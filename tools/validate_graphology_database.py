#!/usr/bin/env python3
"""Validate the complete self-contained interpretation database pending review."""
from __future__ import annotations
from pathlib import Path
import json, sys
TOOLS=Path(__file__).resolve().parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from graphology_db_common import DOMAINS, load, concat, verify_research_baseline

import importlib.util
from validate_graphology_ontology import validate as validate_ontology
from validate_graphology_selector_foundation import validate as validate_selectors
from validate_graphology_traditional_rules import validate as validate_traditional
def load_compiler(repo: Path):
    path=repo/"tools/compile_premium_interpretation_db.py"; spec=importlib.util.spec_from_file_location("premium_interpretation_compiler",path)
    module=importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(module); return module
def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=[]
    for group in (validate_ontology(repo),validate_selectors(repo),validate_traditional(repo)): errors.extend(group)
    artifact=load(repo/"schema/premium_interpretation_database_v1.json"); manifest=load(root/"manifest.json"); stage_doc=load(root/"stage_contract.json"); stage=stage_doc["stages"][stage_doc["current_stage"]]
    compiler=load_compiler(repo)
    if artifact!=compiler.build_database(repo): errors.append("compiled artifact differs from deterministic compiler output")
    if artifact.get("status")!=stage["artifact_status"] or artifact.get("runtime_activation")!=stage["artifact_runtime_activation"]: errors.append("compiled artifact stage invalid")
    required=["sources","source_claims","source_gaps","answer_state_policy","selection_contract","observation_envelope","observation_policy","observation_definitions","feature_mappings","candidate_validation_policy","candidate_envelope","candidate_generator_contracts","selector_generator_map"]
    for key in required:
        if key not in artifact: errors.append(f"compiled artifact missing {key}")
    if "selection_mode" in artifact["enums"]: errors.append("runtime contract still conflates selector origin and cardinality")
    if artifact["enums"].get("selection_domain")!=["FIXED","DYNAMIC"] or artifact["enums"].get("cardinality")!=["SINGLE","MULTIPLE"]: errors.append("runtime selection axes invalid")
    if any(s["answer_state_policy"]!=artifact["answer_state_policy"]["policy_id"] for s in artifact["selector_definitions"]): errors.append("selector answer-state policy does not resolve")
    source_ids={x["source_id"] for x in artifact["sources"]}; claim_ids={x["assertion_id"] for x in artifact["source_claims"]}
    for s in artifact["selector_definitions"]:
        if {r["source_id"] for r in s["source_refs"]}-source_ids: errors.append(f"selector source reference unresolved: {s['selector_id']}")
    for p in artifact["traditional"]["method_policies"]:
        if {r["source_id"] for r in p["source_refs"]}-source_ids: errors.append(f"method-policy source unresolved: {p['policy_id']}")
        if set(p["source_assertion_ids"])-claim_ids: errors.append(f"method-policy assertion unresolved: {p['policy_id']}")
    gen_ids={x["generator_id"] for x in artifact["candidate_generator_contracts"]}
    if any(x["generator_id"] not in gen_ids for x in artifact["selector_generator_map"]): errors.append("selector generator mapping has dangling generator")
    if len(artifact["observation_definitions"])!=manifest["counts"]["observations"]: errors.append("compiled observation count mismatch")
    if len(artifact["feature_mappings"])!=50: errors.append("compiled feature mapping count mismatch")
    en=artifact["localization"]["en"]
    if artifact["localization_keys"]!=sorted(en): errors.append("localization registry differs from English catalogue")
    for q in artifact["question_definitions"]:
        if q["prompt_template_key"] not in en: errors.append(f"question prompt localization missing: {q['question_id']}")
    for f in artifact["soft_field_definitions"]:
        if f["label_key"] not in en: errors.append(f"soft label localization missing: {f['soft_field_id']}")
        if f["prompt_template_key"] not in en: errors.append(f"soft prompt localization missing: {f['soft_field_id']}")
    if any(p["runtime_activation"] or p["runtime_eligible_association_ids"] for p in artifact["traditional"]["rule_pack_registry"]): errors.append("compiled traditional rules activated")
    return list(dict.fromkeys(errors))
def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo); print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
