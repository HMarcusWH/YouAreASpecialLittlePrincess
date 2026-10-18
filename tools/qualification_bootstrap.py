"""Externally provisioned stdlib-only bootstrap for synthetic qualification.

IMPORTANT: this file inside the repository is a DISTRIBUTION TEMPLATE.
Copy it to an independently controlled location and verify its own SHA-256
against an independently approved digest BEFORE running it. Executing an
unchecked copy from the checkout being evaluated is NOT trusted execution.

Only a trusted OS/interpreter, Git object database, verified policy approval
and separately installed bootstrap are assumed. No human data authorization.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_REJECTED = re.compile(r"\[(Q_[A-Z0-9_]{1,100})\]")
_MAX_POLICY_BYTES = 128 * 1024
_RUNNER_PATH = "evaluation/segmentation/run_qualification.py"
_FILES = ("development", "validation", "holdout", "policy", "approved_digest_file")
_DIRS = ("image_root",)


class _Rejected(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _git(args, *, cwd: Path, timeout: int = 90) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd, capture_output=True, timeout=timeout, check=False,
    )
    if completed.returncode:
        raise _Rejected("Q_SOURCE")
    return completed


def _validated_policy_sha(args) -> str:
    try:
        digest = args.approved_digest_file.read_text(encoding="ascii").strip()
        if not _DIGEST.fullmatch(digest):
            raise ValueError("invalid review digest")
        with args.policy.open("rb") as stream:
            raw = stream.read(_MAX_POLICY_BYTES + 1)
        if (len(raw) > _MAX_POLICY_BYTES
                or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest)):
            raise ValueError("unapproved policy")
        def strict_pairs(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("duplicate policy key")
                obj[key] = value
            return obj
        def reject_constant(value):
            raise ValueError("nonfinite policy value")
        policy = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_pairs,
                            parse_constant=reject_constant)
        if (not isinstance(policy, dict) or policy.get("schema_version") != 2
                or policy.get("mode") != "synthetic"
                or policy.get("profile") != "qualified-v2"):
            raise ValueError("invalid frozen policy")
        revision = policy.get("source_commit_sha")
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            raise ValueError("invalid approved source revision")
        return revision, raw, digest.encode("ascii")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise _Rejected("Q_POLICY") from exc


def _absolute_inputs(args):
    try:
        for name in _FILES + _DIRS + ("wheelhouse", "repository"):
            value = getattr(args, name)
            if value is None:
                continue
            resolved = value.resolve(strict=True)
            if name in _DIRS + ("wheelhouse", "repository"):
                if not resolved.is_dir():
                    raise ValueError("invalid directory")
            elif not resolved.is_file():
                raise ValueError("invalid file")
            setattr(args, name, resolved)
    except (OSError, ValueError, TypeError) as exc:
        raise _Rejected("Q_INPUT") from exc



def _sealed_snapshot(data: bytes, label: str) -> int:
    """Create a kernel-sealed, read-only-in-practice approval snapshot.

    Linux memfd seals prohibit replacement or mutation while the child reads
    /proc/self/fd/N. No plaintext policy path or approval digest is logged.
    """
    if not hasattr(os, "memfd_create") or not hasattr(os, "MFD_ALLOW_SEALING"):
        raise _Rejected("Q_POLICY")
    fd = os.memfd_create("qualification-" + label, os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    try:
        with os.fdopen(os.dup(fd), "wb") as output:
            output.write(data)
            output.flush()
        fcntl.fcntl(
            fd, fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
        )
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE == 0:
            raise OSError("policy snapshot not sealed")
        return fd
    except Exception as exc:
        os.close(fd)
        raise _Rejected("Q_POLICY") from exc


def _run(args) -> int:
    # Path binding is performed BEFORE any working directory change.
    _absolute_inputs(args)
    revision, frozen_policy, frozen_approval = _validated_policy_sha(args)
    source = args.repository

    # Never execute the checked-out launcher or use the unapproved current
    # checkout HEAD as authority. Get the launcher from the Git object
    # identified by the independently approved policy revision.
    object_bytes = _git(["show", revision + ":" + _RUNNER_PATH], cwd=source).stdout
    if not object_bytes:
        raise _Rejected("Q_SOURCE")
    with tempfile.TemporaryDirectory(prefix="frozen-qualification-") as temp:
        stage = Path(temp) / "checkout"
        _git(["worktree", "add", "--detach", str(stage), revision], cwd=source)
        try:
            if _git(["rev-parse", "--verify", "HEAD"], cwd=stage).stdout.strip().decode("ascii") != revision:
                raise _Rejected("Q_SOURCE")
            # Do not accidentally trust ignored or untracked executables.
            if _git(["status", "--porcelain", "--ignored=matching",
                     "--untracked-files=all"], cwd=stage).stdout.strip():
                raise _Rejected("Q_SOURCE")
            entry = stage / _RUNNER_PATH
            if entry.is_symlink() or entry.read_bytes() != object_bytes:
                raise _Rejected("Q_SOURCE")
            # The authenticated policy and digest must not be reopened via
            # attacker-mutable original paths after this point. Sealed fd
            # snapshots survive a simultaneous policy+approval rotation.
            policy_fd = _sealed_snapshot(frozen_policy, "policy")
            try:
                approval_fd = _sealed_snapshot(frozen_approval, "approval")
            except Exception:
                os.close(policy_fd)
                raise
            try:
                cmd = [
                    sys.executable, "-I", "-S", "-B", str(entry), "--_staged",
                    "--development", str(args.development),
                    "--validation", str(args.validation),
                    "--holdout", str(args.holdout),
                    "--policy", f"/proc/self/fd/{policy_fd}",
                    "--approved-digest-file", f"/proc/self/fd/{approval_fd}",
                    "--image-root", str(args.image_root),
                ]
                if args.wheelhouse is not None:
                    cmd.extend(["--wheelhouse", str(args.wheelhouse)])
                env = {k: v for k, v in os.environ.items() if not k.startswith(
                    ("PYTHON", "GIT_", "PIP_")
                )}
                if args.wheelhouse is not None:
                    env["QUALIFICATION_WHEELHOUSE"] = str(args.wheelhouse)
                proc = subprocess.run(
                    cmd, cwd=stage, env=env, capture_output=True, text=True,
                    timeout=240, check=False, pass_fds=(policy_fd, approval_fd),
                )
            finally:
                os.close(approval_fd)
                os.close(policy_fd)
            if proc.returncode:
                match = _REJECTED.search(proc.stderr)
                raise _Rejected(match.group(1) if match else "Q_WORKER")
            try:
                receipt = json.loads(proc.stdout)
                if (not isinstance(receipt, dict)
                        or set(receipt) != {
                            "kind", "mode", "data_origin", "blank_evidence_scope",
                            "public_qualification", "decision", "specimen_count", "metrics",
                        }
                        or receipt["kind"] != "segmentation-public-summary/1"
                        or receipt["mode"] != "synthetic"
                        or receipt["data_origin"] != "SYNTHETIC_FIXTURE"
                        or receipt["blank_evidence_scope"] != "SYNTHETIC_FIXTURE_ORACLE_ONLY"
                        or receipt["public_qualification"] != "NOT_AUTHORIZED"
                        or receipt["decision"] not in ("ENGINEERING_PASS", "ENGINEERING_FAIL")):
                    raise ValueError("not a redacted frozen receipt")
            except (ValueError, TypeError, KeyError) as exc:
                raise _Rejected("Q_RECEIPT") from exc
            print(json.dumps(receipt, sort_keys=True, allow_nan=False))
            return 0
        finally:
            subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null",
                 "worktree", "remove", "--force", str(stage)],
                cwd=source, capture_output=True, timeout=60, check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Externally provisioned synthetic qualifier bootstrap")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--approved-digest-file", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_ISOLATION]; details withheld.\n")
    try:
        return _run(args)
    except _Rejected as exc:
        parser.exit(2, f"Frozen synthetic evaluation rejected [{exc.code}]; details withheld.\n")
    except Exception:
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_UNKNOWN]; details withheld.\n")


if __name__ == "__main__":
    raise SystemExit(main())
