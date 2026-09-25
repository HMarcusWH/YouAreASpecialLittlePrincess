#!/usr/bin/env python3
"""Validate the complete self-contained interpretation database pending review."""
from __future__ import annotations
from pathlib import Path
import json, sys, importlib.util
TOOLS=Path(__file__).resolve().parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from graphology_db_common import DOMAINS, load, concat
from validate_graphology_ontology import validate as validate_ontology
from validate_graphology_selector_foundation import validate as validate_selectors
from validate_graphology_traditional_rules import validate as validate_traditional

EXPECTED_PROHIBITED_CLAIMS={
    "CLINICAL_OR_PSYCHIATRIC_DIAGNOSIS",
    "INTELLIGENCE_OR_COGNITIVE_ABILITY",
    "CRIMINALITY_OR_DECEPTION",
    "EMPLOYMENT_SUITABILITY",
    "RELATIONSHIP_OUTCOME_OR_COMPATIBILITY",
    "MORAL_WORTH",
    "NEW_NUMERIC_MEASUREMENT_PERCENTILE_PROBABILITY_OR_SCORE",
}

def load_compiler(repo: Path):
    path=repo/"tools/compile_premium_interpretation_db.py"
    spec=importlib.util.spec_from_file_location("premium_interpretation_compiler",path)
    module=importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(module); return module

def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=[]
    for group in (validate_ontology(repo),validate_selectors(repo),validate_traditional(repo)): errors.extend(group)
    research_meta=load(repo/"research/graphology/foundations-v0.1/blueprint/metadata.json")
    research_questions=concat(repo/"research/graphology/foundations-v0.1/blueprint","questions")
    questions=concat(root,"questions"); packs=load(root/"packs/question_packs.json")["packs"]
    soft=load(root/"narrative/soft_fields.json")["records"]; tones=load(root/"narrative/tone_profiles.json")["records"]
    slots=load(root/"reports/report_slots.json")["records"]; artifact=load(repo/"schema/premium_interpretation_database_v1.json")
    manifest=load(root/"manifest.json"); stage_doc=load(root/"stage_contract.json"); stage=stage_doc["stages"][stage_doc["current_stage"]]
    compiler=load_compiler(repo)

    research_by_id={x["question_id"]:x for x in research_questions}
    if len(questions)!=89 or set(research_by_id)!={x["question_id"] for x in questions}: errors.append("production question coverage differs from frozen research")
    for q in questions:
        r=research_by_id[q["question_id"]]
        expected={
          "selector_id":r["selector_id"],"domain_id":r["domain_id"],"scope":r["scope"],"prompt_text_en":r["question_text_en"],
          "text_origin":r["question_text_origin"],"source_support":r["source_support"],"source_refs":r["source_refs"],
          "answer_mode":"MULTI_SELECTOR" if r["cardinality"]=="MULTIPLE" else "SELECTOR","answer_owner":r["answer_owner"],
          "model_call_role":r["model_call_role"],"required_inputs":r["required_inputs"],
          "required_fact_classes":[r["permitted_evidence_class"]],"required_candidate_kinds":[r["candidate_kind"]] if r["candidate_kind"] else [],
          "answer_state_policy":r["answer_state_policy"],"numeric_threshold_policy":r["numeric_threshold_policy"],
          "report_target":r["report_target"],"note":r["note"],"source_status":r["status"],
        }
        for key,val in expected.items():
            if q.get(key)!=val: errors.append(f"production question drift {key}: {q['question_id']}")
        if q.get("version")!="1.0.0" or q.get("prompt_template_key")!=f"question.{q['question_id'].lower()}":
            errors.append(f"question application metadata drift: {q['question_id']}")
        if q.get("runtime_status")!="DRAFT_NOT_ACTIVE" or q.get("enabled") is not False:
            errors.append(f"question activated: {q['question_id']}")
        if q.get("minimum_supporting_fact_count") is not None or q.get("minimum_supporting_association_count") is not None or q.get("fallback_value_id") is not None:
            errors.append(f"unreviewed support threshold/fallback invented: {q['question_id']}")

    pack_map={"INDIVIDUAL_GRAPHIC_DRAFT":"PREMIUM_INDIVIDUAL_GRAPHIC_V1","TRADITIONAL_READING_DRAFT":"PREMIUM_TRADITIONAL_READING_V1","REFERENCE_DRAFT":"PREMIUM_REFERENCE_V1","PAIR_DRAFT":"PREMIUM_PAIR_V1","HISTORY_DRAFT":"PREMIUM_HISTORY_V1"}
    prod_by_research={x["research_pack_id"]:x for x in packs}
    if set(prod_by_research)!=set(pack_map): errors.append("question-pack research mapping incomplete")
    for rpack in research_meta["question_packs"]:
        p=prod_by_research.get(rpack["pack_id"])
        if not p: continue
        if p.get("pack_id")!=pack_map[rpack["pack_id"]] or p.get("question_ids")!=rpack["questions"]: errors.append(f"question-pack composition drift: {rpack['pack_id']}")
        if p.get("runtime_activation") is not False: errors.append(f"question pack activated: {p['pack_id']}")
    trad=next(x for x in packs if x["pack_id"]=="PREMIUM_TRADITIONAL_READING_V1")
    if trad.get("production_status")!="BLOCKED_NO_RUNTIME_ELIGIBLE_ASSOCIATIONS": errors.append("traditional question pack lost its block")
    ref=next(x for x in packs if x["pack_id"]=="PREMIUM_REFERENCE_V1")
    if ref.get("production_status")!="CONDITIONAL_VALID_REFERENCE_RELEASE": errors.append("reference question pack lost its reference-release condition")

    research_soft={x["soft_field_id"]:x for x in research_meta["soft_field_definitions"]}
    if len(soft)!=8 or set(research_soft)!={x["soft_field_id"] for x in soft}: errors.append("soft-field population differs from frozen research")
    added={"version","label_key","label_en","prompt_template_key","prompt_text_en","prompt_text_origin","tone_profile_id","prohibited_claim_classes","support_policy","runtime_status","enabled"}
    for f in soft:
        stripped={k:v for k,v in f.items() if k not in added}
        if stripped!=research_soft[f["soft_field_id"]]: errors.append(f"soft field drift from frozen research: {f['soft_field_id']}")
        if f.get("version")!="1.0.0" or f.get("support_policy")!="REQUIRED_SUPPORT_ONLY": errors.append(f"soft field application contract drift: {f['soft_field_id']}")
        if f.get("label_en")!=f.get("purpose") or f.get("prompt_text_en")!=f.get("purpose") or f.get("prompt_text_origin")!="APPLICATION_DERIVED_FROM_FROZEN_RESEARCH_PURPOSE":
            errors.append(f"soft field copy provenance drift: {f['soft_field_id']}")
        if f.get("allow_new_numbers") is not False or f.get("no_source_no_claim") is not True:
            errors.append(f"soft field numerical/source guard weakened: {f['soft_field_id']}")
        if set(f.get("prohibited_claim_classes",[]))!=EXPECTED_PROHIBITED_CLAIMS:
            errors.append(f"soft field prohibited-claim set drift: {f['soft_field_id']}")
        if f.get("runtime_status")!="DRAFT_NOT_ACTIVE" or f.get("enabled") is not False:
            errors.append(f"soft field activated: {f['soft_field_id']}")

    if len(tones)!=1 or tones[0].get("tone_profile_id")!="PREMIUM_EVIDENCE_DOSSIER_V1": errors.append("tone profile registry changed")
    if set(tones[0].get("prohibited_claim_classes",[]))!=EXPECTED_PROHIBITED_CLAIMS:
        errors.append("tone profile prohibited-claim set drift")
    if tones[0].get("runtime_status")!="DRAFT_NOT_ACTIVE": errors.append("tone profile activated")
    if len(slots)!=17 or len({x["report_target"] for x in slots})!=17 or any(x.get("runtime_status")!="DRAFT_NOT_ACTIVE" for x in slots):
        errors.append("report-slot registry invalid or activated")

    expected_compiled=compiler.build_database(repo)
    if artifact!=expected_compiled: errors.append("compiled artifact differs from deterministic compiler output")
    if artifact.get("status")!=stage["artifact_status"] or artifact.get("runtime_activation")!=stage["artifact_runtime_activation"]: errors.append("compiled artifact stage invalid")
    required=["sources","source_claims","source_gaps","answer_state_policy","selection_contract","observation_envelope","observation_policy","observation_definitions","feature_mappings","candidate_validation_policy","candidate_envelope","candidate_generator_contracts","selector_generator_map"]
    for key in required:
        if key not in artifact: errors.append(f"compiled artifact missing {key}")
    if "selection_mode" in artifact["enums"] or artifact["enums"].get("selection_domain")!=["FIXED","DYNAMIC"] or artifact["enums"].get("cardinality")!=["SINGLE","MULTIPLE"]:
        errors.append("runtime selection axes invalid")

    source_ids={x["source_id"] for x in artifact["sources"]}; claim_ids={x["assertion_id"] for x in artifact["source_claims"]}
    if any(s["answer_state_policy"]!=artifact["answer_state_policy"]["policy_id"] for s in artifact["selector_definitions"]): errors.append("selector answer-state policy does not resolve")
    for s in artifact["selector_definitions"]:
        if {r["source_id"] for r in s["source_refs"]}-source_ids: errors.append(f"selector source reference unresolved: {s['selector_id']}")
    for p in artifact["traditional"]["method_policies"]:
        if {r["source_id"] for r in p["source_refs"]}-source_ids: errors.append(f"method-policy source unresolved: {p['policy_id']}")
        if set(p["source_assertion_ids"])-claim_ids: errors.append(f"method-policy assertion unresolved: {p['policy_id']}")

    if len(artifact["observation_definitions"])!=manifest["counts"]["observations"]: errors.append("compiled observation count mismatch")
    if len(artifact["feature_mappings"])!=50: errors.append("compiled feature mapping count mismatch")
    if len(artifact["candidate_generator_contracts"])!=33 or len(artifact["selector_generator_map"])!=35: errors.append("compiled candidate generator contract count mismatch")

    en=artifact["localization"]["en"]
    if artifact["localization_keys"]!=sorted(en) or len(artifact["localization_keys"])!=len(set(artifact["localization_keys"])): errors.append("localization registry invalid")
    for q in artifact["question_definitions"]:
        if q["prompt_template_key"] not in en: errors.append(f"question prompt localization missing: {q['question_id']}")
    for f in artifact["soft_field_definitions"]:
        if f["label_key"] not in en: errors.append(f"soft label localization missing: {f['soft_field_id']}")
        if f["prompt_template_key"] not in en: errors.append(f"soft prompt localization missing: {f['soft_field_id']}")

    if any(p.get("runtime_activation") or p.get("runtime_eligible_association_ids") for p in artifact["traditional"]["rule_pack_registry"]):
        errors.append("compiled traditional rules activated")
    return list(dict.fromkeys(errors))

def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo)
    print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
