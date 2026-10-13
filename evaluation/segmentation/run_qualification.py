"""Offline frozen synthetic qualification with independently staged execution.

Run: python -I -S -B evaluation/segmentation/run_qualification.py ...
No checkout code, cached bytecode or third-party wheels are imported until a
fresh reviewed worktree and original locked wheels have been authenticated.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


def _checked_subprocess(command, *, cwd):
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True,
        timeout=90, check=False,
    )
    if result.returncode:
        raise ValueError("reviewed checkout staging failed")
    return result.stdout.strip()



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


def _verify_staged_worktree(root: Path) -> None:
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
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("invalid staged source revision")
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


def _staged_worker(args) -> int:
    root = Path(__file__).resolve(strict=True).parents[2]
    _verify_staged_worktree(root)
    if any(not getattr(args, name).is_absolute()
           for name in _INPUT_FILES + _INPUT_DIRECTORIES):
        raise ValueError("worker inputs must be bound to original absolute paths")
    original = tuple(sys.path)
    project_paths = (str(root / "src"), str(root))
    sites = tuple(dict.fromkeys(
        sysconfig.get_paths()[key] for key in ("purelib", "platlib")
    ))
    # -I -S uses interpreter/stdlib paths only; append, never prepend, sources.
    # The approved third-party paths are not admitted until preflight finishes.
    sys.path[:] = list(original) + list(project_paths)
    from evaluation.segmentation.runtime_integrity import preflight_reviewed_environment

    preflight_reviewed_environment(root)
    sys.path.extend(sites)
    from evaluation.segmentation.qualification import (
        public_safe_receipt, run_frozen_synthetic_qualification,
    )

    approved_digest = args.approved_digest_file.read_text(encoding="ascii").strip()
    receipt = run_frozen_synthetic_qualification(
        args.development, args.validation, args.holdout, args.policy,
        args.image_root, expected_policy_sha256=approved_digest,
    )
    print(json.dumps(public_safe_receipt(receipt), sort_keys=True, allow_nan=False))
    return 0


def _stage_and_execute(args) -> int:
    _resolve_input_arguments(args)
    original = Path(__file__).resolve(strict=True).parents[2]
    # Never stage edited checkout files: checkout from the reviewed Git object
    # instead, yielding a pristine worktree with no inherited bytecode caches.
    head = _checked_subprocess(["git", "rev-parse", "--verify", "HEAD"], cwd=original)
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        raise ValueError("invalid source revision")
    source = Path(__file__).read_bytes()
    canonical = subprocess.run(
        ["git", "show", f"{head}:evaluation/segmentation/run_qualification.py"],
        cwd=original, capture_output=True, check=False, timeout=20,
    )
    if canonical.returncode != 0 or canonical.stdout != source:
        raise ValueError("unreviewed qualification launcher source")
    with tempfile.TemporaryDirectory(prefix="frozen-qualification-") as temp:
        stage = Path(temp) / "checkout"
        _checked_subprocess([
            "git", "-c", "core.hooksPath=/dev/null", "worktree",
            "add", "--detach", str(stage), head,
        ], cwd=original)
        try:
            if _checked_subprocess(["git", "rev-parse", "HEAD"], cwd=stage) != head:
                raise ValueError("staged source revision mismatch")
            if _checked_subprocess([
                "git", "status", "--porcelain", "--untracked-files=all"
            ], cwd=stage):
                raise ValueError("unreviewed staged source changes")
            entry = stage / "evaluation" / "segmentation" / "run_qualification.py"
            cmd = [
                sys.executable, "-I", "-S", "-B", str(entry), "--_staged",
                "--development", str(args.development),
                "--validation", str(args.validation),
                "--holdout", str(args.holdout),
                "--policy", str(args.policy),
                "--approved-digest-file", str(args.approved_digest_file),
                "--image-root", str(args.image_root),
            ]
            if args.wheelhouse is not None:
                cmd.extend(["--wheelhouse", str(args.wheelhouse)])
            env = {k: v for k, v in os.environ.items() if not k.startswith(
                ("PYTHON", "GIT_", "PIP_")
            )}
            if args.wheelhouse is not None:
                env["QUALIFICATION_WHEELHOUSE"] = str(args.wheelhouse)
            output = subprocess.run(
                cmd, cwd=stage, env=env, capture_output=True, text=True,
                timeout=240, check=False,
            )
            if output.returncode:
                raise ValueError("isolated qualification failed")
            # The staged child already emits only public_safe_receipt JSON.
            record = json.loads(output.stdout)
            if (record.get("mode") != "synthetic"
                    or record.get("data_origin") != "SYNTHETIC_FIXTURE"
                    or record.get("public_qualification") != "NOT_AUTHORIZED"):
                raise ValueError("untrusted qualification receipt")
            print(json.dumps(record, sort_keys=True, allow_nan=False))
            return 0
        finally:
            subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null",
                 "worktree", "remove", "--force", str(stage)],
                cwd=original, capture_output=True, timeout=60, check=False,
            )


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
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode):
        parser.exit(2, "Isolation requires python -I -S -B.\n")
    try:
        if args.wheelhouse is not None:
            os.environ["QUALIFICATION_WHEELHOUSE"] = str(args.wheelhouse.resolve(strict=True))
        return _staged_worker(args) if args._staged else _stage_and_execute(args)
    except Exception:
        # Never publish paths, private records, untrusted stderr or stack traces.
        parser.exit(2, "Frozen synthetic evaluation rejected; details withheld.\n")


if __name__ == "__main__":
    raise SystemExit(main())
