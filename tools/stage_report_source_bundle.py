#!/usr/bin/env python3
"""Stage a digest-pinned R1 handover ZIP outside the checkout, without approval.

This offline utility never modifies the repository and never executes bundled
scripts. After preflight it extracts only the known reviewed-source candidates
and a receipt into a private staging directory for independent human review.
It does NOT install /4 copy/contracts, approve source rights or enable Premium.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from check_report_source_bundle import (
    MAX_MEMBER_BYTES, REQUIRED, ROOT, SourceBundleError,
    _normalized_names, inspect_bundle,
)

RECEIPT = "_SOURCE_REVIEW_REQUIRED.json"
ALLOWED_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _validated_destination(destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        raise SourceBundleError("staging destination already exists")
    if not destination.parent.is_dir():
        raise SourceBundleError("staging destination parent must already exist")
    # Do not permit output to escape through a renamed/symlinked ancestor.
    if any(parent.is_symlink() for parent in (destination, *destination.parents)):
        raise SourceBundleError("staging destination must not traverse a symlink")
    # Path.absolute() preserves ".." components and can make a path that
    # physically resolves inside the checkout look lexically outside it.
    # Resolve the entire destination before enforcing the source-review fence.
    final = destination.resolve(strict=False)
    if final.is_relative_to(ROOT.resolve()):
        raise SourceBundleError("refuse to stage unapproved sources inside the repository")
    return final


def _write_private(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    except BaseException:
        # fdopen takes ownership of fd; the temporary tree is removed by caller.
        raise


def stage_archive(archive: Path, destination: Path, *, expected_sha256: str) -> dict[str, Any]:
    """Prepare exact source bytes and hashes for *separate* review.

    The independently recorded archive digest is mandatory. ZIP names never
    choose arbitrary output paths, and the destination cannot be the checkout.
    """
    if not isinstance(expected_sha256, str) or ALLOWED_DIGEST.fullmatch(expected_sha256) is None:
        raise SourceBundleError("an independent 64-digit lowercase source SHA256 pin is mandatory")
    target = _validated_destination(destination)
    receipt = inspect_bundle(archive, expected_sha256=expected_sha256)

    tmp = Path(tempfile.mkdtemp(prefix=".r1-report-review-", dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as zf:
            members = _normalized_names(zf.infolist())
            for name in sorted(REQUIRED):
                info = members[name]
                # Recheck every byte on the second read, preventing accidental
                # mixing from a changing/archive-replaced input.
                with zf.open(info) as opened:
                    payload = opened.read(MAX_MEMBER_BYTES + 1)
                if len(payload) != info.file_size or len(payload) > MAX_MEMBER_BYTES:
                    raise SourceBundleError("staged source size drift")
                if hashlib.sha256(payload).hexdigest() != receipt["member_sha256"][name]:
                    raise SourceBundleError("staged source digest drift")
                # Every member path has already been checked for traversal.
                outfile = tmp.joinpath(*name.split("/"))
                outfile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _write_private(outfile, payload)
        # The entire source ZIP, not merely the required members, must still
        # match the independent pin after all staging reads.
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
            raise SourceBundleError("archive bytes changed during source staging")
        marker = {
            "status": "STAGED_UNREVIEWED_NOT_APPROVED",
            "archive_sha256": receipt["archive_sha256"],
            "spec_version": receipt["spec_version"],
            "baseline": receipt["baseline"],
            "v1_presentation_sha256": receipt["v1_presentation_sha256"],
            "required_members": receipt["required_members_checked"],
            "member_sha256": receipt["member_sha256"],
            "next_steps": [
                "Independently verify author review, source provenance and byte digests.",
                "Reconcile 127-path manifest against current main and regenerate from approved sources.",
                "Keep the /4 writer, Premium provider and commerce default-off.",
            ],
        }
        _write_private(
            tmp / RECEIPT,
            (json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        if target.exists() or target.is_symlink():
            raise SourceBundleError("staging destination appeared during verification")
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp)
        raise
    return marker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path, required=True,
                        help="New staging folder outside the repository (must not exist)")
    parser.add_argument("--expected-sha256", required=True,
                        help="Independently verified original source ZIP SHA256")
    args = parser.parse_args()
    try:
        record = stage_archive(args.archive, args.destination,
                               expected_sha256=args.expected_sha256)
    except (SourceBundleError, OSError, zipfile.BadZipFile) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps({
        "status": record["status"],
        "archive_sha256": record["archive_sha256"],
        "required_members": record["required_members"],
        "review_required": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
