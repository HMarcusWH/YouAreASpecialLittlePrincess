#!/usr/bin/env python3
"""Validate that traditional graphology structures remain sourced and non-executable."""
from __future__ import annotations
from pathlib import Path
import json, sys
TOOLS=Path(__file__).resolve().parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from graphology_db_common import DOMAINS, load, concat, verify_research_baseline

def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=list(verify_research_baseline(repo))
    research=load(repo/"research/graphology/foundations-v0.1/blueprint/metadata.json")
    claims={x["assertion_id"]:x for x in load(root/"ontology/source_claims.json")}
    policies=load(root/"traditional/method_policies.json")["records"]; associations=load(root/"traditional/associations/jaminian.json")
    packs=load(root/"traditional/rule_pack_registry.json")["packs"]; gates=load(root/"traditional/activation_gates.json")
    canonical=load(root/"candidates/candidate_validation_policy.json")
    old=load(root/"traditional/candidate_validation_policy.json")
    if {k:v for k,v in canonical.items() if k not in {"policy_id","version","production_status","runtime_activation"}}!=research["candidate_validation_policy"]: errors.append("canonical candidate policy drift")
    if {k:v for k,v in old.items() if k not in {"version","production_status","runtime_activation"}}!=research["candidate_validation_policy"]: errors.append("traditional candidate policy compatibility copy drift")
    if len(policies)!=4 or any(x["runtime_status"]!="DRAFT_NOT_ACTIVE" for x in policies): errors.append("traditional method policy state invalid")
    historical={k:v for k,v in claims.items() if v["claim_kind"]=="HISTORICAL_INTERPRETIVE_ASSOCIATION"}
    if len(associations)!=2 or len(historical)!=2: errors.append("historical association stub count changed")
    for a in associations:
        c=historical.get(a["source_assertion_id"])
        if not c: errors.append(f"association source assertion missing: {a['association_id']}"); continue
        if a["paraphrase"]!=c["paraphrase"] or a["remaining_gaps"]!=c["remaining_gaps"]: errors.append(f"association source drift: {a['association_id']}")
        if any(a[x] for x in ["premise_concepts","all_of","any_of","modifiers","counter_signs","exclusions"]): errors.append(f"executable rule content invented: {a['association_id']}")
        if a["runtime_eligibility"]!="BLOCKED_RESEARCH_ONLY" or a["eligible_for_rule_engine"] or a["eligible_for_model_candidate"]: errors.append(f"association activated: {a['association_id']}")
    if len(packs)!=5 or any(p["runtime_activation"] or p["runtime_eligible_association_ids"] for p in packs): errors.append("traditional rule pack activated")
    if gates["runtime_activation"] or gates["general_release_gates"]!=research["release_gates"]: errors.append("traditional activation gates invalid")
    return errors
def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo); print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
