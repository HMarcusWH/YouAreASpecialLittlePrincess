#!/usr/bin/env python3
"""Validate the complete T26 interpretation database while it remains pending review."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


DOMAINS = [
    "01-context", "02-global", "03-space", "04-size", "05-direction", "06-connection",
    "07-form", "08-stroke", "09-movement", "10-detail", "11-signature", "12-hierarchy",
    "13-interpretation", "14-reference", "15-pair", "16-history",
]


def load(path: Path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate key in {path}: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"Non-finite JSON in {path}: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def concat(root: Path, relative: str):
    return [item for name in DOMAINS for item in load(root / relative / f"{name}.json")]


def load_compiler(repo: Path):
    path = repo / "tools/compile_premium_interpretation_db.py"
    spec = importlib.util.spec_from_file_location("premium_interpretation_compiler", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    research_meta = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")
    research_questions = concat(repo / "research/graphology/foundations-v0.1/blueprint", "questions")
    questions = concat(root, "questions")
    packs = load(root / "packs/question_packs.json")["packs"]
    soft = load(root / "narrative/soft_fields.json")["records"]
    tones = load(root / "narrative/tone_profiles.json")["records"]
    slots = load(root / "reports/report_slots.json")["records"]
    manifest = load(root / "manifest.json")
    exclusions = load(root / "traceability/exclusions.json")
    task_doc = load(repo / "docs/roadmap/tasks.json")
    artifact = load(repo / "schema/premium_interpretation_database_v1.json")
    compiler = load_compiler(repo)

    errors = []

    if len(questions) != 89:
        errors.append("expected 89 production question definitions")
    research_by_id = {x["question_id"]: x for x in research_questions}
    if set(research_by_id) != {x["question_id"] for x in questions}:
        errors.append("production question IDs differ from frozen research")

    for q in questions:
        r = research_by_id[q["question_id"]]
        expected = {
            "selector_id": r["selector_id"],
            "domain_id": r["domain_id"],
            "scope": r["scope"],
            "prompt_text_en": r["question_text_en"],
            "text_origin": r["question_text_origin"],
            "source_support": r["source_support"],
            "source_refs": r["source_refs"],
            "answer_mode": "MULTI_SELECTOR" if r["cardinality"] == "MULTIPLE" else "SELECTOR",
            "answer_owner": r["answer_owner"],
            "model_call_role": r["model_call_role"],
            "required_inputs": r["required_inputs"],
            "required_fact_classes": [r["permitted_evidence_class"]],
            "required_candidate_kinds": [r["candidate_kind"]] if r["candidate_kind"] else [],
            "answer_state_policy": r["answer_state_policy"],
            "numeric_threshold_policy": r["numeric_threshold_policy"],
            "report_target": r["report_target"],
            "note": r["note"],
            "source_status": r["status"],
        }
        for key, value in expected.items():
            if q[key] != value:
                errors.append(f"production question drifted for {q['question_id']}: {key}")
        if q["runtime_status"] != "DRAFT_NOT_ACTIVE" or q["enabled"] is not False:
            errors.append(f"question became active: {q['question_id']}")
        if q["minimum_supporting_fact_count"] is not None or q["minimum_supporting_association_count"] is not None or q["fallback_value_id"] is not None:
            errors.append(f"unreviewed support threshold/fallback invented: {q['question_id']}")

    pack_map = {
        "INDIVIDUAL_GRAPHIC_DRAFT": "PREMIUM_INDIVIDUAL_GRAPHIC_V1",
        "TRADITIONAL_READING_DRAFT": "PREMIUM_TRADITIONAL_READING_V1",
        "REFERENCE_DRAFT": "PREMIUM_REFERENCE_V1",
        "PAIR_DRAFT": "PREMIUM_PAIR_V1",
        "HISTORY_DRAFT": "PREMIUM_HISTORY_V1",
    }
    prod_by_research = {x["research_pack_id"]: x for x in packs}
    if set(prod_by_research) != set(pack_map):
        errors.append("question-pack research mapping incomplete")
    for rpack in research_meta["question_packs"]:
        p = prod_by_research.get(rpack["pack_id"])
        if p is None:
            continue
        if p["pack_id"] != pack_map[rpack["pack_id"]] or p["question_ids"] != rpack["questions"]:
            errors.append(f"question-pack composition drifted: {rpack['pack_id']}")
        if p["runtime_activation"] is not False:
            errors.append(f"question pack became active: {p['pack_id']}")
    trad = next(x for x in packs if x["pack_id"] == "PREMIUM_TRADITIONAL_READING_V1")
    if trad["production_status"] != "BLOCKED_NO_RUNTIME_ELIGIBLE_ASSOCIATIONS":
        errors.append("traditional question pack lost its block")
    ref = next(x for x in packs if x["pack_id"] == "PREMIUM_REFERENCE_V1")
    if ref["production_status"] != "CONDITIONAL_VALID_REFERENCE_RELEASE":
        errors.append("reference question pack lost its reference-release condition")

    research_soft = {x["soft_field_id"]: x for x in research_meta["soft_field_definitions"]}
    if len(soft) != 8 or set(research_soft) != {x["soft_field_id"] for x in soft}:
        errors.append("soft-field population differs from frozen research")
    added_soft_keys = {
        "version", "label_key", "prompt_template_key", "tone_profile_id",
        "prohibited_claim_classes", "support_policy", "runtime_status", "enabled",
    }
    for field in soft:
        stripped = {k: v for k, v in field.items() if k not in added_soft_keys}
        if stripped != research_soft[field["soft_field_id"]]:
            errors.append(f"soft field drifted from frozen research: {field['soft_field_id']}")
        if field["allow_new_numbers"] is not False or field["no_source_no_claim"] is not True:
            errors.append(f"soft field numerical/source guard weakened: {field['soft_field_id']}")
        if field["runtime_status"] != "DRAFT_NOT_ACTIVE" or field["enabled"] is not False:
            errors.append(f"soft field became active: {field['soft_field_id']}")

    if len(tones) != 1 or tones[0]["tone_profile_id"] != "PREMIUM_EVIDENCE_DOSSIER_V1":
        errors.append("expected one evidence-first tone profile")
    if "NEW_NUMERIC_MEASUREMENT_PERCENTILE_PROBABILITY_OR_SCORE" not in tones[0]["prohibited_claim_classes"]:
        errors.append("tone profile permits new numerical claims")
    if tones[0]["runtime_status"] != "DRAFT_NOT_ACTIVE":
        errors.append("tone profile became active")

    if len(slots) != 17 or len({x["report_target"] for x in slots}) != 17:
        errors.append("expected 17 unique report slots")
    if any(x["runtime_status"] != "DRAFT_NOT_ACTIVE" for x in slots):
        errors.append("report slot became active")

    if artifact["version"] != "premium-interpretation-db/1" or artifact["status"] != "POPULATED_PENDING_REVIEW":
        errors.append("compiled artifact version/status invalid")
    if artifact["runtime_activation"] is not False:
        errors.append("compiled artifact became runtime-active")
    expected_compiled = compiler.build_database(repo)
    if artifact != expected_compiled:
        errors.append("compiled artifact differs from deterministic compiler output")

    expected_counts = {
        "selector_definitions": 89,
        "question_definitions": 89,
        "question_packs": 5,
        "soft_field_definitions": 8,
        "candidate_definitions": 33,
        "tone_profiles": 1,
        "report_slots": 17,
        "report_mappings": 97,
    }
    for key, value in expected_counts.items():
        if len(artifact[key]) != value:
            errors.append(f"compiled artifact count differs for {key}")

    if artifact["localization_keys"] != sorted(artifact["localization"]["en"]):
        errors.append("localization key registry differs from English catalogue")
    if len(artifact["localization_keys"]) != len(set(artifact["localization_keys"])):
        errors.append("duplicate localization key")

    question_ids = {x["question_id"] for x in artifact["question_definitions"]}
    selector_ids = {x["selector_id"] for x in artifact["selector_definitions"]}
    soft_ids = {x["soft_field_id"] for x in artifact["soft_field_definitions"]}
    slot_ids = {x["report_slot_id"] for x in artifact["report_slots"]}
    if any(x["content_kind"] == "QUESTION" and (x["content_id"] not in question_ids or x["selector_id"] not in selector_ids) for x in artifact["report_mappings"]):
        errors.append("question report mapping does not resolve")
    if any(x["content_kind"] == "SOFT_FIELD" and x["content_id"] not in soft_ids for x in artifact["report_mappings"]):
        errors.append("soft-field report mapping does not resolve")
    if any(x["report_slot_id"] not in slot_ids for x in artifact["report_mappings"]):
        errors.append("report mapping slot does not resolve")

    if artifact["traditional"]["rule_pack_registry"] and any(x["runtime_activation"] for x in artifact["traditional"]["rule_pack_registry"]):
        errors.append("traditional rule pack became active")
    if any(x["runtime_eligible_association_ids"] for x in artifact["traditional"]["rule_pack_registry"]):
        errors.append("traditional rule pack contains runtime-eligible association")

    t26 = next(x for x in task_doc["tasks"] if x["id"] == "T26")
    if t26["status"] != "IMPLEMENTED_PENDING_REVIEW":
        errors.append("T26 must be IMPLEMENTED_PENDING_REVIEW after PR4")
    if manifest["status"] != "POPULATED_PENDING_REVIEW" or manifest["production_scope"] != "COMPLETE_DATABASE_PENDING_REVIEW":
        errors.append("manifest PR4 completion state invalid")
    if manifest["runtime_activation"] is not False or manifest["t26_status"] != "IMPLEMENTED_PENDING_REVIEW":
        errors.append("manifest PR4 runtime/T26 state invalid")

    required_exclusions = {
        "Runtime OpenAI adapter and dynamic Structured Output request compilation (T15)",
        "Candidate generator implementations owned by later engine/reference/comparison tasks",
        "Runtime activation of traditional associations or school rule packs",
        "Resolution of source/morphology gaps explicitly recorded as blocked",
        "Non-English translations beyond stable localization keys and English canonical copy",
        "Live model evaluation, pricing, payment and deployment",
    }
    if set(exclusions["intentionally_not_in_scope"]) != required_exclusions:
        errors.append("PR4 exclusions differ from reviewed boundary")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "scope": "T26_PR4_COMPLETE_DATABASE_PENDING_REVIEW"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
