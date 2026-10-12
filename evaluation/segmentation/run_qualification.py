"""Isolated, synthetic-only frozen-qualification entrypoint.

Invoke with python -I to exclude CWD and PYTHONPATH from initial imports.
Outputs only an explicitly privacy-redacted summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen synthetic engineering evaluation")
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--approved-digest-file", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.exit(2, "Isolation required; run with python -I.\n")

    try:
        # Import numerical wheels BEFORE admitting the checkout to sys.path.
        import cv2  # noqa: F401
        import numpy  # noqa: F401

        repository = Path(__file__).resolve(strict=True).parents[2]
        sys.path.insert(0, str(repository))
        sys.path.insert(0, str(repository / "src"))
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
    except Exception:
        # Never reveal protected paths, private annotations or specimen IDs.
        parser.exit(2, "Frozen synthetic evaluation rejected; details withheld.\n")


if __name__ == "__main__":
    raise SystemExit(main())
