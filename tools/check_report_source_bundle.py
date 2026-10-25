#!/usr/bin/env python3
"""Inspect the exact R1 handover ZIP *before* any source import.

Read-only, standard-library tooling: never extracts archive members and never
changes the checkout. This is a structural/provenance preflight, NOT evidence
of editorial approval or permission to activate report/4 or Premium reading/2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "inktrospect-report-build-spec/1.0"
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 384
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED = 24 * 1024 * 1024

ROOT_SCHEMAS = (
    "reading-support", "premium-reading-packet", "premium-reading-output",
    "premium-reading-view", "premium-offer", "render-envelope",
)
CONTENT = (
    "proposed/content/presentation/v2/presentation.json",
    "proposed/content/presentation/v2/chapters.json",
    "proposed/content/premium/reading-v2/relations.json",
    "proposed/content/premium/reading-v2/manifest.json",
)
SCHEMAS = tuple(
    f"proposed/contracts/product/v1/schemas/{stem}.schema.json"
    for stem in (*ROOT_SCHEMAS, "common")
)
REVIEW_RECORDS = (
    "FILE_MANIFEST.json",
    "BUILD_DECISIONS.json",
    "WIRING.json",
    "ACCEPTANCE_MATRIX.json",
)
REQUIRED = frozenset((*CONTENT, *SCHEMAS, *REVIEW_RECORDS))
LOCAL_BASELINE = ROOT / "content" / "presentation" / "v1" / "presentation.json"


class SourceBundleError(ValueError):
    """An input cannot be treated as a source for the reviewed R1 import."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise SourceBundleError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _json(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda x: (_ for _ in ()).throw(
                SourceBundleError(f"{name}: non-finite JSON {x}")),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SourceBundleError(f"{name}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceBundleError(f"{name}: expected a JSON object")
    return value


def _validate_entry(info: zipfile.ZipInfo) -> bool:
    """Return True for a regular file, False for a directory; reject links."""
    name = info.filename
    if (not name or "\\" in name or "\x00" in name or name.startswith("/")
            or re.match(r"^[A-Za-z]:", name)
            or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
            or any(ord(char) < 32 for char in name)):
        raise SourceBundleError("unsafe ZIP path")
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG):
        raise SourceBundleError("non-regular ZIP member or symlink")
    if info.is_dir():
        return False
    if info.file_size > MAX_MEMBER_BYTES:
        raise SourceBundleError("oversized ZIP member")
    if info.compress_size == 0 and info.file_size:
        raise SourceBundleError("invalid ZIP compression size")
    return True


def _normalized_names(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    if len(infos) > MAX_MEMBERS:
        raise SourceBundleError("too many ZIP members")
    members: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    total = 0
    for info in infos:
        if not _validate_entry(info):
            continue
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise SourceBundleError("ZIP uncompressed-byte budget exceeded")
        if info.filename.casefold() in folded:
            raise SourceBundleError("duplicate or case-colliding ZIP member")
        folded.add(info.filename.casefold())
        members[info.filename] = info
    # Accept a single, uniform wrapper directory without changing paths.
    if not REQUIRED.issubset(members):
        tops = {name.split("/", 1)[0] for name in members}
        if len(tops) == 1:
            prefix = next(iter(tops)) + "/"
            if all(name.startswith(prefix) for name in members):
                members = {name[len(prefix):]: info for name, info in members.items()}
    missing = sorted(REQUIRED - members.keys())
    if missing:
        raise SourceBundleError("missing R1 source members: " + ", ".join(missing[:6]))
    return members


def _presentation_parity(candidate: dict[str, Any], baseline: dict[str, Any]) -> None:
    if (candidate.get("version"), candidate.get("policy_version")) != (
            "presentation/2", "highlight-policy/2"):
        raise SourceBundleError("presentation v2 version/policy identity mismatch")
    if set(candidate) != set(baseline):
        raise SourceBundleError("presentation v2 shape drift")
    for key in ("locales", "family_order", "primary_families", "threshold_policy",
                "selection_strength_semantics", "feature_labels", "display_domains"):
        if candidate.get(key) != baseline[key]:
            raise SourceBundleError(f"presentation v2 alters frozen {key}")
    if (len(baseline["candidates"]) != 54
            or len(candidate["candidates"]) != 54
            or len(baseline["feature_labels"]) != 64):
        raise SourceBundleError("54-rule/64-label baseline count mismatch")
    before = {row["candidate_id"]: row for row in baseline["candidates"]}
    after = {row.get("candidate_id"): row for row in candidate["candidates"]
             if isinstance(row, dict)}
    if len(after) != 54 or set(after) != set(before):
        raise SourceBundleError("presentation candidate identity drift")
    for name, row in before.items():
        source = {key: value for key, value in row.items() if key != "content_id"}
        proposed = {key: value for key, value in after[name].items() if key != "content_id"}
        if source != proposed:
            raise SourceBundleError("presentation candidate rules/strengths changed")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise SourceBundleError("missing presentation v2 copy catalogue")
    referenced = {candidate.get("fallback_content_id"), *(r.get("content_id") for r in after.values())}
    if (set(content) != referenced or
            any(not isinstance(k, str) or not k.startswith("content.highlight.v2.")
                for k in content)):
        raise SourceBundleError("presentation v2 has unreviewed/missing copy IDs")
    for record in content.values():
        if (not isinstance(record, dict) or set(record) != {"en", "sv"}
                or any(not isinstance(text, str) or not text.strip()
                       for text in record.values())):
            raise SourceBundleError("presentation v2 EN/SV copy is incomplete")


def inspect_bundle(archive: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Return an inspection receipt, explicitly not a source-approval claim."""
    if archive.is_symlink() or not archive.is_file():
        raise SourceBundleError("archive must be a regular file, not a symlink")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SourceBundleError("archive exceeds byte budget")
    if expected_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise SourceBundleError("invalid expected archive SHA256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise SourceBundleError("archive SHA256 does not match recorded authority")
    try:
        with zipfile.ZipFile(archive) as zf:
            members = _normalized_names(zf.infolist())
            blobs: dict[str, bytes] = {}
            hashes: dict[str, str] = {}
            for name in sorted(REQUIRED):
                info = members[name]
                with zf.open(info) as fp:
                    raw = fp.read(MAX_MEMBER_BYTES + 1)
                if len(raw) != info.file_size or len(raw) > MAX_MEMBER_BYTES:
                    raise SourceBundleError("ZIP member decompression limit mismatch")
                blobs[name] = raw
                hashes[name] = hashlib.sha256(raw).hexdigest()
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
        raise SourceBundleError("invalid/corrupt handover ZIP") from exc

    baseline = _json(LOCAL_BASELINE.read_bytes(), str(LOCAL_BASELINE))
    presentation = _json(blobs[CONTENT[0]], CONTENT[0])
    _presentation_parity(presentation, baseline)
    for name in (*CONTENT[1:], *SCHEMAS, *REVIEW_RECORDS):
        value = _json(blobs[name], name)
        if name.startswith("proposed/contracts/"):
            schema_file = name.rsplit("/", 1)[-1]
            if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or value.get("$id") != schema_file:
                raise SourceBundleError(f"{name}: schema identity mismatch")
    manifest = _json(blobs["FILE_MANIFEST.json"], "FILE_MANIFEST.json")
    if manifest.get("spec_version") != VERSION or manifest.get("baseline") != (
            "0c50c577231ae633c6910114f1dad731ffc7a978"):
        raise SourceBundleError("manifest version/baseline mismatch")
    if not isinstance(manifest.get("operations"), list) or len(manifest["operations"]) != 127:
        raise SourceBundleError("manifest is not the complete 127-path implementation plan")
    return {
        "status": "STRUCTURAL_PREFLIGHT_ONLY_NOT_APPROVED",
        "spec_version": VERSION,
        "baseline": manifest["baseline"],
        "archive_sha256": digest,
        "archive_sha256_pinned": expected_sha256 is not None,
        "review_required": True,
        "required_members_checked": len(hashes),
        "member_sha256": hashes,
        "v1_presentation_sha256": hashlib.sha256(LOCAL_BASELINE.read_bytes()).hexdigest(),
        "candidate_count": 54,
        "feature_label_count": 64,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-sha256", help="Independently recorded authoritative ZIP digest")
    args = parser.parse_args()
    try:
        receipt = inspect_bundle(args.archive, expected_sha256=args.expected_sha256)
    except SourceBundleError as exc:
        print("FAIL: " + str(exc))
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
