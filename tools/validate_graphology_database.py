#!/usr/bin/env python3
"""Validate the complete self-contained interpretation database pending review."""

from __future__ import annotations
from pathlib import Path
import json
import sys
import importlib.util

from graphology_db_common import load, concat
from validate_graphology_ontology import validate as validate_ontology
from validate_graphology_selector_foundation import validate as validate_selectors
from validate_graphology_traditional_rules import validate as validate_traditional

EXPECTED_PROHIBITED_CLAIMS = {
    "CLINICAL_OR_PSYCHIATRIC_DIAGNOSIS",
    "INTELLIGENCE_OR_COGNITIVE_ABILITY",
    "CRIMINALITY_OR_DECEPTION",
    "EMPLOYMENT_SUITABILITY",
    "RELATIONSHIP_OUTCOME_OR_COMPATIBILITY",
    "MORAL_WORTH",
    "NEW_NUMERIC_MEASUREMENT_PERCENTILE_PROBABILITY_OR_SCORE",
}


def load_compiler(repo: Path):
    path = repo / "tools/compile_premium_interpretation_db.py"
    spec = importlib.util.spec_from_file_location("premium_interpretation_compiler", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    errors = []
    for group in (validate_ontology(repo), validate_selectors(repo), validate_traditional(repo)):
        errors.extend(group)
    research_meta = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")
    research_questions = concat(repo / "research/graphology/foundations-v0.1/blueprint", "questions")
    questions = concat(root, "questions")
    packs_doc = load(root / "packs/question_packs.json")
    packs = packs_doc["packs"]
    soft_doc = load(root / "narrative/soft_fields.json")
    soft = soft_doc["records"]
    tones_doc = load(root / "narrative/tone_profiles.json")
    tones = tones_doc["records"]
    slots_doc = load(root / "reports/report_slots.json")
    slots = slots_doc["records"]
    localization_policy = load(root / "localization/policy.json")
    model_pack_policy = load(root / "packs/model_pack_policy.json")
    artifact = load(repo / "schema/premium_interpretation_database_v1.json")
    manifest = load(root / "manifest.json")
    stage_doc = load(root / "stage_contract.json")
    stage = stage_doc["stages"][stage_doc["current_stage"]]
    compiler = load_compiler(repo)

    research_by_id = {x["question_id"]: x for x in research_questions}
    if len(questions) != 89 or set(research_by_id) != {x["question_id"] for x in questions}:
        errors.append("production question coverage differs from frozen research")
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
        for key, val in expected.items():
            if q.get(key) != val:
                errors.append(f"production question drift {key}: {q['question_id']}")
        if q.get("version") != "1.0.0" or q.get("prompt_template_key") != f"question.{q['question_id'].lower()}":
            errors.append(f"question application metadata drift: {q['question_id']}")
        if q.get("runtime_status") != "DRAFT_NOT_ACTIVE" or q.get("enabled") is not False:
            errors.append(f"question activated: {q['question_id']}")
        if (
            q.get("minimum_supporting_fact_count") is not None
            or q.get("minimum_supporting_association_count") is not None
            or q.get("fallback_value_id") is not None
        ):
            errors.append(f"unreviewed support threshold/fallback invented: {q['question_id']}")

    pack_map = {
        "INDIVIDUAL_GRAPHIC_DRAFT": "PREMIUM_INDIVIDUAL_GRAPHIC_V1",
        "TRADITIONAL_READING_DRAFT": "PREMIUM_TRADITIONAL_READING_V1",
        "REFERENCE_DRAFT": "PREMIUM_REFERENCE_V1",
        "PAIR_DRAFT": "PREMIUM_PAIR_V1",
        "HISTORY_DRAFT": "PREMIUM_HISTORY_V1",
    }
    expected_model_pack_policy = {
        "policy_id": "graphology-model-pack-policy/1",
        "version": "1.0.0",
        "research_id": "model_pack_policy",
        "policy": research_meta["model_pack_policy"],
        "runtime_activation": False,
    }
    if model_pack_policy != expected_model_pack_policy:
        errors.append("model-pack policy contract drift")
    if packs_doc.get("version") != "graphology-question-packs/1" or packs_doc.get("runtime_activation") is not False:
        errors.append("question-pack registry metadata/lifecycle drift")
    if len(packs) != 5 or len({x["pack_id"] for x in packs}) != 5 or len({x["research_pack_id"] for x in packs}) != 5:
        errors.append("question-pack count/uniqueness invalid")
    prod_by_research = {x["research_pack_id"]: x for x in packs}
    if set(prod_by_research) != set(pack_map):
        errors.append("question-pack research mapping incomplete")
    pack_application = {
        "INDIVIDUAL_GRAPHIC_DRAFT": {
            "scope": "INDIVIDUAL",
            "soft_field_ids": ["SOFT_GRAPHIC_PORTRAIT", "SOFT_COMBINATION", "SOFT_LIMITATION"],
            "preconditions": ["AUTHORIZED_IMAGE", "APPLICABLE_QUESTIONS_COMPILED"],
            "production_status": "DRAFT_NOT_ACTIVE",
        },
        "TRADITIONAL_READING_DRAFT": {
            "scope": "INDIVIDUAL",
            "soft_field_ids": ["SOFT_TRADITIONAL_SYNTHESIS", "SOFT_ALTERNATIVE", "SOFT_LIMITATION"],
            "preconditions": ["REVIEWED_SCHOOL_RULE_PACK", "RUNTIME_ELIGIBLE_TRADITIONAL_CANDIDATE"],
            "production_status": "BLOCKED_NO_RUNTIME_ELIGIBLE_ASSOCIATIONS",
        },
        "REFERENCE_DRAFT": {
            "scope": "INDIVIDUAL",
            "soft_field_ids": ["SOFT_DISTINCTIVENESS", "SOFT_LIMITATION"],
            "preconditions": ["VALID_REFERENCE_RELEASE", "ELIGIBLE_REFERENCE_CLAIMS"],
            "production_status": "CONDITIONAL_VALID_REFERENCE_RELEASE",
        },
        "PAIR_DRAFT": {
            "scope": "PAIR",
            "soft_field_ids": ["SOFT_PAIR", "SOFT_LIMITATION"],
            "preconditions": ["AUTHORIZED_PAIR_INPUTS", "PAIR_COMPARABLE"],
            "production_status": "DRAFT_NOT_ACTIVE",
        },
        "HISTORY_DRAFT": {
            "scope": "HISTORY",
            "soft_field_ids": ["SOFT_HISTORY", "SOFT_LIMITATION"],
            "preconditions": ["AUTHORIZED_HISTORY_INPUTS", "HISTORY_COMPARABLE"],
            "production_status": "DRAFT_NOT_ACTIVE",
        },
    }
    research_pack_by_id = {x["pack_id"]: x for x in research_meta["question_packs"]}
    for research_id, production_id in pack_map.items():
        p = prod_by_research.get(research_id)
        rpack = research_pack_by_id[research_id]
        if not p:
            continue
        expected_app = pack_application[research_id]
        if p.get("pack_id") != production_id or p.get("question_ids") != rpack["questions"]:
            errors.append(f"question-pack composition drift: {research_id}")
        if p.get("version") != "1.0.0" or p.get("output_schema_version") != "premium-analysis/1":
            errors.append(f"question-pack version/schema drift: {production_id}")
        if (
            p.get("scope") != expected_app["scope"]
            or p.get("soft_field_ids") != expected_app["soft_field_ids"]
            or p.get("preconditions") != expected_app["preconditions"]
        ):
            errors.append(f"question-pack application wiring drift: {production_id}")
        if (
            p.get("model_pack_policy") != research_meta["model_pack_policy"]
            or p.get("research_status") != rpack["status"]
        ):
            errors.append(f"question-pack research policy/status drift: {production_id}")
        if p.get("production_status") != expected_app["production_status"] or p.get("runtime_activation") is not False:
            errors.append(f"question-pack lifecycle drift: {production_id}")

    if soft_doc.get("version") != "graphology-soft-fields/1" or soft_doc.get("runtime_activation") is not False:
        errors.append("soft-field registry metadata/lifecycle drift")
    research_soft = {x["soft_field_id"]: x for x in research_meta["soft_field_definitions"]}
    if (
        len(soft) != 8
        or len({x["soft_field_id"] for x in soft}) != 8
        or set(research_soft) != {x["soft_field_id"] for x in soft}
    ):
        errors.append("soft-field population differs from frozen research")
    added = {
        "version",
        "label_key",
        "label_en",
        "prompt_template_key",
        "prompt_text_en",
        "prompt_text_origin",
        "tone_profile_id",
        "prohibited_claim_classes",
        "support_policy",
        "runtime_status",
        "enabled",
    }
    for f in soft:
        stripped = {k: v for k, v in f.items() if k not in added}
        if stripped != research_soft[f["soft_field_id"]]:
            errors.append(f"soft field drift from frozen research: {f['soft_field_id']}")
        if f.get("version") != "1.0.0" or f.get("support_policy") != "REQUIRED_SUPPORT_ONLY":
            errors.append(f"soft field application contract drift: {f['soft_field_id']}")
        if (
            f.get("label_en") != f.get("purpose")
            or f.get("prompt_text_en") != f.get("purpose")
            or f.get("prompt_text_origin") != "APPLICATION_DERIVED_FROM_FROZEN_RESEARCH_PURPOSE"
        ):
            errors.append(f"soft field copy provenance drift: {f['soft_field_id']}")
        if f.get("allow_new_numbers") is not False or f.get("no_source_no_claim") is not True:
            errors.append(f"soft field numerical/source guard weakened: {f['soft_field_id']}")
        if set(f.get("prohibited_claim_classes", [])) != EXPECTED_PROHIBITED_CLAIMS:
            errors.append(f"soft field prohibited-claim set drift: {f['soft_field_id']}")
        if f.get("runtime_status") != "DRAFT_NOT_ACTIVE" or f.get("enabled") is not False:
            errors.append(f"soft field activated: {f['soft_field_id']}")

    expected_tone = {
        "tone_profile_id": "PREMIUM_EVIDENCE_DOSSIER_V1",
        "version": "1.0.0",
        "origin": "APPLICATION_AUTHORED",
        "label_key": "tone.premium_evidence_dossier.label",
        "label_en": "Evidence-first personal dossier",
        "style_traits": ["CONCISE", "POLISHED", "CURIOUS", "NON_CLINICAL", "LIGHTLY_PLAYFUL_WHERE_APPROPRIATE"],
        "rules": [
            "State measured/reference facts as supplied; do not rewrite or upgrade them.",
            "Separate visual observations from canonical measurements.",
            "Label historical/traditional graphology as traditional interpretation.",
            "Prefer specific evidence-linked language over flattering generalities.",
            "Say when evidence is mixed, unavailable, blocked, or insufficient.",
            "Do not introduce new numerical claims.",
        ],
        "prohibited_claim_classes": EXPECTED_PROHIBITED_CLAIMS,
        "runtime_status": "DRAFT_NOT_ACTIVE",
    }
    if (
        tones_doc.get("version") != "graphology-tone-profiles/1"
        or tones_doc.get("runtime_activation") is not False
        or len(tones) != 1
    ):
        errors.append("tone profile registry metadata/lifecycle drift")
    else:
        tone = tones[0]
        for key, val in expected_tone.items():
            actual = set(tone.get(key, [])) if key == "prohibited_claim_classes" else tone.get(key)
            if actual != val:
                errors.append(f"tone profile drift: {key}")

    expected_targets = [
        "graphology.context",
        "graphology.global",
        "graphology.space",
        "graphology.size",
        "graphology.direction",
        "graphology.connection",
        "graphology.form",
        "graphology.stroke",
        "graphology.movement",
        "graphology.detail",
        "graphology.signature",
        "graphology.hierarchy",
        "graphology.interpretation",
        "graphology.reference",
        "graphology.pair",
        "graphology.history",
        "graphology.synthesis",
    ]
    if slots_doc.get("version") != "graphology-report-slots/1" or slots_doc.get("runtime_activation") is not False:
        errors.append("report-slot registry metadata/lifecycle drift")
    if (
        len(slots) != 17
        or [x.get("report_target") for x in slots] != expected_targets
        or len({x.get("report_slot_id") for x in slots}) != 17
    ):
        errors.append("report-slot order/coverage/uniqueness invalid")
    for idx, slot in enumerate(slots, 1):
        target = expected_targets[idx - 1]
        stem = target.removeprefix("graphology.")
        expected_scope = (
            "PAIR"
            if stem == "pair"
            else "HISTORY"
            if stem == "history"
            else "ALL"
            if stem == "synthesis"
            else "INDIVIDUAL"
        )
        if (
            slot.get("report_slot_id") != f"SLOT_{stem.upper()}"
            or slot.get("scope") != expected_scope
            or slot.get("order") != idx
        ):
            errors.append(f"report-slot identity/scope/order drift: {target}")
        if (
            slot.get("label_key") != f"report.{stem}.label"
            or slot.get("content_origin") != "APPLICATION_REPORT_ARCHITECTURE"
            or slot.get("runtime_status") != "DRAFT_NOT_ACTIVE"
        ):
            errors.append(f"report-slot metadata/lifecycle drift: {target}")

    expected_localization_policy = {
        "version": "graphology-localization-policy/1",
        "canonical_locale": "en",
        "supported_locales": ["en"],
        "planned_locales": ["sv"],
        "source_text_policy": "English question text and value labels are preserved from the frozen research/application draft. Localization keys are stable IDs; adding a translation must not change IDs or semantics.",
        "compiler_output": "The compiler emits a complete English localization catalogue and a sorted localization-key registry.",
        "runtime_status": "DRAFT_NOT_ACTIVE",
    }
    if localization_policy != expected_localization_policy:
        errors.append("localization policy drift")

    expected_compiled = compiler.build_database(repo)
    if artifact != expected_compiled:
        errors.append("compiled artifact differs from deterministic compiler output")
    if (
        artifact.get("status") != stage["artifact_status"]
        or artifact.get("runtime_activation") != stage["artifact_runtime_activation"]
    ):
        errors.append("compiled artifact stage invalid")
    required = [
        "sources",
        "source_claims",
        "source_gaps",
        "answer_state_policy",
        "selection_contract",
        "observation_envelope",
        "observation_policy",
        "observation_definitions",
        "feature_mappings",
        "candidate_validation_policy",
        "candidate_envelope",
        "candidate_generator_contracts",
        "selector_generator_map",
    ]
    for key in required:
        if key not in artifact:
            errors.append(f"compiled artifact missing {key}")
    if (
        "selection_mode" in artifact["enums"]
        or artifact["enums"].get("selection_domain") != ["FIXED", "DYNAMIC"]
        or artifact["enums"].get("cardinality") != ["SINGLE", "MULTIPLE"]
    ):
        errors.append("runtime selection axes invalid")

    source_ids = {x["source_id"] for x in artifact["sources"]}
    claim_ids = {x["assertion_id"] for x in artifact["source_claims"]}
    if any(
        s["answer_state_policy"] != artifact["answer_state_policy"]["policy_id"]
        for s in artifact["selector_definitions"]
    ):
        errors.append("selector answer-state policy does not resolve")
    for s in artifact["selector_definitions"]:
        if {r["source_id"] for r in s["source_refs"]} - source_ids:
            errors.append(f"selector source reference unresolved: {s['selector_id']}")
    for p in artifact["traditional"]["method_policies"]:
        if {r["source_id"] for r in p["source_refs"]} - source_ids:
            errors.append(f"method-policy source unresolved: {p['policy_id']}")
        if set(p["source_assertion_ids"]) - claim_ids:
            errors.append(f"method-policy assertion unresolved: {p['policy_id']}")

    if len(artifact["observation_definitions"]) != manifest["counts"]["observations"]:
        errors.append("compiled observation count mismatch")
    if len(artifact["feature_mappings"]) != 50:
        errors.append("compiled feature mapping count mismatch")
    if len(artifact["candidate_generator_contracts"]) != 33 or len(artifact["selector_generator_map"]) != 35:
        errors.append("compiled candidate generator contract count mismatch")

    en = artifact["localization"]["en"]
    if artifact["localization_keys"] != sorted(en) or len(artifact["localization_keys"]) != len(
        set(artifact["localization_keys"])
    ):
        errors.append("localization registry invalid")
    for q in artifact["question_definitions"]:
        if q["prompt_template_key"] not in en:
            errors.append(f"question prompt localization missing: {q['question_id']}")
    for f in artifact["soft_field_definitions"]:
        if f["label_key"] not in en:
            errors.append(f"soft label localization missing: {f['soft_field_id']}")
        if f["prompt_template_key"] not in en:
            errors.append(f"soft prompt localization missing: {f['soft_field_id']}")

    if any(
        p.get("runtime_activation") or p.get("runtime_eligible_association_ids")
        for p in artifact["traditional"]["rule_pack_registry"]
    ):
        errors.append("compiled traditional rules activated")

    pr4_trace = load(root / "traceability/pr4_content.json")["records"]
    pack_pairs = {
        ("QUESTION_PACK", r["pack_id"], "QUESTION_PACK", pack_map[r["pack_id"]])
        for r in research_meta["question_packs"]
    }
    soft_pairs = {
        ("SOFT_FIELD", r["soft_field_id"], "SOFT_FIELD", r["soft_field_id"])
        for r in research_meta["soft_field_definitions"]
    }
    question_pairs = {
        ("QUESTION", q["question_id"], "QUESTION_DEFINITION", q["question_id"]) for q in research_questions
    }
    expected_pr4 = (
        pack_pairs
        | soft_pairs
        | question_pairs
        | {("MODEL_PACK_POLICY", "model_pack_policy", "QUESTION_PACK_POLICY", "graphology-model-pack-policy/1")}
    )
    actual_pr4 = [(x["research_kind"], x["research_id"], x["production_kind"], x["production_id"]) for x in pr4_trace]
    if len(actual_pr4) != len(set(actual_pr4)) or set(actual_pr4) != expected_pr4:
        errors.append("PR4 content traceability drift")

    expected_counts = {
        "sources": len(artifact["sources"]),
        "schools": len(artifact["schools"]),
        "domains": len(artifact["domains"]),
        "concepts": len(artifact["concepts"]),
        "source_claims": len(artifact["source_claims"]),
        "concept_relationships": len(artifact["concept_relationships"]["relationships"]),
        "observations": len(artifact["observation_definitions"]),
        "canonical_feature_mappings": len(artifact["feature_mappings"]),
        "mapped_canonical_feature_ids": len({x["canonical_feature_id"] for x in artifact["feature_mappings"]}),
        "value_sets": len(artifact["selector_value_sets"]),
        "value_entries": sum(len(x["values"]) for x in artifact["selector_value_sets"]),
        "selectors": len(artifact["selector_definitions"]),
        "fixed_selectors": sum(x["selection_domain"] == "FIXED" for x in artifact["selector_definitions"]),
        "dynamic_selectors": sum(x["selection_domain"] == "DYNAMIC" for x in artifact["selector_definitions"]),
        "candidate_kinds": len(artifact["candidate_definitions"]),
        "answer_states": len(artifact["answer_state_policy"]["states"]),
        "traditional_method_policies": len(artifact["traditional"]["method_policies"]),
        "association_contracts": 1,
        "candidate_validation_policies": 1,
        "historical_association_stubs": len(artifact["traditional"]["associations"]["jaminian"]),
        "runtime_eligible_associations": sum(
            len(x["runtime_eligible_association_ids"]) for x in artifact["traditional"]["rule_pack_registry"]
        ),
        "rule_pack_shells": len(artifact["traditional"]["rule_pack_registry"]),
        "active_rule_packs": sum(bool(x["runtime_activation"]) for x in artifact["traditional"]["rule_pack_registry"]),
        "question_definitions": len(artifact["question_definitions"]),
        "question_packs": len(artifact["question_packs"]),
        "soft_fields": len(artifact["soft_field_definitions"]),
        "tone_profiles": len(artifact["tone_profiles"]),
        "report_slots": len(artifact["report_slots"]),
        "report_mappings": len(artifact["report_mappings"]),
        "candidate_generator_contracts": len(artifact["candidate_generator_contracts"]),
        "selector_generator_mappings": len(artifact["selector_generator_map"]),
        "compiled_feature_mappings": len(artifact["feature_mappings"]),
        "compiled_source_records": len(artifact["sources"]),
        "compiled_source_claims": len(artifact["source_claims"]),
    }
    for key, val in expected_counts.items():
        if manifest["counts"].get(key) != val:
            errors.append(f"manifest compiled count drift: {key}")
    return list(dict.fromkeys(errors))


def main():
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
