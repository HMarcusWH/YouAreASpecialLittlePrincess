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
import zlib
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


# The external bootstrap is the trust root: no helper is imported from a
# caller-controlled checkout. Only exact SHA-1 Git objects are ever staged.
_MAX_SOURCE_OBJECTS = 16000
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_OBJECT_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_DEPTH = 32
_GIT_BINARY = "/usr/bin/git"


def _git_environment(private: Path) -> dict:
    """No inherited Git config, replacement refs, prompts or lazy-fetch hooks."""
    home, xdg, template = (private / "home", private / "xdg", private / "empty-template")
    for folder in (home, xdg, template):
        folder.mkdir(exist_ok=True, mode=0o700)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home), "XDG_CONFIG_HOME": str(xdg),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
        "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_TEMPLATE_DIR": str(template), "LC_ALL": "C",
    }


def _git(args, *, cwd: Path, env: dict, timeout: int = 90,
         input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    if not Path(_GIT_BINARY).is_file():
        raise _Rejected("Q_SOURCE")
    try:
        completed = subprocess.run(
            [_GIT_BINARY, "--no-replace-objects", "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd, env=env, input=input_bytes, capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _Rejected("Q_SOURCE") from exc
    if completed.returncode:
        raise _Rejected("Q_SOURCE")
    return completed


def _verified_object_batch(source: Path, object_ids: list[str],
                           env: dict) -> dict[str, tuple[str, bytes]]:
    """Read packed/loose objects by exact SHA, with no revision/ref replacement."""
    unique = list(dict.fromkeys(object_ids))
    if not unique:
        return {}
    if len(unique) > _MAX_SOURCE_OBJECTS or any(
        not _REVISION.fullmatch(key) for key in unique
    ):
        raise _Rejected("Q_SOURCE")
    request = ("\n".join(unique) + "\n").encode("ascii")
    listing = _git(["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                   cwd=source, env=env, input_bytes=request).stdout.splitlines()
    if len(listing) != len(unique):
        raise _Rejected("Q_SOURCE")
    kinds, sizes = [], []
    total = 0
    for key, line in zip(unique, listing):
        tokens = line.split(b" ")
        if (len(tokens) != 3 or tokens[0] != key.encode("ascii")
                or tokens[1] not in (b"commit", b"tree", b"blob")
                or not tokens[2].isdigit()):
            raise _Rejected("Q_SOURCE")
        size = int(tokens[2])
        total += size
        if size > _MAX_OBJECT_BYTES or total > _MAX_SOURCE_BYTES:
            raise _Rejected("Q_SOURCE")
        kinds.append(tokens[1].decode("ascii"))
        sizes.append(size)
    output = _git(["cat-file", "--batch"], cwd=source, env=env,
                  input_bytes=request).stdout
    pos, found = 0, {}
    for key, kind, size in zip(unique, kinds, sizes):
        end = output.find(b"\n", pos)
        if end < 0 or output[pos:end] != (
            key + " " + kind + " " + str(size)
        ).encode("ascii"):
            raise _Rejected("Q_SOURCE")
        pos = end + 1
        payload = output[pos:pos + size]
        if len(payload) != size or output[pos + size:pos + size + 1] != b"\n":
            raise _Rejected("Q_SOURCE")
        pos += size + 1
        actual = hashlib.sha1(
            (kind + " " + str(size)).encode("ascii") + b"\x00" + payload
        ).hexdigest()
        if not hmac.compare_digest(actual, key):
            raise _Rejected("Q_SOURCE")
        found[key] = (kind, payload)
    if pos != len(output):
        raise _Rejected("Q_SOURCE")
    return found


def _approved_tree(source: Path, revision: str, env: dict):
    """Walk only the SHA-authenticated commit tree; reject exotic file modes."""
    objects = _verified_object_batch(source, [revision], env)
    kind, commit_bytes = objects[revision]
    if kind != "commit":
        raise _Rejected("Q_SOURCE")
    tree_lines = [
        line[5:] for line in commit_bytes.split(b"\n\n", 1)[0].splitlines()
        if line.startswith(b"tree ")
    ]
    if len(tree_lines) != 1 or not _REVISION.fullmatch(
        tree_lines[0].decode("ascii", errors="replace")
    ):
        raise _Rejected("Q_SOURCE")
    pending = [(tree_lines[0].decode("ascii"), "", 0)]
    files, directories, seen_paths = [], set(), set()
    total_bytes, item_count = 0, 0
    while pending:
        batch = list(dict.fromkeys(key for key, _, _ in pending if key not in objects))
        for offset in range(0, len(batch), 256):
            objects.update(_verified_object_batch(source, batch[offset:offset + 256], env))
        children = []
        for tree_sha, prefix, depth in pending:
            if depth > _MAX_SOURCE_DEPTH or objects[tree_sha][0] != "tree":
                raise _Rejected("Q_SOURCE")
            raw = objects[tree_sha][1]
            cursor, local_names = 0, set()
            while cursor < len(raw):
                space = raw.find(b" ", cursor)
                nul = raw.find(b"\x00", space + 1)
                if space < 0 or nul < 0 or nul + 21 > len(raw):
                    raise _Rejected("Q_SOURCE")
                mode, encoded = raw[cursor:space], raw[space + 1:nul]
                cursor = nul + 21
                try:
                    name = encoded.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise _Rejected("Q_SOURCE") from exc
                if (not name or name in (".", "..") or "/" in name
                        or "\\" in name or "\x00" in name
                        or name.casefold() == ".git"
                        or name.casefold() in local_names):
                    raise _Rejected("Q_SOURCE")
                local_names.add(name.casefold())
                path = prefix + name
                if path in seen_paths:
                    raise _Rejected("Q_SOURCE")
                seen_paths.add(path)
                sha = raw[nul + 1:nul + 21].hex()
                item_count += 1
                if item_count > _MAX_SOURCE_OBJECTS:
                    raise _Rejected("Q_SOURCE")
                if mode in (b"40000", b"040000"):
                    directories.add(path)
                    children.append((sha, path + "/", depth + 1))
                elif mode in (b"100644", b"100755"):
                    files.append((path, mode.decode("ascii"), sha))
                else:
                    # No symlinks, gitlinks, special files or unknown extensions.
                    raise _Rejected("Q_SOURCE")
        pending = children
    blob_ids = list(dict.fromkeys(sha for _, _, sha in files))
    for offset in range(0, len(blob_ids), 256):
        batch = [sha for sha in blob_ids[offset:offset + 256] if sha not in objects]
        objects.update(_verified_object_batch(source, batch, env))
    for path, _mode, sha in files:
        if objects[sha][0] != "blob" or path.endswith(".pyc"):
            raise _Rejected("Q_SOURCE")
        total_bytes += len(objects[sha][1])
        if total_bytes > _MAX_SOURCE_BYTES:
            raise _Rejected("Q_SOURCE")
    if len(objects) > _MAX_SOURCE_OBJECTS:
        raise _Rejected("Q_SOURCE")
    return objects, sorted(directories, key=lambda p: (p.count("/"), p)), files


def _stage_approved_source(source: Path, revision: str, private: Path):
    """Copy authenticated raw objects to a new Git store, never checkout source."""
    env = _git_environment(private)
    objects, dirs, files = _approved_tree(source, revision, env)
    isolated = private / "reviewed.git"
    stage = private / "checkout"
    _git(["init", "--bare", "--template", str(private / "empty-template"),
          str(isolated)], cwd=private, env=env)
    for sha, (kind, data) in objects.items():
        path = isolated / "objects" / sha[:2] / sha[2:]
        path.parent.mkdir(mode=0o700, exist_ok=True)
        encoded = zlib.compress(
            (kind + " " + str(len(data))).encode("ascii") + b"\x00" + data
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    _git(["--git-dir", str(isolated), "worktree", "add", "--no-checkout",
          "--detach", str(stage), revision], cwd=private, env=env)
    for dirname in dirs:
        (stage / dirname).mkdir(mode=0o700, parents=True, exist_ok=False)
    approved_paths = {}
    for name, mode, sha in files:
        path = stage / name
        if not path.parent.is_dir():
            raise _Rejected("Q_SOURCE")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(objects[sha][1])
        path.chmod(0o755 if mode == "100755" else 0o644)
        approved_paths[name] = (mode, sha)
    # This updates ONLY the isolated index; no Git checkout conversion/filter.
    _git(["read-tree", "--reset", revision], cwd=stage, env=env)
    if _git(["rev-parse", "--verify", "HEAD"], cwd=stage, env=env).stdout.strip() != (
        revision.encode("ascii")
    ):
        raise _Rejected("Q_SOURCE")
    all_paths = {p.relative_to(stage).as_posix() for p in stage.rglob("*")}
    if all_paths != {".git", *dirs, *approved_paths}:
        raise _Rejected("Q_SOURCE")
    for name, (mode, digest) in approved_paths.items():
        path = stage / name
        if (path.is_symlink() or not path.is_file()
                or (path.stat().st_mode & 0o777) != (0o755 if mode == "100755" else 0o644)
                or hashlib.sha1(
                    b"blob " + str(path.stat().st_size).encode("ascii")
                    + b"\x00" + path.read_bytes()
                ).hexdigest() != digest):
            raise _Rejected("Q_SOURCE")
    if _git(["status", "--porcelain", "--ignored=matching", "--untracked-files=all"],
            cwd=stage, env=env).stdout.strip():
        raise _Rejected("Q_SOURCE")
    entry = stage / _RUNNER_PATH
    if not entry.is_file() or entry.is_symlink():
        raise _Rejected("Q_SOURCE")
    return stage, env


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

    # Read only authenticated objects. The caller-controlled repository is
    # never checked out or used for mutable worktree operations.
    with tempfile.TemporaryDirectory(prefix="frozen-qualification-") as temp:
        private = Path(temp)
        stage, git_env = _stage_approved_source(source, revision, private)
        entry = stage / _RUNNER_PATH
        try:
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
                # Preserve no ambient Git/Python/loader configuration.
                env = dict(git_env)
                if args.wheelhouse is not None:
                    env["QUALIFICATION_WHEELHOUSE"] = str(args.wheelhouse)
                elif os.environ.get("QUALIFICATION_WHEELHOUSE"):
                    env["QUALIFICATION_WHEELHOUSE"] = os.environ["QUALIFICATION_WHEELHOUSE"]
                elif os.environ.get("RUNNER_TEMP"):
                    env["RUNNER_TEMP"] = os.environ["RUNNER_TEMP"]
                # Some reviewed CI interpreters need their own libpython path.
                base_lib = Path(sys.base_prefix).resolve() / "lib"
                if base_lib.is_dir():
                    env["LD_LIBRARY_PATH"] = str(base_lib)
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
            # TemporaryDirectory owns both the isolated object store and stage.
            # Never mutate the source repository's worktree registrations.
            pass


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
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode) or sys.flags.optimize != 0:
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_ISOLATION]; details withheld.\n")
    try:
        return _run(args)
    except _Rejected as exc:
        parser.exit(2, f"Frozen synthetic evaluation rejected [{exc.code}]; details withheld.\n")
    except Exception:
        parser.exit(2, "Frozen synthetic evaluation rejected [Q_UNKNOWN]; details withheld.\n")


if __name__ == "__main__":
    raise SystemExit(main())
