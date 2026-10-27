#!/usr/bin/env python3
"""Compile the recovered inactive R1 report-reading sources without altering v1."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from generate_presentation_content import SOURCE as V1_SOURCE, validate_v2

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "presentation": ROOT / "content/presentation/v2/presentation.json",
    "chapters": ROOT / "content/presentation/v2/chapters.json",
    "relations": ROOT / "content/premium/reading-v2/relations.json",
    "manifest": ROOT / "content/premium/reading-v2/manifest.json",
}
T26_SOURCE = ROOT / "schema/premium_interpretation_database_v1.json"
SERVER_OUTPUT = ROOT / "src/princess_app/domain/content/_reading_v2.json"
CLIENT_OUTPUT = ROOT / "packages/report-core/src/reading.generated.ts"
CHAPTERS = ("slant", "baseline", "spacing", "size", "layout", "ink")
LOCALES = frozenset(("en", "sv"))


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate reading source key")
        result[key] = value
    return result


def _read(path: Path) -> dict[str, Any]:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("reading source may not traverse symlinks")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("reading source must be a regular file")
    if path.stat().st_size > 262144:
        raise ValueError("reading source exceeds byte limit")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite reading source")),
    )
    if not isinstance(value, dict):
        raise ValueError("reading source root must be an object")
    return value


def _localized(value: Any, *, limit: int = 500) -> None:
    if not isinstance(value, dict) or set(value) != LOCALES:
        raise ValueError("reading source must have exactly en and sv")
    if any(not isinstance(v, str) or not v.strip() or len(v) > limit for v in value.values()):
        raise ValueError("invalid bounded reading translation")


def validate_reading_content(
    presentation: dict[str, Any], chapters: dict[str, Any],
    relations: dict[str, Any], manifest: dict[str, Any], baseline: dict[str, Any],
) -> None:
    """Validate structural reachability; this is not editorial or release approval."""
    validate_v2(presentation, baseline)
    if chapters.get("version") != "chapter-copy/1" or chapters.get("runtime_activation") is not False:
        raise ValueError("chapter registry must remain inactive chapter-copy/1")
    if chapters.get("review_status") != "DRAFT_FOR_REVIEW":
        raise ValueError("chapter source cannot assert reviewed publication")
    rows = chapters.get("chapters")
    if not isinstance(rows, list) or len(rows) != 6:
        raise ValueError("exactly six authored chapters required")
    for family, row in zip(CHAPTERS, rows):
        if not isinstance(row, dict) or row.get("family") != family or row.get("section_id") != f"section.{family}":
            raise ValueError("chapter order/identity mismatch")
        if row.get("neutral_content_id") != f"content.chapter.v2.{family}.neutral":
            raise ValueError("chapter neutral copy identity mismatch")
        if row.get("unavailable_content_id") != f"content.chapter.v2.{family}.unavailable":
            raise ValueError("chapter fallback identity mismatch")
        if row.get("measurement_access") != "FREE" or row.get("evidence_mode") != "SAVED_ONLY":
            raise ValueError("chapters may not invent paid or unsaved evidence")
        if row.get("max_summary_characters") != 280:
            raise ValueError("chapter summary length policy drift")
        for key in ("title", "neutral", "unavailable"):
            _localized(row.get(key), limit=280)
    states = chapters.get("states")
    if not isinstance(states, dict) or set(states) != {"NEUTRAL", "PARTIAL", "UNQUALIFIED"}:
        raise ValueError("missing neutral/partial/unqualified states")
    for state in states.values():
        _localized(state, limit=280)

    if relations.get("version") != "combination-policy/1" or relations.get("runtime_activation") is not False:
        raise ValueError("relationship source must remain inactive")
    if relations.get("review_status") != "DRAFT_FOR_REVIEW":
        raise ValueError("relationship source cannot assert reviewed publication")
    rules = relations.get("rules")
    if not isinstance(rules, list) or len(rules) != 6:
        raise ValueError("exactly six neutral relationship rules required")
    candidate_family = {row["candidate_id"]: row["family"] for row in presentation["candidates"]}
    ids: set[str] = set()
    copy_ids: set[str] = set()
    for row in rules:
        if not isinstance(row, dict) or row.get("type") not in {"CONTRAST", "COOCCURRENCE"}:
            raise ValueError("unknown relation kind")
        rid, cid = row.get("relation_id"), row.get("claim_key")
        if (not isinstance(rid, str) or not rid.startswith("relation.")
                or rid in ids or not isinstance(cid, str)
                or not cid.startswith("content.relation.v1.") or cid in copy_ids):
            raise ValueError("invalid or duplicate relationship identity")
        ids.add(rid)
        copy_ids.add(cid)
        required = row.get("required_descriptor_ids")
        if (not isinstance(required, list) or len(required) != 2
                or len(set(required)) != 2
                or any(item not in candidate_family for item in required)
                or len({candidate_family[item] for item in required}) != 2):
            raise ValueError("relationship needs two known distinct families")
        if row.get("min_families") != 2 or row.get("causal_claim") is not False or row.get("population_claim") is not False:
            raise ValueError("relationship must remain noncausal and non-population")
        _localized(row.get("copy"), limit=280)

    if manifest.get("version") != "premium-reading/2" or manifest.get("runtime_activation") is not False:
        raise ValueError("Premium source is not authorized for activation")
    if manifest.get("review_status") != "DRAFT_FOR_REVIEW" or manifest.get("does_not_activate_base_pack") is not True:
        raise ValueError("unreviewed Premium authority")
    if (manifest.get("base_selector_pack") != "PREMIUM_INDIVIDUAL_GRAPHIC_V1"
            or manifest.get("selector_definition_source") != "FROZEN_T26_V1_DEFINITIONS_ONLY"
            or manifest.get("traditional_runtime_eligible_associations") != 0):
        raise ValueError("Premium would expand frozen selector authority")
    selected = manifest.get("selector_question_ids")
    visual = manifest.get("visual_question_ids")
    if (not isinstance(selected, list) or len(selected) != 14 or len(set(selected)) != 14
            or not isinstance(visual, list) or len(visual) != 7 or len(set(visual)) != 7
            or not set(visual).issubset(selected)):
        raise ValueError("question allowlist drift")
    if any(not isinstance(item, str) or item.startswith(("Q_TRAD", "Q_SIG", "Q_HIERARCHY")) for item in selected):
        raise ValueError("traditional/private selectors are not supported")
    if tuple(manifest.get(k) for k in (
        "max_descriptor_candidates", "max_combination_candidates", "max_authorized_regions",
        "max_attempts", "max_model_output_tokens",
    )) != (12, 8, 32, 2, 4000):
        raise ValueError("Premium limits drift")
    if manifest.get("semantic_release_review_required") is not True:
        raise ValueError("Premium cannot waive independent review")
    if manifest.get("base_t26_sha256") != hashlib.sha256(T26_SOURCE.read_bytes()).hexdigest():
        raise ValueError("Premium selector source digest drift")
    # Freeze the proposed allowlist to actual published T26 definitions. A
    # valid-looking Q_* name alone must not create a new model question.
    frozen = json.loads(T26_SOURCE.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    packs = [row for row in frozen["question_packs"]
             if row["pack_id"] == manifest["base_selector_pack"]]
    defined = {row["question_id"] for row in frozen["question_definitions"]}
    if (len(packs) != 1 or
            not set(selected) <= set(packs[0]["question_ids"]) & defined):
        raise ValueError("Premium selector allowlist contains a foreign T26 question")


def compile_registry(sources: dict[str, dict[str, Any]], digests: dict[str, str]) -> dict[str, Any]:
    # The source pins are evidence, not optional display metadata. A missing
    # or stale digest must never yield a seemingly complete read-only registry.
    if set(digests) != set(INPUTS) or any(
        digests[name] != hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in INPUTS.items()
    ):
        raise ValueError("reading-v2 source SHA-256 pins are absent or drifted")
    chapters = sources["chapters"]
    relations = sources["relations"]
    return {
        "version": "reading-v2-registry/1",
        "status": "DRAFT_FOR_REVIEW",
        "runtime_activation": False,
        "presentation_version": "presentation/2",
        "chapter_policy_version": chapters["version"],
        "policy_version": relations["version"],
        "reading_pack_version": sources["manifest"]["version"],
        "source_sha256": digests,
        "chapters": [
            {key: row[key] for key in (
                "section_id", "family", "title", "neutral_content_id", "neutral",
                "unavailable_content_id", "unavailable",
            )}
            for row in chapters["chapters"]
        ],
        "states": chapters["states"],
        "relations": [
            {
                "relation_id": row["relation_id"],
                "kind": row["type"],
                "content_id": row["claim_key"],
                "required_descriptors": row["required_descriptor_ids"],
                "copy": row["copy"],
            }
            for row in relations["rules"]
        ],
    }


def render_registry(registry: dict[str, Any]) -> str:
    return json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def render_typescript(registry: dict[str, Any], presentation: dict[str, Any]) -> str:
    """Expose exact authored EN/SV copy and IDs to readers, not selector authority."""
    copy_by_id = dict(presentation["content"])

    def add(content_id: str, localized: dict[str, str]) -> None:
        if content_id in copy_by_id:
            raise ValueError(f"duplicate authored client content {content_id}")
        copy_by_id[content_id] = localized

    for row in registry["chapters"]:
        add(row["neutral_content_id"], row["neutral"])
        add(row["unavailable_content_id"], row["unavailable"])
    for state, localized in registry["states"].items():
        add(f"content.reading.v2.state.{state.lower()}", localized)
    for row in registry["relations"]:
        add(row["content_id"], row["copy"])

    # 55 approved presentation copy IDs + 12 chapters + 3 states + 6 relations.
    # This is a source-closure check, not a rule for choosing user-facing text.
    if len(copy_by_id) != 76 or len(presentation["feature_labels"]) != 64:
        raise ValueError("unexpected approved Free client content closure")

    content = {
        "version": registry["version"],
        "presentation_version": registry["presentation_version"],
        "feature_labels": presentation["feature_labels"],
        "content": copy_by_id,
        "chapters": [
            {key: row[key] for key in (
                "section_id", "title", "neutral_content_id", "unavailable_content_id",
                "neutral", "unavailable",
            )}
            for row in registry["chapters"]
        ],
        "states": registry["states"],
        "relations": [
            {key: row[key] for key in ("relation_id", "content_id", "copy")}
            for row in registry["relations"]
        ],
    }
    return (
        "// GENERATED by tools/generate_report_reading_content.py; do not edit.\n"
        "export const READING_CONTENT = "
        + json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + " as const;\n"
    )


def build() -> dict[Path, str]:
    sources = {name: _read(path) for name, path in INPUTS.items()}
    baseline = _read(V1_SOURCE)
    validate_reading_content(
        sources["presentation"], sources["chapters"],
        sources["relations"], sources["manifest"], baseline,
    )
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest()
               for name, path in INPUTS.items()}
    registry = compile_registry(sources, digests)
    return {
        SERVER_OUTPUT: render_registry(registry),
        CLIENT_OUTPUT: render_typescript(registry, sources["presentation"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build()
    stale = [path for path, body in outputs.items()
             if not path.is_file() or path.read_text(encoding="utf-8") != body]
    if args.check:
        if stale:
            print("stale report-reading content: " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
            return 1
        print("PASS inactive reading-v2 content registry: six chapters, six relations")
        return 0
    for path, body in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    print("wrote inactive reading-v2 generated registries (NOT APPROVED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
