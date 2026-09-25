#!/usr/bin/env python3
"""Check the frozen research import; optionally reconstruct the original artifacts.

Offline, standard-library only. This is not a production database compiler.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=reject_constant)


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes research root: {relative}")
    return path


def catalogue(blueprint: dict, sources: list[dict], preamble: str) -> bytes:
    """Reproduce the original readable catalogue without duplicating its records."""
    lines = [preamble]
    sets = {item["value_set_id"]: item for item in blueprint["selector_value_sets"]}
    for domain in blueprint["domains"]:
        lines.append(f"## {domain['label']}\n\n{domain['design_note']}\n\n")
        for q in blueprint["question_definitions"]:
            if q["domain_id"] != domain["domain_id"]:
                continue
            lines.append(f"### {q['question_id']}\n\n{q['question_text_en']}\n\n")
            lines.append(f"**Answer owner:** {q['answer_owner']}. **Scope:** {q['scope']}. "
                         f"**Cardinality:** {q['cardinality']}.\n")
            if q["value_set_id"]:
                choices = "; ".join(f"`{v['value_id']}` — {v['label_en']}"
                                    for v in sets[q["value_set_id"]]["values"])
                lines.append(f"**Choices:** {choices}.\n")
            else:
                lines.append(f"**Choices:** eligible current-report IDs from `{q['candidate_kind']}`; "
                             "no invented candidates.\n")
            if q["related_canonical_feature_ids"]:
                refs = ", ".join(f"`{x}`" for x in q["related_canonical_feature_ids"])
                lines.append(f"**Related measurements (not automatic equivalence):** {refs}.\n")
            if q["required_inputs"]:
                lines.append(f"**Requires:** {', '.join(q['required_inputs'])}.\n")
            if q["source_refs"]:
                refs = ", ".join(f"[{r['source_id']}](#{r['source_id'].lower()})" for r in q["source_refs"])
                lines.append(f"**Domain/term sources:** {refs}. Wording/rubric is authored for this app.\n")
            else:
                lines.append("**Origin:** application extension; no claim of historical graphological meaning.\n")
            if q["note"]:
                lines.append(f"**Guardrail:** {q['note']}\n")
            lines.append("\n")
    lines.append("## Bounded text fields\n\n")
    for field in blueprint["soft_field_definitions"]:
        lines.append(f"### {field['soft_field_id']}\n\n{field['purpose']}\n")
        lines.append(f"Proposed limit: {field['max_characters']} characters / {field['max_sentences']} "
                     f"sentences. No new numbers. Requires: {', '.join(field['required_support'])}.\n\n")
    lines.append("## Sources\n\n")
    for s in sources:
        lines.append(f"### {s['source_id']}\n\n[{s['title']}]({s['url']})\n")
        lines.append(f"Scope: {s['supports']}\nAccess: {s['access_depth']}.\n")
        lines.append(f"Limit: {s['does_not_establish']}\n\n")
    return "".join(lines).encode("utf-8")


def reconstruct(root: Path, manifest: dict) -> tuple[dict, dict[str, bytes]]:
    plan = manifest["reassembly"]
    metadata = load(safe_path(root, plan["metadata_file"]))
    values = load(safe_path(root, plan["value_sets_file"]))
    questions = []
    for part in plan["question_parts"]:
        items = load(safe_path(root, part["path"]))
        if [q["question_id"] for q in items] != part["question_ids"]:
            raise ValueError(f"Question order differs: {part['path']}")
        if any(q["domain_id"] != part["domain_id"] for q in items):
            raise ValueError(f"Wrong domain in {part['path']}")
        questions.extend(items)
    if set(metadata) != set(plan["top_level_key_order"]) - {"selector_value_sets", "question_definitions"}:
        raise ValueError("Unexpected/missing blueprint metadata keys")
    contents = dict(metadata, selector_value_sets=values, question_definitions=questions)
    blueprint = {key: contents[key] for key in plan["top_level_key_order"]}
    originals = {}
    for original, mapped in manifest["original_file_mapping"].items():
        if original in {"graphology_question_selector_blueprint.json", "question_catalogue.md"}:
            continue
        originals[original] = safe_path(root, mapped).read_bytes()
    originals["graphology_question_selector_blueprint.json"] = encoded(blueprint)
    sources = load(root / "sources.json")
    preamble = safe_path(root, plan["catalogue_preamble_file"]).read_text(encoding="utf-8")
    originals["question_catalogue.md"] = catalogue(blueprint, sources, preamble)
    return blueprint, originals


def validate(root: Path, feature_schema: Path) -> tuple[dict, dict[str, bytes]]:
    checks = []

    def check(name: str, ok: bool) -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL"})

    manifest = load(root / "provenance/import_manifest.json")
    for entry in manifest["files"]:
        data = safe_path(root, entry["path"]).read_bytes()
        check(f"Integrity: {entry['path']}", len(data) == entry["bytes"] and sha256(data) == entry["sha256"])
    b, originals = reconstruct(root, manifest)
    for name, digest in load(root / "provenance/original_SHA256SUMS.json").items():
        check(f"Original artifact SHA-256: {name}", sha256(originals[name]) == digest)
    check("No production scaffold replacement", b["replaces_production_scaffold"] is False)
    check("Research-only snapshot", b["status"] == "RESEARCH_DRAFT_NOT_PRODUCTION_POPULATION")
    sources = load(root / "sources.json")
    questions = b["question_definitions"]
    sets = b["selector_value_sets"]
    packs = b["question_packs"]
    source_ids = {x["source_id"] for x in sources}
    domain_ids = {x["domain_id"] for x in b["domains"]}
    qids = {q["question_id"] for q in questions}
    sids = {s["value_set_id"] for s in sets}
    feature_bytes = feature_schema.read_bytes()
    feature_ids = {f["id"] for f in load(feature_schema)["features"]}
    check("Canonical feature schema matches original validation baseline",
          sha256(feature_bytes) == load(root / "provenance/original_validation_report.json")["source_schema_sha256"])
    check("Source IDs unique", len(source_ids) == len(sources))
    check("Question IDs unique", len(qids) == len(questions))
    check("Selector IDs unique", len({q["selector_id"] for q in questions}) == len(questions))
    check("Value set IDs unique", len(sids) == len(sets))
    check("Canonical feature references resolve", all(set(q["related_canonical_feature_ids"]) <= feature_ids for q in questions))
    check("Question source references resolve", all({r["source_id"] for r in q["source_refs"]} <= source_ids for q in questions))
    check("Question domains resolve", all(q["domain_id"] in domain_ids for q in questions))
    check("One answer domain per question", all(bool(q["value_set_id"]) != bool(q["candidate_kind"]) for q in questions))
    check("Fixed value sets resolve", all(not q["value_set_id"] or q["value_set_id"] in sids for q in questions))
    check("Dynamic candidate kinds resolve", all(not q["candidate_kind"] or q["candidate_kind"] in b["candidate_kinds"] for q in questions))
    check("Value IDs unique per set", all(len({v["value_id"] for v in s["values"]}) == len(s["values"]) for s in sets))
    check("No orphan value sets", {q["value_set_id"] for q in questions if q["value_set_id"]} == sids)
    check("All questions draft", all(q["status"] == "DRAFT_NOT_ACTIVATED" for q in questions))
    check("All value entries draft", all(v["status"] == "DRAFT" for s in sets for v in s["values"]))
    examples = [a for a in b["source_assertions"] if a["claim_kind"] == "HISTORICAL_INTERPRETIVE_ASSOCIATION"]
    check("Historical examples research-only", all(a["runtime_role"] == "RESEARCH_ONLY_DO_NOT_EXECUTE" for a in examples))
    non_model = {"USER_OR_REVIEWER", "DETERMINISTIC", "RULE_ENGINE"}
    check("Non-model questions read-only", all(q["model_call_role"] == "READ_ONLY_CONTEXT_OR_PRECOMPUTED" for q in questions if q["answer_owner"] in non_model))
    check("Soft fields forbid new numbers", all(f["allow_new_numbers"] is False for f in b["soft_field_definitions"]))
    check("Pack references resolve", all(set(p["questions"]) <= qids for p in packs))
    check("No unreferenced question", set().union(*(set(p["questions"]) for p in packs)) == qids)
    check("All source IDs in metadata resolve", all(set(x["source_ids"]) <= source_ids for x in b["schools"] + b["domains"] + sets))
    check("Soft-field source references resolve", all(set(x["source_refs"]) <= source_ids for x in b["soft_field_definitions"]))
    check("Assertion sources resolve", all(x["source_id"] in source_ids for x in b["source_assertions"]))
    check("No forbidden control characters", all(not any(ord(c) < 32 and c not in "\n\r\t" for c in data.decode("utf-8")) for data in originals.values()))
    check("Strict JSON serialization roundtrip", json.loads(encoded(b)) == b)
    counts = {"sources": len(sources), "schools": len(b["schools"]), "domains": len(b["domains"]),
              "questions": len(questions), "selectors": len({q["selector_id"] for q in questions}),
              "fixed_value_sets": len(sets), "fixed_value_entries": sum(len(s["values"]) for s in sets),
              "dynamic_candidate_kinds": len(b["candidate_kinds"]), "soft_fields": len(b["soft_field_definitions"]),
              "questions_by_owner": dict(Counter(q["answer_owner"] for q in questions))}
    report = {"status": "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL",
              "scope": "IMPORT_INTEGRITY_AND_DRAFT_STRUCTURE_ONLY", "counts": counts, "checks": checks,
              "not_tested": ["Graphological validity", "Source completeness or reproduction rights",
                             "Engine accuracy", "OpenAI calls", "Production integration"]}
    return report, originals


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    canonical_research_root = (repo / "research/graphology/foundations-v0.1").resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo / "research/graphology/foundations-v0.1")
    parser.add_argument("--feature-schema", type=Path, default=repo / "schema/graphology_feature_database_v1.json")
    parser.add_argument("--assemble-dir", type=Path, help="NEW directory for original research files; never overwrites")
    args = parser.parse_args()
    try:
        report, originals = validate(args.root.resolve(), args.feature_schema.resolve())
        if report["status"] == "PASS" and args.assemble_dir:
            output = args.assemble_dir.resolve()
            protected_roots = (
                (repo / "schema").resolve(),
                (repo / "src").resolve(),
                canonical_research_root,
                args.root.resolve(),
            )
            if any(output.is_relative_to(root) for root in protected_roots):
                raise ValueError("Output cannot be a production or frozen research directory")
            output.mkdir(parents=True, exist_ok=False)
            for name, data in originals.items():
                safe_path(output, name).write_bytes(data)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
