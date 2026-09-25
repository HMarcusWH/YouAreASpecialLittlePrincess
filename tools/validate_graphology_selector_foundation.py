#!/usr/bin/env python3
"""Validate selectors, observations, feature roles and candidate contracts against frozen research."""
from __future__ import annotations
from pathlib import Path
import json, sys
TOOLS=Path(__file__).resolve().parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from graphology_db_common import DOMAINS, load, concat, verify_research_baseline

OBS_CLASSES={"DECLARED_METADATA","PRECOMPUTED_DESCRIPTION","AI_VISUAL_DESCRIPTION_NOT_CANONICAL_MEASUREMENT"}
DESCRIPTIVE_DOMAINS={"CONTEXT","GLOBAL","SPACE","SIZE","DIRECTION","CONNECTION","FORM","STROKE","MOVEMENT","DETAIL","SIGNATURE","HIERARCHY"}
def observation_question(q): return q["domain_id"] in DESCRIPTIVE_DOMAINS and (q["permitted_evidence_class"] in OBS_CLASSES or bool(q["related_canonical_feature_ids"]))
def mapping_role(q,fid):
    if q["selection_domain"]=="DYNAMIC": return "CANDIDATE_INPUT"
    if q["answer_owner"]=="PREMIUM_VISUAL": return "AUXILIARY_CONTEXT"
    if fid.endswith("_CV") or fid.endswith("_STD"): return "VARIABILITY_CONTEXT"
    if fid.endswith("_FRACTION"): return "DISTRIBUTION_CONTEXT"
    return "PRIMARY_VALUE"
def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=list(verify_research_baseline(repo))
    rm=load(repo/"research/graphology/foundations-v0.1/blueprint/metadata.json"); rq=concat(repo/"research/graphology/foundations-v0.1/blueprint","questions")
    selectors=concat(root,"selectors"); obs=concat(root,"ontology/observations"); maps=concat(root,"ontology/feature_mappings")
    values=load(root/"values/value_sets.json"); answer=load(root/"values/answer_states.json"); selection=load(root/"values/selection_contract.json")
    envelope=load(root/"ontology/observation_envelope.json"); policy=load(root/"ontology/observation_policy.json")
    cand_defs=load(root/"candidates/candidate_definitions.json")["records"]; cand_policy=load(root/"candidates/candidate_validation_policy.json")
    cand_env=load(root/"candidates/candidate_envelope.json"); gens=load(root/"candidates/generator_contracts.json")["records"]; genmap=load(root/"candidates/selector_generator_map.json")["records"]
    feature_ids={x["id"] for x in load(repo/"schema/graphology_feature_database_v1.json")["features"]}
    q_by_sel={q["selector_id"]:q for q in rq}; sel_by_id={s["selector_id"]:s for s in selectors}
    if set(q_by_sel)!=set(sel_by_id): errors.append("selector IDs differ from frozen research")
    core=["source_question_id","domain_id","scope","answer_owner","model_call_role","selection_domain","cardinality","value_set_id","candidate_kind","required_inputs","answer_state_policy","numeric_threshold_policy","permitted_evidence_class","source_refs","feature_mapping_relation","report_target","source_status"]
    for sid,s in sel_by_id.items():
        q=q_by_sel[sid]
        expected={k:(q["question_id"] if k=="source_question_id" else q["status"] if k=="source_status" else q[k]) for k in core}
        if any(s.get(k)!=v for k,v in expected.items()): errors.append(f"selector drift: {sid}")
        if s.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"selector guardrail drift: {sid}")
        if s["runtime_status"]!="DRAFT_NOT_ACTIVE": errors.append(f"selector activated: {sid}")
    research_values=load(repo/"research/graphology/foundations-v0.1/blueprint/value_sets.json")
    if [{k:v for k,v in x.items() if k not in {"production_status","runtime_activation"}} for x in values]!=research_values: errors.append("value-set promotion drift")
    if {k:v for k,v in answer.items() if k not in {"version","production_status","runtime_activation"}}!=rm["answer_state_policy"]: errors.append("answer-state policy drift")
    if {k:v for k,v in selection.items() if k not in {"version","production_status","runtime_activation"}}!=rm["selection_contract"]: errors.append("selection contract drift")
    if {k:v for k,v in envelope.items() if k not in {"version","production_status","runtime_activation"}}!=rm["observation_envelope"]: errors.append("observation envelope drift")
    if {k:v for k,v in cand_policy.items() if k not in {"policy_id","version","production_status","runtime_activation"}}!=rm["candidate_validation_policy"]: errors.append("candidate validation policy drift")

    expected_obs={q["question_id"] for q in rq if observation_question(q)}; actual_obs={o["source_question_id"] for o in obs}
    if actual_obs!=expected_obs: errors.append("observation boundary differs from evidence policy")
    obs_by_q={o["source_question_id"]:o for o in obs}
    for qid in expected_obs:
        q=next(x for x in rq if x["question_id"]==qid); o=obs_by_q[qid]
        if o.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"observation guardrail drift: {qid}")
        if o["runtime_status"]!="DRAFT_NOT_ACTIVE": errors.append(f"observation activated: {qid}")
    expected_map={(q["selector_id"],fid):mapping_role(q,fid) for q in rq for fid in q["related_canonical_feature_ids"]}
    actual_map={(m["selector_id"],m["canonical_feature_id"]):m for m in maps}
    if set(actual_map)!=set(expected_map): errors.append("feature mapping coverage differs from frozen research")
    for key,role in expected_map.items():
        m=actual_map.get(key)
        if not m: continue
        q=q_by_sel[key[0]]
        if m["canonical_feature_id"] not in feature_ids: errors.append(f"unknown canonical feature: {m['canonical_feature_id']}")
        if m["relationship"]!="SUPPORTING_NOT_AUTOMATIC_SEMANTIC_EQUIVALENCE": errors.append(f"unsafe semantic mapping: {m['mapping_id']}")
        if m["mapping_role"]!=role: errors.append(f"feature role mismatch: {m['mapping_id']}")
        expected_obs_id=obs_by_q[q["question_id"]]["observation_id"] if q["question_id"] in obs_by_q else None
        if m["observation_id"]!=expected_obs_id: errors.append(f"mapping observation mismatch: {m['mapping_id']}")
        if m.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"mapping guardrail drift: {m['mapping_id']}")
    if any(m["mapping_role"]=="PRIMARY_VALUE" and q_by_sel[m["selector_id"]]["answer_owner"]!="DETERMINISTIC" for m in maps): errors.append("non-deterministic mapping marked PRIMARY_VALUE")

    if len(cand_defs)!=33 or {x["candidate_kind_id"] for x in cand_defs}!=set(rm["candidate_kinds"]): errors.append("candidate kind registry drift")
    if any(x["generator_status"]!="CONTRACT_ONLY_NOT_IMPLEMENTED" or x["runtime_status"]!="DRAFT_NOT_ACTIVE" for x in cand_defs): errors.append("candidate definition implementation/activation state invalid")
    gen_by_kind={g["candidate_kind_id"]:g for g in gens}
    if set(gen_by_kind)!=set(rm["candidate_kinds"]): errors.append("candidate generator contract coverage incomplete")
    dyn=[s for s in selectors if s["selection_domain"]=="DYNAMIC"]; map_by_sel={x["selector_id"]:x for x in genmap}
    if set(map_by_sel)!={s["selector_id"] for s in dyn}: errors.append("dynamic selector generator mapping incomplete")
    for s in dyn:
        gm=map_by_sel.get(s["selector_id"])
        if not gm: continue
        g=gen_by_kind.get(s["candidate_kind"])
        if not g or gm["generator_id"]!=g["generator_id"] or gm["candidate_kind_id"]!=s["candidate_kind"]: errors.append(f"generator mapping mismatch: {s['selector_id']}")
    if any(g["implementation_status"]!="CONTRACT_ONLY_NOT_IMPLEMENTED" or g["runtime_activation"] for g in gens): errors.append("candidate generator falsely implemented/active")
    if cand_env["envelope_id"]!="CANDIDATE_ENVELOPE_V1" or cand_env["runtime_activation"]: errors.append("candidate envelope invalid")
    manifest=load(root/"manifest.json")
    if manifest["counts"].get("observations")!=len(obs): errors.append("manifest observation count mismatch")
    return errors
def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo); print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
