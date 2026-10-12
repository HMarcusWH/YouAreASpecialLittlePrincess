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


def _staged_worker(args) -> int:
    root = Path(__file__).resolve(strict=True).parents[2]
    for dirname in ("src", "evaluation", "tools"):
        # The staged checkout was newly created from Git and must remain free
        # of inherited .pyc / __pycache__ files before any project import.
        if any(root.joinpath(dirname).rglob("*.pyc")):
            raise ValueError("cached bytecode in reviewed source")
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
