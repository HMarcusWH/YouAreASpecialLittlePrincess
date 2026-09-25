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

def observation_question(q):
    return q["domain_id"] in DESCRIPTIVE_DOMAINS and (q["permitted_evidence_class"] in OBS_CLASSES or bool(q["related_canonical_feature_ids"]))

def mapping_role(q,fid):
    if q["selection_domain"]=="DYNAMIC": return "CANDIDATE_INPUT"
    if q["answer_owner"]=="PREMIUM_VISUAL": return "AUXILIARY_CONTEXT"
    if fid.endswith("_CV") or fid.endswith("_STD"): return "VARIABILITY_CONTEXT"
    if fid.endswith("_FRACTION"): return "DISTRIBUTION_CONTEXT"
    return "PRIMARY_VALUE"

def unique(values):
    values=list(values)
    return len(values)==len(set(values))

def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=list(verify_research_baseline(repo))
    rm=load(repo/"research/graphology/foundations-v0.1/blueprint/metadata.json")
    rq=concat(repo/"research/graphology/foundations-v0.1/blueprint","questions")
    selectors=concat(root,"selectors"); obs=concat(root,"ontology/observations"); maps=concat(root,"ontology/feature_mappings")
    values=load(root/"values/value_sets.json"); answer=load(root/"values/answer_states.json"); selection=load(root/"values/selection_contract.json")
    envelope=load(root/"ontology/observation_envelope.json"); policy=load(root/"ontology/observation_policy.json")
    cand_defs=load(root/"candidates/candidate_definitions.json")["records"]
    cand_policy=load(root/"candidates/candidate_validation_policy.json")
    cand_env=load(root/"candidates/candidate_envelope.json")
    gens=load(root/"candidates/generator_contracts.json")["records"]
    genmap=load(root/"candidates/selector_generator_map.json")["records"]
    feature_ids={x["id"] for x in load(repo/"schema/graphology_feature_database_v1.json")["features"]}

    q_by_sel={q["selector_id"]:q for q in rq}; sel_by_id={s["selector_id"]:s for s in selectors}
    if set(q_by_sel)!=set(sel_by_id): errors.append("selector IDs differ from frozen research")
    core=["source_question_id","domain_id","scope","answer_owner","model_call_role","selection_domain","cardinality","value_set_id","candidate_kind","required_inputs","answer_state_policy","numeric_threshold_policy","permitted_evidence_class","source_refs","feature_mapping_relation","report_target","source_status"]
    for sid,s in sel_by_id.items():
        q=q_by_sel[sid]
        expected={k:(q["question_id"] if k=="source_question_id" else q["status"] if k=="source_status" else q[k]) for k in core}
        if any(s.get(k)!=v for k,v in expected.items()): errors.append(f"selector drift: {sid}")
        if s.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"selector guardrail drift: {sid}")
        if s.get("runtime_status")!="DRAFT_NOT_ACTIVE": errors.append(f"selector activated: {sid}")

    research_values=load(repo/"research/graphology/foundations-v0.1/blueprint/value_sets.json")
    if [{k:v for k,v in x.items() if k not in {"production_status","runtime_activation"}} for x in values]!=research_values:
        errors.append("value-set promotion drift")
    if any(x.get("production_status")!="DRAFT_NOT_ACTIVE" or x.get("runtime_activation") is not False for x in values):
        errors.append("value-set lifecycle state invalid")

    if {k:v for k,v in answer.items() if k not in {"version","production_status","runtime_activation"}}!=rm["answer_state_policy"]:
        errors.append("answer-state policy drift")
    if answer.get("production_status")!="DRAFT_NOT_ACTIVE" or answer.get("runtime_activation") is not False:
        errors.append("answer-state lifecycle state invalid")

    if {k:v for k,v in selection.items() if k not in {"version","production_status","runtime_activation"}}!=rm["selection_contract"]:
        errors.append("selection contract drift")
    if selection.get("production_status")!="DRAFT_NOT_ACTIVE" or selection.get("runtime_activation") is not False:
        errors.append("selection-contract lifecycle state invalid")

    if {k:v for k,v in envelope.items() if k not in {"version","production_status","runtime_activation"}}!=rm["observation_envelope"]:
        errors.append("observation envelope drift")
    if envelope.get("production_status")!="DRAFT_NOT_ACTIVE" or envelope.get("runtime_activation") is not False:
        errors.append("observation-envelope lifecycle state invalid")
    if policy.get("runtime_activation") is not False:
        errors.append("observation policy became active")
    if set(policy.get("mapping_roles",{}))!={"PRIMARY_VALUE","VARIABILITY_CONTEXT","DISTRIBUTION_CONTEXT","CANDIDATE_INPUT","AUXILIARY_CONTEXT"}:
        errors.append("observation mapping-role contract drift")

    if {k:v for k,v in cand_policy.items() if k not in {"policy_id","version","production_status","runtime_activation"}}!=rm["candidate_validation_policy"]:
        errors.append("candidate validation policy drift")
    if cand_policy.get("production_status")!="DRAFT_NOT_ACTIVE" or cand_policy.get("runtime_activation") is not False:
        errors.append("candidate-policy lifecycle state invalid")

    expected_obs={q["question_id"] for q in rq if observation_question(q)}; actual_obs={o["source_question_id"] for o in obs}
    if actual_obs!=expected_obs: errors.append("observation boundary differs from evidence policy")
    obs_by_q={o["source_question_id"]:o for o in obs}
    for qid in expected_obs:
        q=next(x for x in rq if x["question_id"]==qid); o=obs_by_q[qid]
        if o.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"observation guardrail drift: {qid}")
        if o.get("runtime_status")!="DRAFT_NOT_ACTIVE": errors.append(f"observation activated: {qid}")

    expected_map={(q["selector_id"],fid):mapping_role(q,fid) for q in rq for fid in q["related_canonical_feature_ids"]}
    if not unique((m["mapping_id"] for m in maps)): errors.append("duplicate feature mapping ID")
    actual_map={(m["selector_id"],m["canonical_feature_id"]):m for m in maps}
    if len(actual_map)!=len(maps): errors.append("duplicate selector/feature mapping")
    if set(actual_map)!=set(expected_map): errors.append("feature mapping coverage differs from frozen research")
    for key,role in expected_map.items():
        m=actual_map.get(key)
        if not m: continue
        q=q_by_sel[key[0]]
        if m["canonical_feature_id"] not in feature_ids: errors.append(f"unknown canonical feature: {m['canonical_feature_id']}")
        if m.get("relationship")!="SUPPORTING_NOT_AUTOMATIC_SEMANTIC_EQUIVALENCE": errors.append(f"unsafe semantic mapping: {m['mapping_id']}")
        if m.get("mapping_role")!=role: errors.append(f"feature role mismatch: {m['mapping_id']}")
        expected_obs_id=obs_by_q[q["question_id"]]["observation_id"] if q["question_id"] in obs_by_q else None
        if m.get("observation_id")!=expected_obs_id: errors.append(f"mapping observation mismatch: {m['mapping_id']}")
        if m.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"mapping guardrail drift: {m['mapping_id']}")
        if m.get("mapping_status")!="DRAFT_SUPPORT_ONLY" or m.get("runtime_activation") is not False:
            errors.append(f"feature mapping lifecycle invalid: {m['mapping_id']}")
    if any(m["mapping_role"]=="PRIMARY_VALUE" and q_by_sel[m["selector_id"]]["answer_owner"]!="DETERMINISTIC" for m in maps):
        errors.append("non-deterministic mapping marked PRIMARY_VALUE")

    kind_ids=[x["candidate_kind_id"] for x in cand_defs]
    if len(cand_defs)!=33 or not unique(kind_ids) or set(kind_ids)!=set(rm["candidate_kinds"]):
        errors.append("candidate kind registry drift or duplication")
    if any(x.get("generator_status")!="CONTRACT_ONLY_NOT_IMPLEMENTED" or x.get("runtime_status")!="DRAFT_NOT_ACTIVE" for x in cand_defs):
        errors.append("candidate definition implementation/activation state invalid")

    gen_kind_ids=[g["candidate_kind_id"] for g in gens]; gen_ids=[g["generator_id"] for g in gens]
    if not unique(gen_kind_ids): errors.append("duplicate candidate generator kind contract")
    if not unique(gen_ids): errors.append("duplicate candidate generator ID")
    if len(gens)!=33 or set(gen_kind_ids)!=set(rm["candidate_kinds"]):
        errors.append("candidate generator contract coverage incomplete")
    gen_by_kind={g["candidate_kind_id"]:g for g in gens}

    dyn=[s for s in selectors if s["selection_domain"]=="DYNAMIC"]
    mapped_selectors=[x["selector_id"] for x in genmap]
    if not unique(mapped_selectors): errors.append("duplicate selector-generator mapping")
    if len(genmap)!=35 or set(mapped_selectors)!={s["selector_id"] for s in dyn}:
        errors.append("dynamic selector generator mapping incomplete")
    map_by_sel={x["selector_id"]:x for x in genmap}
    for s in dyn:
        gm=map_by_sel.get(s["selector_id"])
        if not gm: continue
        g=gen_by_kind.get(s["candidate_kind"])
        if not g or gm.get("generator_id")!=g["generator_id"] or gm.get("candidate_kind_id")!=s["candidate_kind"]:
            errors.append(f"generator mapping mismatch: {s['selector_id']}")
    if any(g.get("implementation_status")!="CONTRACT_ONLY_NOT_IMPLEMENTED" or g.get("runtime_activation") is not False for g in gens):
        errors.append("candidate generator falsely implemented/active")
    if any(g.get("output_envelope_id")!="CANDIDATE_ENVELOPE_V1" or g.get("eligibility_policy_id")!="CANDIDATE_VALIDATION_V1" for g in gens):
        errors.append("candidate generator contract linkage invalid")

    ref_gen=gen_by_kind.get("ELIGIBLE_REFERENCE_CLAIM")
    required_ref_inputs={"VALID_REFERENCE_RELEASE","REFERENCE_SERVICE_ELIGIBILITY_RESULTS"}
    if not ref_gen or not required_ref_inputs <= set(ref_gen.get("required_inputs",[])):
        errors.append("eligible reference claim generator lacks authoritative reference-service inputs")
    elif ref_gen.get("missing_input_behavior")!="NO_CANDIDATE" or ref_gen.get("authoritative_fact_linkage")!="source_fact_ids":
        errors.append("eligible reference claim generator missing-input/fact-linkage contract invalid")

    if cand_env.get("envelope_id")!="CANDIDATE_ENVELOPE_V1" or cand_env.get("runtime_activation") is not False:
        errors.append("candidate envelope invalid")
    manifest=load(root/"manifest.json")
    if manifest["counts"].get("observations")!=len(obs): errors.append("manifest observation count mismatch")
    return errors

def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo)
    print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
