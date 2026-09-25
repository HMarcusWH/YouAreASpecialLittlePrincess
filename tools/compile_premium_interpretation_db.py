#!/usr/bin/env python3
"""Compile the modular graphology interpretation database into one self-contained T15 artifact."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
from graphology_db_common import DOMAINS, load, concat

def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")

def build_database(repo: Path) -> dict:
    root=repo/"schema/graphology_interpretation/v1"
    manifest=load(root/"manifest.json")
    contract=load(root/"runtime_contract.json")
    sources=load(root/"ontology/sources.json")
    source_claims=load(root/"ontology/source_claims.json")
    source_gaps=load(root/"traceability/source_gaps.json")["gaps"]
    schools=load(root/"ontology/schools.json")
    domains=load(root/"ontology/domains.json")
    concepts=load(root/"ontology/concepts.json")
    concept_relationships=load(root/"ontology/concept_relationships.json")
    values=load(root/"values/value_sets.json")
    answer_states=load(root/"values/answer_states.json")
    selection_contract=load(root/"values/selection_contract.json")
    observation_envelope=load(root/"ontology/observation_envelope.json")
    observation_policy=load(root/"ontology/observation_policy.json")
    observations=concat(root,"ontology/observations")
    feature_mappings=concat(root,"ontology/feature_mappings")
    selectors=concat(root,"selectors")
    questions=concat(root,"questions")
    packs=load(root/"packs/question_packs.json")["packs"]
    soft=load(root/"narrative/soft_fields.json")["records"]
    candidates=load(root/"candidates/candidate_definitions.json")["records"]
    candidate_policy=load(root/"candidates/candidate_validation_policy.json")
    candidate_envelope=load(root/"candidates/candidate_envelope.json")
    generator_contracts=load(root/"candidates/generator_contracts.json")["records"]
    selector_generator_map=load(root/"candidates/selector_generator_map.json")["records"]
    tones=load(root/"narrative/tone_profiles.json")["records"]
    slots=load(root/"reports/report_slots.json")["records"]
    localization_policy=load(root/"localization/policy.json")

    association_contract=load(root/"traditional/association_contract.json")
    method_policies=load(root/"traditional/method_policies.json")["records"]
    jaminian=load(root/"traditional/associations/jaminian.json")
    rule_packs=load(root/"traditional/rule_pack_registry.json")["packs"]
    activation_gates=load(root/"traditional/activation_gates.json")

    slot_by_target={x["report_target"]:x["report_slot_id"] for x in slots}
    report_mappings=[]
    for q in questions:
        report_mappings.append({"content_kind":"QUESTION","content_id":q["question_id"],"selector_id":q["selector_id"],"report_target":q["report_target"],"report_slot_id":slot_by_target[q["report_target"]]})
    for f in soft:
        report_mappings.append({"content_kind":"SOFT_FIELD","content_id":f["soft_field_id"],"selector_id":None,"report_target":f["report_target"],"report_slot_id":slot_by_target[f["report_target"]]})

    en={}
    for school in schools: en[f"school.{school['school_id'].lower()}.label"]=school["label"]
    for domain in domains: en[f"domain.{domain['domain_id'].lower()}.label"]=domain["label"]
    for value_set in values:
        for value in value_set["values"]: en[value["label_key"]]=value["label_en"]
    for q in questions: en[q["prompt_template_key"]]=q["prompt_text_en"]
    for f in soft:
        en[f["label_key"]]=f["label_en"]
        en[f["prompt_template_key"]]=f["prompt_text_en"]
    for tone in tones: en[tone["label_key"]]=tone["label_en"]
    for slot in slots: en[slot["label_key"]]=slot["label_en"]

    return {
      "version":"premium-interpretation-db/1","status":"POPULATED_PENDING_REVIEW","runtime_activation":False,
      "source_database_version":manifest["version"],"research_baseline_commit":manifest["research_baseline_commit"],
      "design_principles":contract["design_principles"],"enums":contract["enums"],
      "sources":sources,"source_claims":source_claims,"source_gaps":source_gaps,
      "schools":schools,"domains":domains,"concepts":concepts,"concept_relationships":concept_relationships,
      "selector_value_sets":values,"answer_state_policy":answer_states,"selection_contract":selection_contract,
      "observation_envelope":observation_envelope,"observation_policy":observation_policy,
      "observation_definitions":observations,"feature_mappings":feature_mappings,
      "selector_definitions":selectors,"question_definitions":questions,"question_packs":packs,
      "soft_field_definitions":soft,"candidate_definitions":candidates,
      "candidate_validation_policy":candidate_policy,"candidate_envelope":candidate_envelope,
      "candidate_generator_contracts":generator_contracts,"selector_generator_map":selector_generator_map,
      "tone_profiles":tones,"report_slots":slots,"report_mappings":report_mappings,
      "localization_policy":localization_policy,"localization_keys":sorted(en),"localization":{"en":en},
      "traditional":{
        "association_contract":association_contract,"candidate_validation_policy_id":candidate_policy["policy_id"],
        "method_policies":method_policies,"associations":{"jaminian":jaminian},
        "rule_pack_registry":rule_packs,"activation_gates":activation_gates
      }
    }

def main() -> int:
    repo=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--write",action="store_true"); parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    if args.write and args.check: raise SystemExit("choose only one of --write or --check")
    target=repo/"schema/premium_interpretation_database_v1.json"; data=encoded(build_database(repo))
    if args.write: target.write_bytes(data); return 0
    if args.check:
        if not target.exists() or target.read_bytes()!=data:
            print("premium_interpretation_database_v1.json is out of date",file=sys.stderr); return 1
        return 0
    sys.stdout.buffer.write(data); return 0
if __name__=="__main__": sys.exit(main())
