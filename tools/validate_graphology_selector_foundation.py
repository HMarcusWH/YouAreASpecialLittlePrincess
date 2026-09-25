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
    gens_doc=load(root/"candidates/generator_contracts.json"); gens=gens_doc["records"]
    genmap_doc=load(root/"candidates/selector_generator_map.json"); genmap=genmap_doc["records"]
    feature_ids={x["id"] for x in load(repo/"schema/graphology_feature_database_v1.json")["features"]}

    research_selector_ids=[q["selector_id"] for q in rq]
    selector_ids=[x["selector_id"] for x in selectors]
    if len(selectors)!=89 or not unique(selector_ids):
        errors.append("selector definition count/uniqueness invalid")
    if not unique(research_selector_ids):
        errors.append("frozen research contains duplicate selector IDs")
    q_by_sel={q["selector_id"]:q for q in rq}; sel_by_id={x["selector_id"]:x for x in selectors}
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
    expected_observation_policy={
        "version":"graphology-observation-policy/1","runtime_activation":False,
        "descriptive_domains":["CONTEXT","GLOBAL","SPACE","SIZE","DIRECTION","CONNECTION","FORM","STROKE","MOVEMENT","DETAIL","SIGNATURE","HIERARCHY"],
        "direct_observation_evidence_classes":["DECLARED_METADATA","PRECOMPUTED_DESCRIPTION","AI_VISUAL_DESCRIPTION_NOT_CANONICAL_MEASUREMENT"],
        "include_rule":"A question gets an observation record when it is in a descriptive domain and either has a direct observation evidence class or references canonical handwriting features.",
        "excluded_domains":["INTERPRETATION","REFERENCE","PAIR","HISTORY"],
        "mapping_roles":{
            "PRIMARY_VALUE":"May directly supply a deterministic selector value when that selector's reviewed rubric exists.",
            "VARIABILITY_CONTEXT":"Qualifies heterogeneity/dispersion; must not determine a magnitude band.",
            "DISTRIBUTION_CONTEXT":"Qualifies distribution/composition; must not replace the primary value.",
            "CANDIDATE_INPUT":"Supplies facts to a dynamic candidate generator; does not directly determine a selector value.",
            "AUXILIARY_CONTEXT":"Provides contextual evidence only; does not directly determine a selector value.",
        },
        "safety_rules":[
            "Fixed versus dynamic selector origin never decides whether an observation exists.",
            "Only PRIMARY_VALUE may directly determine a deterministic selector band.",
            "Missing observation evidence never becomes zero or an opposite trait.",
        ],
    }
    if policy!=expected_observation_policy:
        errors.append("observation policy contract drift")

    if {k:v for k,v in cand_policy.items() if k not in {"policy_id","version","production_status","runtime_activation"}}!=rm["candidate_validation_policy"]:
        errors.append("candidate validation policy drift")
    if cand_policy.get("production_status")!="DRAFT_NOT_ACTIVE" or cand_policy.get("runtime_activation") is not False:
        errors.append("candidate-policy lifecycle state invalid")

    expected_obs={q["question_id"] for q in rq if observation_question(q)}
    observation_ids=[o["observation_id"] for o in obs]; observation_questions=[o["source_question_id"] for o in obs]
    if len(obs)!=len(expected_obs) or not unique(observation_ids) or not unique(observation_questions):
        errors.append("observation definition count/uniqueness invalid")
    actual_obs=set(observation_questions)
    if actual_obs!=expected_obs: errors.append("observation boundary differs from evidence policy")
    obs_by_q={o["source_question_id"]:o for o in obs}
    for qid in expected_obs:
        q=next(x for x in rq if x["question_id"]==qid); o=obs_by_q[qid]
        descriptor_kind=(
            "DECLARED_CONTEXT" if q["answer_owner"]=="USER_OR_REVIEWER"
            else "DETERMINISTIC_DESCRIPTOR" if q["answer_owner"]=="DETERMINISTIC"
            else "VISUAL_DESCRIPTOR" if q["answer_owner"]=="PREMIUM_VISUAL"
            else "CANDIDATE_BACKED_DESCRIPTOR"
        )
        expected_record={
            "observation_id":f"OBS_{q['selector_id'].removeprefix('SEL_')}","source_question_id":q["question_id"],
            "selector_id":q["selector_id"],"domain_id":q["domain_id"],"scope":q["scope"],"descriptor_kind":descriptor_kind,
            "assessment_owner":q["answer_owner"],"model_call_role":q["model_call_role"],"cardinality":q["cardinality"],
            "value_set_id":q["value_set_id"],"candidate_kind":q["candidate_kind"],"required_inputs":q["required_inputs"],
            "answer_state_policy":q["answer_state_policy"],"permitted_evidence_class":q["permitted_evidence_class"],
            "source_refs":q["source_refs"],"related_canonical_feature_ids":q["related_canonical_feature_ids"],
            "feature_mapping_relation":q["feature_mapping_relation"],"operational_guardrail":q.get("note") or "",
            "source_status":q["status"],"runtime_status":"DRAFT_NOT_ACTIVE",
        }
        if o!=expected_record: errors.append(f"observation record drift: {qid}")

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
        if m.get("mapping_id")!=f"MAP_{q['selector_id']}_{m['canonical_feature_id']}" or m.get("source_question_id")!=q["question_id"]:
            errors.append(f"feature mapping identity drift: {m['mapping_id']}")
        if m.get("relationship")!="SUPPORTING_NOT_AUTOMATIC_SEMANTIC_EQUIVALENCE": errors.append(f"unsafe semantic mapping: {m['mapping_id']}")
        if m.get("mapping_role")!=role: errors.append(f"feature role mismatch: {m['mapping_id']}")
        expected_obs_id=obs_by_q[q["question_id"]]["observation_id"] if q["question_id"] in obs_by_q else None
        if m.get("observation_id")!=expected_obs_id: errors.append(f"mapping observation mismatch: {m['mapping_id']}")
        if m.get("operational_guardrail","")!=(q.get("note") or ""): errors.append(f"mapping guardrail drift: {m['mapping_id']}")
        if m.get("mapping_status")!="DRAFT_SUPPORT_ONLY" or m.get("runtime_activation") is not False:
            errors.append(f"feature mapping lifecycle invalid: {m['mapping_id']}")
    if any(m["mapping_role"]=="PRIMARY_VALUE" and q_by_sel[m["selector_id"]]["answer_owner"]!="DETERMINISTIC" for m in maps):
        errors.append("non-deterministic mapping marked PRIMARY_VALUE")

    cand_doc=load(root/"candidates/candidate_definitions.json")
    if cand_doc.get("version")!="graphology-candidate-kinds/1" or cand_doc.get("status")!="REGISTERED_NAMES_ONLY":
        errors.append("candidate definition registry metadata drift")
    kind_ids=[x["candidate_kind_id"] for x in cand_defs]
    if len(cand_defs)!=33 or not unique(kind_ids) or set(kind_ids)!=set(rm["candidate_kinds"]):
        errors.append("candidate kind registry drift or duplication")
    if any(x.get("generator_status")!="CONTRACT_ONLY_NOT_IMPLEMENTED" or x.get("runtime_status")!="DRAFT_NOT_ACTIVE" for x in cand_defs):
        errors.append("candidate definition implementation/activation state invalid")

    if gens_doc.get("version")!="graphology-candidate-generator-contracts/1" or gens_doc.get("runtime_activation") is not False:
        errors.append("candidate generator registry metadata/lifecycle drift")
    gen_kind_ids=[g["candidate_kind_id"] for g in gens]; gen_ids=[g["generator_id"] for g in gens]
    if not unique(gen_kind_ids): errors.append("duplicate candidate generator kind contract")
    if not unique(gen_ids): errors.append("duplicate candidate generator ID")
    if len(gens)!=33 or set(gen_kind_ids)!=set(rm["candidate_kinds"]):
        errors.append("candidate generator contract coverage incomplete")
    gen_by_kind={g["candidate_kind_id"]:g for g in gens}

    dyn=[x for x in selectors if x["selection_domain"]=="DYNAMIC"]
    if genmap_doc.get("version")!="graphology-selector-generator-map/1" or genmap_doc.get("runtime_activation") is not False:
        errors.append("selector-generator registry metadata/lifecycle drift")
    if any(x.get("runtime_activation") is not False for x in genmap):
        errors.append("selector-generator mapping became active")
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
    for d in cand_defs:
        g=gen_by_kind.get(d["candidate_kind_id"])
        if not g:
            errors.append(f"candidate definition generator missing: {d['candidate_kind_id']}")
            continue
        if d.get("generator_id")!=g.get("generator_id"):
            errors.append(f"candidate definition generator mismatch: {d['candidate_kind_id']}")
        if d.get("generator_contract_status")!="CONTRACT_ONLY_NOT_IMPLEMENTED":
            errors.append(f"candidate definition generator contract status invalid: {d['candidate_kind_id']}")
    if any(g.get("output_envelope_id")!="CANDIDATE_ENVELOPE_V1" or g.get("eligibility_policy_id")!="CANDIDATE_VALIDATION_V1" for g in gens):
        errors.append("candidate generator contract linkage invalid")
    def expected_source_mode(owners):
        owners=set(owners)
        if owners and owners=={"DETERMINISTIC"}: return "PRECOMPUTED_APPLICATION"
        if owners and owners=={"RULE_ENGINE"}: return "RULE_ENGINE"
        if "PREMIUM_VISUAL" in owners: return "VISUAL_ASSESSMENT_DEPENDENT"
        if "PREMIUM_EDITOR" in owners: return "EDITORIAL_SELECTION_DEPENDENT"
        return "MIXED_DEFERRED"
    for kind,g in gen_by_kind.items():
        linked=[x for x in selectors if x["candidate_kind"]==kind]
        owners={x["answer_owner"] for x in linked}
        if g.get("generator_version")!="1.0.0":
            errors.append(f"candidate generator version drift: {kind}")
        if g.get("selector_ids")!=[x["selector_id"] for x in linked]:
            errors.append(f"candidate generator selector coverage drift: {kind}")
        if set(g.get("scopes",[]))!={x["scope"] for x in linked}:
            errors.append(f"candidate generator scope drift: {kind}")
        if set(g.get("answer_owners",[]))!=owners:
            errors.append(f"candidate generator owner drift: {kind}")
        if g.get("source_mode")!=expected_source_mode(owners):
            errors.append(f"candidate generator source-mode drift: {kind}")
        required_from_selectors=set().union(*(set(x.get("required_inputs",[])) for x in linked)) if linked else set()
        expected_required=set(required_from_selectors)
        if kind=="ELIGIBLE_REFERENCE_CLAIM":
            expected_required|={"VALID_REFERENCE_RELEASE","REFERENCE_SERVICE_ELIGIBILITY_RESULTS"}
        if set(g.get("required_inputs",[]))!=expected_required:
            errors.append(f"candidate generator required-input drift: {kind}")

    ref_gen=gen_by_kind.get("ELIGIBLE_REFERENCE_CLAIM")
    required_ref_inputs={"VALID_REFERENCE_RELEASE","REFERENCE_SERVICE_ELIGIBILITY_RESULTS"}
    if not ref_gen or not required_ref_inputs <= set(ref_gen.get("required_inputs",[])):
        errors.append("eligible reference claim generator lacks authoritative reference-service inputs")
    elif ref_gen.get("missing_input_behavior")!="NO_CANDIDATE" or ref_gen.get("authoritative_fact_linkage")!="source_fact_ids":
        errors.append("eligible reference claim generator missing-input/fact-linkage contract invalid")

    expected_candidate_fields=[
        "candidate_id","candidate_kind_id","generator_id","generator_version","eligibility_state",
        "source_fact_ids","source_observation_ids","source_association_ids","display_key","payload",
    ]
    expected_candidate_invariants=[
        "eligibility_state must be a CANDIDATE_VALIDATION_V1 state.",
        "PENDING_VISUAL_ASSESSMENT is never described as preverified.",
        "No candidate payload creates a canonical measurement, percentile, probability or score unless supplied by an authoritative precomputed fact.",
    ]
    if (
        cand_env.get("envelope_id")!="CANDIDATE_ENVELOPE_V1"
        or cand_env.get("version")!="1.0.0"
        or cand_env.get("runtime_activation") is not False
        or cand_env.get("required_fields")!=expected_candidate_fields
        or cand_env.get("invariants")!=expected_candidate_invariants
    ):
        errors.append("candidate envelope invalid")
    pr2_trace=load(root/"traceability/pr2_values_candidates_policies.json")["records"]
    expected_pr2={
        *{("VALUE_SET",x["value_set_id"],"VALUE_SET",x["value_set_id"]) for x in research_values},
        *{("CANDIDATE_KIND",x,"CANDIDATE_KIND",x) for x in rm["candidate_kinds"]},
        ("ANSWER_STATE_POLICY",rm["answer_state_policy"]["policy_id"],"ANSWER_STATE_POLICY",rm["answer_state_policy"]["policy_id"]),
        ("SELECTION_CONTRACT","selection_contract","SELECTION_CONTRACT","graphology-selection-contract/1"),
        ("OBSERVATION_ENVELOPE","observation_envelope","OBSERVATION_ENVELOPE","graphology-observation-envelope/1"),
        ("CANDIDATE_VALIDATION_POLICY","candidate_validation_policy","CANDIDATE_VALIDATION_POLICY","CANDIDATE_VALIDATION_V1"),
    }
    actual_pr2=[(x["research_kind"],x["research_id"],x["production_kind"],x["production_id"]) for x in pr2_trace]
    if len(actual_pr2)!=len(set(actual_pr2)) or set(actual_pr2)!=expected_pr2:
        errors.append("PR2 static traceability drift")

    selector_trace=concat(root,"traceability/selectors")
    expected_selector_trace={("QUESTION",q["question_id"],"SELECTOR",q["selector_id"]) for q in rq}
    actual_selector_trace=[(x["research_kind"],x["research_id"],x["production_kind"],x["production_id"]) for x in selector_trace]
    if len(actual_selector_trace)!=len(set(actual_selector_trace)) or set(actual_selector_trace)!=expected_selector_trace:
        errors.append("question-to-selector traceability drift")

    manifest=load(root/"manifest.json")
    if manifest["counts"].get("observations")!=len(obs): errors.append("manifest observation count mismatch")
    return errors

def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo)
    print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
