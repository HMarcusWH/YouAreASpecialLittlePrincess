"""Internal synthetic qualification worker, not an independently trusted entrypoint.

Start with an independently provisioned out-of-checkout qualification_bootstrap.py.
This worker checks a policy-approved staged commit before importing any project
code. Direct execution from this checkout is not a trusted invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _checked_subprocess(command, *, cwd):
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True,
        timeout=90, check=False,
    )
    if result.returncode:
        raise ValueError("reviewed checkout staging failed")
    return result.stdout.strip()




_APPROVED_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAX_POLICY_BYTES = 128 * 1024


def _verified_policy_revision(args) -> str:
    """Authenticate the independently approved source revision before imports.

    A clean, detached worktree is not itself authority: a committed malicious
    revision must never execute merely because it matches its own Git HEAD.
    """
    expected = args.approved_digest_file.read_text(encoding="ascii").strip()
    if not _APPROVED_SHA256.fullmatch(expected):
        raise ValueError("independently approved policy digest required")
    with args.policy.open("rb") as stream:
        raw = stream.read(_MAX_POLICY_BYTES + 1)
    if len(raw) > _MAX_POLICY_BYTES or not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), expected
    ):
        raise ValueError("frozen policy differs from prior approval")

    def strict_object(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate frozen policy field")
            obj[key] = value
        return obj

    def invalid_constant(value):
        raise ValueError("nonfinite frozen policy constant")

    policy = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object,
                        parse_constant=invalid_constant)
    if not isinstance(policy, dict) or policy.get("schema_version") != 2 or (
        policy.get("mode") != "synthetic" or policy.get("profile") != "qualified-v2"
    ):
        raise ValueError("unapproved frozen qualification mode")
    commit = policy.get("source_commit_sha")
    if not isinstance(commit, str) or not _COMMIT_SHA.fullmatch(commit):
        raise ValueError("invalid independently approved source revision")
    return commit


_INPUT_FILES = ("development", "validation", "holdout", "policy", "approved_digest_file")
_INPUT_DIRECTORIES = ("image_root",)


def _resolve_input_arguments(args):
    """Bind user-selected paths to the original invocation directory."""
    for name in _INPUT_FILES + _INPUT_DIRECTORIES + ("wheelhouse",):
        value = getattr(args, name)
        if value is None:
            continue
        resolved = value.resolve(strict=True)
        if name in _INPUT_DIRECTORIES or name == "wheelhouse":
            if not resolved.is_dir():
                raise ValueError("invalid reviewed input directory")
        elif not resolved.is_file():
            raise ValueError("invalid reviewed input file")
        setattr(args, name, resolved)
    return args


def _verify_staged_worktree(root: Path, approved_revision: str) -> None:
    """Check source provenance BEFORE any project module can be imported.

    A hidden worker argument is not authority. Direct calls from an ordinary
    checkout or a modified detached checkout are rejected before sys.path
    admits any project code. The trusted host and Git objects remain assumptions.
    """
    git_pointer = root / ".git"
    if not git_pointer.is_file() or git_pointer.is_symlink():
        raise ValueError("staged worker requires a detached worktree")
    revision = _checked_subprocess(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root
    )
    if revision != approved_revision:
        raise ValueError("staged source does not match independently approved policy revision")
    common_dir = Path(_checked_subprocess(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root
    )).resolve(strict=True)
    git_dir = Path(_checked_subprocess(
        ["git", "rev-parse", "--path-format=absolute", "--git-dir"], cwd=root
    )).resolve(strict=True)
    if git_dir == common_dir or not git_dir.is_relative_to(common_dir / "worktrees"):
        raise ValueError("worker was not launched from a detached Git worktree")
    branch = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=root,
        capture_output=True, text=True, timeout=10, check=False,
    )
    if branch.returncode != 1:
        raise ValueError("worker checkout is not detached")
    # Git's normal porcelain status hides ignored files. Those include
    # arbitrary executable code under build/, dist/ and .venv/, so include
    # ignored files in the source-stage integrity check.
    if _checked_subprocess([
        "git", "status", "--porcelain", "--ignored=matching",
        "--untracked-files=all",
    ], cwd=root):
        raise ValueError("staged checkout contains unreviewed changes")
    for path in (root / "evaluation" / "segmentation" / "run_qualification.py",
                 root / "evaluation" / "segmentation" / "qualification.py",
                 root / "evaluation" / "segmentation" / "runtime_integrity.py"):
        canonical = subprocess.run(
            ["git", "show", f"{revision}:{path.relative_to(root).as_posix()}"],
            cwd=root, capture_output=True, timeout=20, check=False,
        )
        if canonical.returncode or path.is_symlink() or canonical.stdout != path.read_bytes():
            raise ValueError("staged executable differs from reviewed commit")
    if any(root.rglob("*.pyc")):
        raise ValueError("staged source contains unreviewed bytecode")


class _QualificationPhaseError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_SANITIZED_FAILURES = {
    "Q_WHEEL": (
        ("missing or redirected locked executable artifact", "Q_WHEEL_MISSING"),
        ("installed file differs from authenticated locked wheel", "Q_WHEEL_HASH"),
        ("unreviewed installed bytecode cache", "Q_WHEEL_CACHE"),
        ("unreviewed installed native library", "Q_WHEEL_NATIVE"),
        ("wheel archive differs", "Q_WHEEL_ARCHIVE"),
        ("wheel not uniquely present", "Q_WHEEL_LOCK"),
        ("missing reviewed wheel artifact", "Q_WHEEL_LOCK"),
        ("invalid Root-Is-Purelib", "Q_WHEEL_METADATA"),
        ("lacks unique WHEEL metadata", "Q_WHEEL_METADATA"),
        ("wheel payload", "Q_WHEEL_PAYLOAD"),
        ("wheel install scheme", "Q_WHEEL_LAYOUT"),
    ),
    "Q_IDENTITY": (
        ("unreviewed imported evaluation module", "Q_IDENTITY_IMPORT"),
        ("reviewed dependency versions", "Q_IDENTITY_DEPENDENCIES"),
        ("installed environment differs", "Q_IDENTITY_LOCKSET"),
        ("source checkout contains", "Q_IDENTITY_DIRTY"),
        ("source revision", "Q_IDENTITY_REVISION"),
        ("dependency snapshot", "Q_IDENTITY_DEPENDENCIES"),
        ("source checkout cleanliness", "Q_IDENTITY_DIRTY"),
        ("unreviewed lock verifier", "Q_IDENTITY_VERIFIER"),
        ("modified numerical", "Q_IDENTITY_WHEEL"),
    ),
}


def _phase(code: str, fn):
    """Emit fixed, privacy-safe reason categories, never raw error messages."""
    try:
        return fn()
    except Exception as exc:
        reason = str(exc)
        for marker, label in _SANITIZED_FAILURES.get(code, ()):
            if marker in reason:
                if label == "Q_WHEEL_HASH":
                    package = re.search(
                        r"\[([a-z0-9-]{1,40}):([a-zA-Z0-9_./-]{1,300})\]", reason
                    )
                    if package:
                        # Report only a public wheel member basename, NEVER
                        # an installed absolute path or private specimen path.
                        member = "_".join(package.group(2).split("/")[-2:])
                        component = re.sub(r"[^A-Z0-9]", "_", member.upper())[-42:]
                        label += "_" + package.group(1).upper().replace("-", "_")
                        label += "_" + component
                        label = label[:90]
                raise _QualificationPhaseError(label) from exc
        raise _QualificationPhaseError(code + "_OTHER") from exc


def _staged_worker(args) -> int:
    root = Path(__file__).resolve(strict=True).parents[2]
    def verify_policy_and_source():
        if any(not getattr(args, name).is_absolute()
               for name in _INPUT_FILES + _INPUT_DIRECTORIES):
            raise ValueError("worker input paths not frozen")
        revision = _verified_policy_revision(args)
        _verify_staged_worktree(root, revision)
    _phase("Q_SOURCE", verify_policy_and_source)

    # The entire source stage is checked *before* the first project import.
    original = tuple(sys.path)
    sys.path[:] = list(original) + [str(root / "src"), str(root)]
    from evaluation.segmentation.runtime_integrity import (
        _site_roots, preflight_reviewed_environment,
    )
    sites = _phase("Q_SITE", _site_roots)
    _phase("Q_WHEEL", lambda: preflight_reviewed_environment(root))
    # Both logical wheel targets must be preserved for file authentication,
    # but duplicate physical site paths would make importlib.metadata discover
    # each installed distribution twice and fail the closed lock-set check.
    sys.path.extend(str(site) for site in dict.fromkeys(sites))

    def import_reviewed_components():
        from evaluation.segmentation.qualification import (
            current_local_identity, public_safe_receipt,
            run_frozen_synthetic_qualification,
        )
        return current_local_identity, public_safe_receipt, run_frozen_synthetic_qualification

    identity_fn, redact_fn, qualify_fn = _phase("Q_IMPORT", import_reviewed_components)
    _phase("Q_IDENTITY", identity_fn)

    def score_reviewed_holdout():
        approved_digest = args.approved_digest_file.read_text(encoding="ascii").strip()
        return qualify_fn(
            args.development, args.validation, args.holdout, args.policy,
            args.image_root, expected_policy_sha256=approved_digest,
        )

    engineering = _phase("Q_SCORE", score_reviewed_holdout)
    receipt = _phase("Q_RECEIPT", lambda: redact_fn(engineering))
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen synthetic engineering evaluation")
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--approved-digest-file", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--_staged", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode) or sys.flags.optimize != 0:
        parser.exit(2, "Isolation requires python -I -S -B.\n")
    if not args._staged:
        # The authoritative entrypoint is the independently provisioned
        # tools/qualification_bootstrap.py, executed OUTSIDE this checkout.
        # A repository script cannot authenticate itself before its top-level
        # code has already run.
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_BOOTSTRAP]; details withheld.\n")
    try:
        if args.wheelhouse is not None:
            os.environ["QUALIFICATION_WHEELHOUSE"] = str(args.wheelhouse.resolve(strict=True))
        return _staged_worker(args)
    except _QualificationPhaseError as exc:
        parser.exit(2, f"Frozen synthetic evaluation rejected [{exc.code}]; details withheld.\n")
    except Exception:
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_UNKNOWN]; details withheld.\n")


if __name__ == "__main__":
    raise SystemExit(main())
