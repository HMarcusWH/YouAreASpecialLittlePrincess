"""T11 pilot metadata tooling.

This module is deliberately metadata-only. It can exercise the collection
pipeline with synthetic fixtures today, and can build a human collection
manifest only after the repository's participant-rights gate is genuinely
approved. It never stores image bytes, filesystem paths, names, signed
agreements or contact data in emitted artifacts.

Human release authority remains the validated boundary in
tools/validate_consent_protocol.py: compile_release_policy ->
collection_consent_context -> check_collection_manifest.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_consent_protocol as vcp  # noqa: E402

CONSENT_DIR = ROOT / "contracts" / "consent" / "v1"
COLLECTION_DIR = ROOT / "content" / "collection" / "v1"
MAX_CAPTURE_BYTES = 20 * 1024 * 1024

SOURCE_KEYS = frozenset({
    "synthetic", "release_purpose", "release_cutoff", "writers", "specimens", "captures", "claimed_counts",
})
WRITER_KEYS = frozenset({"writer_id", "adult_eligibility", "enrollment_id"})
SPECIMEN_KEYS = frozenset({
    "specimen_id", "writer_id", "task_id", "session_index", "collected_at", "declared_language",
    "declared_script", "declared_style", "paper", "instrument", "context_status",
})
CAPTURE_SOURCE_KEYS = frozenset({
    "capture_id", "specimen_id", "capture_index", "captured_at", "source_path", "repeat_of_capture_id",
})
COUNT_KEYS = frozenset({"writers", "specimens", "captures"})
FORBIDDEN_INPUT_KEYS = frozenset({
    "name", "full_name", "email", "phone", "telephone", "address", "birth_date", "dob", "diagnosis",
    "signed_agreement", "signature", "filename", "file_name",
})
ID_PREFIXES = {
    "writer": "wrt",
    "enrollment": "enr",
    "specimen": "spc",
    "capture": "cap",
    "annotation": "ann",
}
DEFAULT_ALLOCATION = {"development": 60, "validation": 20, "holdout": 20}
OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PilotToolError(ValueError):
    """Safe user-facing refusal from the local pilot tool."""


@dataclass(frozen=True)
class EligibleIds:
    synthetic: bool
    writer_ids: tuple[str, ...]
    specimen_ids: tuple[str, ...]
    capture_ids: tuple[str, ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def document_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: str | Path) -> Any:
    return vcp.load_json(Path(path))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def load_policy_documents() -> dict[str, Any]:
    return {
        "gate": load_json(CONSENT_DIR / "pilot_gate.json"),
        "purposes": load_json(CONSENT_DIR / "purposes.json"),
        "notices": load_json(CONSENT_DIR / "notices.json"),
        "sources": load_json(CONSENT_DIR / "source_rights.json"),
        "protocol": load_json(COLLECTION_DIR / "manifest.json"),
    }


def _purpose_map(registry: Mapping[str, Any]) -> dict[tuple[str, int], dict]:
    return {vcp.purpose_key(row): row for row in registry["purposes"]}


def human_readiness_issues(documents: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Return machine-readable reasons human collection must stay disabled.

    This is intentionally stricter than merely checking gate.status. It also
    verifies the current gate/protocol objects, the active pilot notice and the
    protocol's offered purposes. No override flag exists.
    """
    docs = copy.deepcopy(dict(documents or load_policy_documents()))
    gate = docs["gate"]
    protocol = docs["protocol"]
    notices = docs["notices"]
    registry = docs["purposes"]
    sources_doc = docs["sources"]
    purposes = _purpose_map(registry)
    sources = {row["source_id"]: row for row in sources_doc["sources"]}

    codes: set[str] = set()
    schema = vcp.SchemaSet()
    for value, spec in (
        (gate, "pilot-gate.schema.json"),
        (protocol, "collection-protocol.schema.json"),
        (registry, "purpose-registry.schema.json"),
        (notices, "notice-registry.schema.json"),
    ):
        codes.update(issue.code for issue in schema.validate(value, spec))

    if gate.get("status") != "APPROVED":
        codes.add("PILOT_GATE_NOT_APPROVED")
    if protocol.get("status") != "APPROVED":
        codes.add("PILOT_PROTOCOL_NOT_APPROVED")

    approval_when = (protocol.get("approval") or {}).get("decided_on")
    try:
        if not vcp.gate_approved_by(gate, approval_when):
            codes.add("PILOT_GATE_NOT_READY")
    except (KeyError, TypeError, ValueError):
        codes.add("PILOT_GATE_NOT_READY")

    try:
        codes.update(issue.code for issue in vcp.check_pilot_gate(gate, protocol, notices, purposes))
        codes.update(issue.code for issue in vcp.check_protocol(protocol, purposes, sources=sources))
    except (KeyError, TypeError, ValueError, OSError):
        codes.add("PILOT_POLICY_INVALID")

    pilot_notices = [
        row for row in notices.get("notices", [])
        if row.get("notice_id") == "notice.pilot-collection"
    ]
    if (len(pilot_notices) != 1 or pilot_notices[0].get("status") != "ACTIVE"
            or not pilot_notices[0].get("effective_from")):
        codes.add("PILOT_NOTICE_NOT_ACTIVE")

    for purpose_ref in protocol.get("consent_purposes", []):
        row = purposes.get(vcp.purpose_key(purpose_ref))
        if row is None or row.get("status") != "APPROVED":
            codes.add("PILOT_PURPOSE_NOT_APPROVED")

    return tuple(sorted(codes))


def require_mode(mode: str, *, synthetic: bool, documents: Mapping[str, Any] | None = None) -> None:
    if mode not in {"synthetic", "human"}:
        raise PilotToolError("mode must be synthetic or human")
    if mode == "synthetic":
        if synthetic is not True:
            raise PilotToolError("synthetic mode refuses a non-synthetic manifest")
        return
    if synthetic is not False:
        raise PilotToolError("human mode refuses synthetic data")
    issues = human_readiness_issues(documents)
    if issues:
        raise PilotToolError("human pilot is disabled: " + ",".join(issues))


def new_opaque_id(kind: str, *, synthetic: bool = False, seed: str | None = None) -> str:
    """Generate an opaque ID without accepting any participant attributes."""
    prefix = ID_PREFIXES.get(kind)
    if prefix is None:
        raise PilotToolError(f"unknown id kind: {kind}")
    if seed is not None and not synthetic:
        raise PilotToolError("deterministic IDs are synthetic-fixture-only")
    token = hashlib.sha256(f"{kind}\0{seed}".encode()).hexdigest()[:24] if seed is not None else secrets.token_hex(12)
    return f"{prefix}_{token}"


def _assert_exact_keys(value: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown:
        raise PilotToolError(f"{where}: unexpected fields {sorted(unknown)}")
    if missing:
        raise PilotToolError(f"{where}: missing fields {sorted(missing)}")


def _reject_forbidden_keys(value: Any, where: str = "source") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_INPUT_KEYS:
                raise PilotToolError(f"{where}: forbidden personal/path field {key}")
            _reject_forbidden_keys(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{where}[{index}]")


def _capture_sha256(root: Path, relative: str) -> str:
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise PilotToolError("capture source_path must stay beneath capture_root")
    base = root.resolve(strict=True)
    current = base
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise PilotToolError("capture source_path may not traverse symlinks")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(base)
    except (OSError, ValueError):
        raise PilotToolError("capture source_path is missing or escapes capture_root") from None
    st = resolved.stat()
    if not stat.S_ISREG(st.st_mode):
        raise PilotToolError("capture source_path must be a regular file")
    if st.st_size > MAX_CAPTURE_BYTES:
        raise PilotToolError("capture source exceeds the product 20 MiB intake limit")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_schema_issues(manifest: dict) -> tuple[str, ...]:
    tree = vcp.input_tree_issues(manifest, "manifest")
    issues = tree or vcp.SchemaSet().validate(manifest, "collection-manifest.schema.json", "manifest")
    return tuple(sorted({issue.code for issue in issues}))


def validate_synthetic_manifest(manifest: dict, consent_log: dict) -> EligibleIds:
    """Run the repository's existing synthetic-only collection semantics."""
    require_mode("synthetic", synthetic=manifest.get("synthetic") is True)
    registry = load_json(CONSENT_DIR / "purposes.json")
    protocol = load_json(COLLECTION_DIR / "manifest.json")
    consent = vcp.collection_consent_context(
        registry, manifest, consent_log, fixture_mode=True,
    )
    issues, summary = vcp.check_fixture_collection_manifest(
        manifest, protocol, consent, publish_at=vcp.parse_timestamp(manifest["release_cutoff"]),
    )
    if issues:
        codes = ",".join(sorted({issue.code for issue in issues}))
        raise PilotToolError(f"synthetic collection manifest rejected: {codes}")
    return EligibleIds(
        synthetic=True,
        writer_ids=tuple(summary.writer_ids),
        specimen_ids=tuple(summary.specimen_ids),
        capture_ids=tuple(summary.capture_ids),
    )


def build_manifest(source: Mapping[str, Any], *, capture_root: str | Path, mode: str,
                   consent_log: dict | None = None,
                   documents: Mapping[str, Any] | None = None) -> tuple[dict, EligibleIds | None]:
    """Compile private/source metadata into the canonical collection-manifest/v1 shape."""
    if not isinstance(source, Mapping):
        raise PilotToolError("source metadata must be an object")
    _reject_forbidden_keys(source)
    _assert_exact_keys(source, SOURCE_KEYS, "source")
    synthetic = source["synthetic"]
    if type(synthetic) is not bool:
        raise PilotToolError("source.synthetic must be boolean")
    require_mode(mode, synthetic=synthetic, documents=documents)

    writers = []
    for index, row in enumerate(source["writers"]):
        if not isinstance(row, Mapping):
            raise PilotToolError(f"writers[{index}] must be an object")
        _assert_exact_keys(row, WRITER_KEYS, f"writers[{index}]")
        writers.append({key: row[key] for key in WRITER_KEYS})

    specimens = []
    for index, row in enumerate(source["specimens"]):
        if not isinstance(row, Mapping):
            raise PilotToolError(f"specimens[{index}] must be an object")
        _assert_exact_keys(row, SPECIMEN_KEYS, f"specimens[{index}]")
        specimens.append({key: row[key] for key in SPECIMEN_KEYS})

    captures = []
    capture_root_path = Path(capture_root)
    for index, row in enumerate(source["captures"]):
        if not isinstance(row, Mapping):
            raise PilotToolError(f"captures[{index}] must be an object")
        _assert_exact_keys(row, CAPTURE_SOURCE_KEYS, f"captures[{index}]")
        capture = {key: row[key] for key in CAPTURE_SOURCE_KEYS if key != "source_path"}
        capture["content_sha256"] = _capture_sha256(capture_root_path, str(row["source_path"]))
        captures.append(capture)

    counts = source["claimed_counts"]
    if not isinstance(counts, Mapping):
        raise PilotToolError("claimed_counts must be an object")
    _assert_exact_keys(counts, COUNT_KEYS, "claimed_counts")

    protocol = load_json(COLLECTION_DIR / "manifest.json")
    manifest = {
        "contract_version": "collection-manifest/v1",
        "protocol": {
            "protocol_id": protocol["protocol_id"],
            "version": protocol["version"],
        },
        "synthetic": synthetic,
        "release_purpose": copy.deepcopy(source["release_purpose"]),
        "release_cutoff": source["release_cutoff"],
        "writers": writers,
        "specimens": specimens,
        "captures": captures,
        "claimed_counts": {key: counts[key] for key in COUNT_KEYS},
    }
    schema_issues = _manifest_schema_issues(manifest)
    if schema_issues:
        raise PilotToolError("collection manifest schema rejected: " + ",".join(schema_issues))

    if mode == "synthetic":
        if consent_log is None:
            raise PilotToolError("synthetic mode requires a consent_log for semantic validation")
        return manifest, validate_synthetic_manifest(manifest, consent_log)
    # This only builds the canonical metadata envelope. It is not release
    # authorization: the human release boundary still requires compiled policy,
    # protected ledger context, publication evidence and check_collection_manifest.
    return manifest, None


def _allocation_quotas(total: int, allocation: Mapping[str, int]) -> dict[str, int]:
    if not allocation or any(type(weight) is not int or weight <= 0 for weight in allocation.values()):
        raise PilotToolError("split allocation weights must be positive integers")
    weight_sum = sum(allocation.values())
    names = sorted(allocation)
    quotas = {name: 0 for name in names}
    remaining = total

    # If the pilot is large enough, give every configured split at least one
    # writer. This is an engineering partition rule, not evidence of adequacy.
    if total >= len(names):
        for name in names:
            quotas[name] = 1
        remaining -= len(names)
    if remaining <= 0:
        return quotas

    raw = {name: remaining * allocation[name] / weight_sum for name in names}
    floors = {name: int(raw[name]) for name in names}
    for name, count in floors.items():
        quotas[name] += count
    leftover = remaining - sum(floors.values())
    ranked = sorted(names, key=lambda name: (-(raw[name] - floors[name]), name))
    for name in ranked[:leftover]:
        quotas[name] += 1
    return quotas


def plan_writer_disjoint(manifest: dict, eligible: EligibleIds, *,
                         allocation: Mapping[str, int] = DEFAULT_ALLOCATION,
                         salt: str = "pilot-split-v1") -> dict:
    if manifest.get("synthetic") is not eligible.synthetic:
        raise PilotToolError("eligibility synthetic flag does not match manifest")
    writer_rows = {row["writer_id"]: row for row in manifest["writers"]}
    specimen_rows = {row["specimen_id"]: row for row in manifest["specimens"]}
    capture_rows = {row["capture_id"]: row for row in manifest["captures"]}
    writer_ids = sorted(set(eligible.writer_ids))
    if len(writer_ids) != len(eligible.writer_ids) or any(writer_id not in writer_rows for writer_id in writer_ids):
        raise PilotToolError("eligible writer IDs are duplicate or outside the manifest")

    ranked = sorted(
        writer_ids,
        key=lambda writer_id: (
            hashlib.sha256(f"{salt}\0{writer_id}".encode()).hexdigest(),
            writer_id,
        ),
    )
    quotas = _allocation_quotas(len(ranked), allocation)
    assignment: dict[str, str] = {}
    cursor = 0
    for split in sorted(quotas):
        for writer_id in ranked[cursor:cursor + quotas[split]]:
            assignment[writer_id] = split
        cursor += quotas[split]
    if set(assignment) != set(writer_ids):
        raise PilotToolError("split allocation did not assign every eligible writer")

    specimen_ids = set(eligible.specimen_ids)
    capture_ids = set(eligible.capture_ids)
    specimens = []
    for specimen_id in sorted(specimen_ids):
        row = specimen_rows.get(specimen_id)
        if row is None or row["writer_id"] not in assignment:
            raise PilotToolError("eligible specimen is outside the eligible writer set")
        specimens.append({
            "specimen_id": specimen_id,
            "writer_id": row["writer_id"],
            "split": assignment[row["writer_id"]],
        })

    specimen_split = {row["specimen_id"]: row["split"] for row in specimens}
    specimen_writer = {row["specimen_id"]: row["writer_id"] for row in specimens}
    captures = []
    for capture_id in sorted(capture_ids):
        row = capture_rows.get(capture_id)
        if row is None or row["specimen_id"] not in specimen_split:
            raise PilotToolError("eligible capture is outside the eligible specimen set")
        captures.append({
            "capture_id": capture_id,
            "specimen_id": row["specimen_id"],
            "writer_id": specimen_writer[row["specimen_id"]],
            "split": specimen_split[row["specimen_id"]],
        })

    plan = {
        "contract_version": "pilot-split-plan/v1",
        "synthetic": eligible.synthetic,
        "manifest_sha256": document_sha256(manifest),
        "method": "writer_disjoint_sha256_rank_v1",
        "salt_id": salt,
        "allocation_weights": dict(sorted(allocation.items())),
        "writers": [
            {"writer_id": writer_id, "split": assignment[writer_id]}
            for writer_id in sorted(assignment)
        ],
        "specimens": specimens,
        "captures": captures,
    }
    issues = validate_split_plan(plan, manifest, eligible)
    if issues:
        raise PilotToolError("invalid split plan: " + ",".join(issues))
    return plan


def validate_split_plan(plan: Mapping[str, Any], manifest: dict, eligible: EligibleIds) -> tuple[str, ...]:
    issues: set[str] = set()
    if plan.get("contract_version") != "pilot-split-plan/v1":
        issues.add("SPLIT_CONTRACT")
    if plan.get("manifest_sha256") != document_sha256(manifest):
        issues.add("SPLIT_MANIFEST_MISMATCH")
    if plan.get("synthetic") is not eligible.synthetic:
        issues.add("SPLIT_SYNTHETIC_MISMATCH")

    writers = plan.get("writers")
    specimens = plan.get("specimens")
    captures = plan.get("captures")
    if not all(isinstance(rows, list) for rows in (writers, specimens, captures)):
        return tuple(sorted(issues | {"SPLIT_SHAPE"}))

    writer_map: dict[str, str] = {}
    for row in writers:
        if not isinstance(row, Mapping) or not isinstance(row.get("writer_id"), str) or not isinstance(row.get("split"), str):
            issues.add("SPLIT_SHAPE")
            continue
        if row["writer_id"] in writer_map:
            issues.add("SPLIT_DUPLICATE_WRITER")
        writer_map[row["writer_id"]] = row["split"]
    if set(writer_map) != set(eligible.writer_ids):
        issues.add("SPLIT_WRITER_SET")

    specimen_manifest = {row["specimen_id"]: row for row in manifest["specimens"]}
    seen_specimens: set[str] = set()
    for row in specimens:
        if not isinstance(row, Mapping):
            issues.add("SPLIT_SHAPE")
            continue
        specimen_id = row.get("specimen_id")
        if specimen_id in seen_specimens:
            issues.add("SPLIT_DUPLICATE_SPECIMEN")
        seen_specimens.add(specimen_id)
        source = specimen_manifest.get(specimen_id)
        if source is None or row.get("writer_id") != source["writer_id"]:
            issues.add("SPECIMEN_WRITER_MISMATCH")
        elif row.get("split") != writer_map.get(source["writer_id"]):
            issues.add("SPECIMEN_SPLIT_LEAKAGE")
    if seen_specimens != set(eligible.specimen_ids):
        issues.add("SPLIT_SPECIMEN_SET")

    capture_manifest = {row["capture_id"]: row for row in manifest["captures"]}
    specimen_plan = {
        row.get("specimen_id"): row
        for row in specimens if isinstance(row, Mapping) and isinstance(row.get("specimen_id"), str)
    }
    seen_captures: set[str] = set()
    for row in captures:
        if not isinstance(row, Mapping):
            issues.add("SPLIT_SHAPE")
            continue
        capture_id = row.get("capture_id")
        if capture_id in seen_captures:
            issues.add("SPLIT_DUPLICATE_CAPTURE")
        seen_captures.add(capture_id)
        source = capture_manifest.get(capture_id)
        parent = specimen_plan.get(source["specimen_id"]) if source is not None else None
        if source is None or parent is None:
            issues.add("CAPTURE_SPECIMEN_MISMATCH")
        elif (row.get("specimen_id") != source["specimen_id"]
              or row.get("writer_id") != parent.get("writer_id")
              or row.get("split") != parent.get("split")):
            issues.add("CAPTURE_SPLIT_LEAKAGE")
    if seen_captures != set(eligible.capture_ids):
        issues.add("SPLIT_CAPTURE_SET")

    return tuple(sorted(issues))


def annotation_worklist(manifest: dict, split_plan: dict, eligible: EligibleIds) -> dict:
    issues = validate_split_plan(split_plan, manifest, eligible)
    if issues:
        raise PilotToolError("cannot build annotation worklist: " + ",".join(issues))
    captures = {row["capture_id"]: row for row in split_plan["captures"]}
    items = []
    for capture_id in sorted(eligible.capture_ids):
        row = captures[capture_id]
        ann_id = "ann_" + hashlib.sha256(f"annotation-v1\0{capture_id}".encode()).hexdigest()[:24]
        items.append({
            "annotation_item_id": ann_id,
            "writer_id": row["writer_id"],
            "specimen_id": row["specimen_id"],
            "capture_id": capture_id,
            "split": row["split"],
            "asset_ref": ("synthetic:" if eligible.synthetic else "protected:") + capture_id,
            "status": "PENDING",
        })
    return {
        "contract_version": "pilot-annotation-worklist/v1",
        "synthetic": eligible.synthetic,
        "manifest_sha256": document_sha256(manifest),
        "split_plan_sha256": document_sha256(split_plan),
        "items": items,
    }


def recruitment_summary(manifest: dict, eligible: EligibleIds) -> dict:
    writer_ids = set(eligible.writer_ids)
    specimen_ids = set(eligible.specimen_ids)
    specimens = [row for row in manifest["specimens"] if row["specimen_id"] in specimen_ids]
    languages_by_writer: dict[str, set[str]] = defaultdict(set)
    for row in specimens:
        languages_by_writer[row["writer_id"]].add(row["declared_language"])

    writer_languages = Counter()
    for writer_id in sorted(writer_ids):
        languages = languages_by_writer.get(writer_id, set())
        label = next(iter(languages)) if len(languages) == 1 else ("NONE" if not languages else "MULTIPLE")
        writer_languages[label] += 1

    session_2 = {row["writer_id"] for row in specimens if row["session_index"] >= 2}
    return {
        "contract_version": "pilot-recruitment-summary/v1",
        "synthetic": eligible.synthetic,
        "manifest_sha256": document_sha256(manifest),
        "writers": len(writer_ids),
        "specimens": len(specimen_ids),
        "captures": len(eligible.capture_ids),
        "writer_languages": dict(sorted(writer_languages.items())),
        "specimen_styles": dict(sorted(Counter(row["declared_style"] for row in specimens).items())),
        "specimen_paper": dict(sorted(Counter(row["paper"] for row in specimens).items())),
        "specimen_instruments": dict(sorted(Counter(row["instrument"] for row in specimens).items())),
        "session_2_writers": len(session_2),
        "session_2_return_rate": (len(session_2) / len(writer_ids)) if writer_ids else None,
        "limitations": [
            "Descriptive collection composition only; not population representativeness.",
            "The protocol does not collect gender, ethnicity, diagnosis or socioeconomic status.",
        ],
    }


def _validated_synthetic(manifest_path: str, consent_path: str) -> tuple[dict, EligibleIds]:
    manifest = load_json(manifest_path)
    consent = load_json(consent_path)
    return manifest, validate_synthetic_manifest(manifest, consent)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="T11 gated pilot metadata tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gate-status", help="Show whether human pilot tooling is enabled")

    build = sub.add_parser("build-manifest")
    build.add_argument("--mode", choices=("synthetic", "human"), required=True)
    build.add_argument("--input", required=True)
    build.add_argument("--capture-root", required=True)
    build.add_argument("--consent-log")
    build.add_argument("--output", required=True)

    for command in ("split-synthetic", "annotation-synthetic", "summary-synthetic"):
        item = sub.add_parser(command)
        item.add_argument("--manifest", required=True)
        item.add_argument("--consent-log", required=True)
        item.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "gate-status":
            issues = human_readiness_issues()
            print(canonical_json({"human_mode_ready": not issues, "issues": list(issues)}))
            return 0 if not issues else 3

        if args.command == "build-manifest":
            source = load_json(args.input)
            consent = load_json(args.consent_log) if args.consent_log else None
            manifest, _eligible = build_manifest(
                source, capture_root=args.capture_root, mode=args.mode, consent_log=consent,
            )
            write_json(args.output, manifest)
            return 0

        manifest, eligible = _validated_synthetic(args.manifest, args.consent_log)
        if args.command == "split-synthetic":
            write_json(args.output, plan_writer_disjoint(manifest, eligible))
        elif args.command == "annotation-synthetic":
            split = plan_writer_disjoint(manifest, eligible)
            write_json(args.output, annotation_worklist(manifest, split, eligible))
        elif args.command == "summary-synthetic":
            write_json(args.output, recruitment_summary(manifest, eligible))
        return 0
    except (PilotToolError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
