#!/usr/bin/env python3
"""Validate that traditional graphology structures remain sourced, constrained and non-executable."""
from __future__ import annotations
from pathlib import Path
import json, sys
TOOLS=Path(__file__).resolve().parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from graphology_db_common import load, verify_research_baseline

def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"; errors=list(verify_research_baseline(repo))
    research=load(repo/"research/graphology/foundations-v0.1/blueprint/metadata.json")
    sources={x["source_id"] for x in load(root/"ontology/sources.json")}
    claims={x["assertion_id"]:x for x in load(root/"ontology/source_claims.json")}
    schools={x["school_id"] for x in load(root/"ontology/schools.json") if x["school_kind"]=="GRAPHOLOGY_TRADITION_PROFILE"}
    value_sets={x["value_set_id"]:x for x in load(root/"values/value_sets.json")}
    policies=load(root/"traditional/method_policies.json")["records"]
    associations=load(root/"traditional/associations/jaminian.json")
    packs=load(root/"traditional/rule_pack_registry.json")["packs"]
    gates=load(root/"traditional/activation_gates.json")
    canonical=load(root/"candidates/candidate_validation_policy.json")
    compat=load(root/"traditional/candidate_validation_policy.json")
    association_contract=load(root/"traditional/association_contract.json")

    stripped_association_contract={k:v for k,v in association_contract.items() if k not in {"version","production_status","runtime_activation"}}
    if stripped_association_contract!=research["school_association_contract"]:
        errors.append("school association contract drift")
    if association_contract.get("version")!="graphology-school-association-contract/1":
        errors.append("school association contract version drift")
    if association_contract.get("production_status")!="STRUCTURE_ONLY" or association_contract.get("runtime_activation") is not False:
        errors.append("school association contract lifecycle invalid")

    if {k:v for k,v in canonical.items() if k not in {"policy_id","version","production_status","runtime_activation"}}!=research["candidate_validation_policy"]:
        errors.append("canonical candidate policy drift")
    if canonical.get("policy_id")!="CANDIDATE_VALIDATION_V1" or canonical.get("version")!="graphology-candidate-validation/1":
        errors.append("canonical candidate policy identity drift")
    if canonical.get("production_status")!="DRAFT_NOT_ACTIVE" or canonical.get("runtime_activation") is not False:
        errors.append("canonical candidate policy lifecycle invalid")
    if {k:v for k,v in compat.items() if k not in {"version","production_status","runtime_activation"}}!=research["candidate_validation_policy"]:
        errors.append("traditional candidate policy compatibility copy drift")
    if compat.get("version")!="graphology-traditional-candidate-validation/1":
        errors.append("traditional candidate policy compatibility version drift")
    if compat.get("production_status")!="STRUCTURE_ONLY" or compat.get("runtime_activation") is not False:
        errors.append("traditional candidate policy compatibility lifecycle invalid")

    if len(policies)!=4 or any(x.get("runtime_status")!="DRAFT_NOT_ACTIVE" for x in policies):
        errors.append("traditional method policy state invalid")
    p={x["policy_id"]:x for x in policies}
    expected_ids={"POLICY_CJ_CONTEXTUAL_SYNTHESIS_V1","POLICY_CJ_ABSENCE_GUARD_V1","POLICY_BIG_CORROBORATION_V1","POLICY_MORETTI_TYPED_RELATIONS_V1"}
    if set(p)!=expected_ids: errors.append("traditional method policy IDs changed")

    cj=p.get("POLICY_CJ_CONTEXTUAL_SYNTHESIS_V1",{}).get("constraints",{})
    if cj.get("preserve_alternative_readings") is not True or cj.get("evaluate_modifiers_and_counterevidence") is not True:
        errors.append("Jamin contextual synthesis safeguards weakened")
    if cj.get("allow_arbitrary_trait_weights") is not False or cj.get("isolated_sign_is_sufficient") is not False:
        errors.append("Jamin contextual synthesis permits unsupported inference")

    absence=p.get("POLICY_CJ_ABSENCE_GUARD_V1",{}).get("constraints",{})
    if any(absence.get(k) is not False for k in ["absent_positive_sign_activates_opposite","not_assessable_activates_opposite","not_applicable_activates_opposite"]):
        errors.append("Jamin absence guard permits inverse inference")
    if absence.get("explicit_opposing_evidence_required_for_opposite") is not True:
        errors.append("Jamin absence guard no longer requires opposing evidence")

    bigp=p.get("POLICY_BIG_CORROBORATION_V1",{})
    big=bigp.get("constraints",{})
    if bigp.get("application_adaptation")!=claims["METHOD_BIG_SUPPORT"].get("app_adaptation"):
        errors.append("BIG application adaptation drift")
    if big.get("minimum_distinct_support_groups")!=3 or big.get("correlated_summaries_count_once") is not True or big.get("repeated_measurements_of_same_graphic_family_count_once") is not True:
        errors.append("BIG distinct-support constraints weakened")
    if big.get("support_count_is_statistical_proof") is not False:
        errors.append("BIG support count treated as statistical proof")

    moretti=p.get("POLICY_MORETTI_TYPED_RELATIONS_V1",{})
    relation_ids={x["value_id"] for x in value_sets["SIGN_RELATION"]["values"]}
    if set(moretti.get("allowed_relation_value_ids",[]))!={"SUPPORTS","OPPOSES","NEUTRAL"}:
        errors.append("Moretti relation values drifted")
    if set(moretti.get("allowed_relation_value_ids",[]))-relation_ids:
        errors.append("Moretti relation value does not resolve")
    mc=moretti.get("constraints",{})
    if mc.get("preserve_sign_role_separately_from_within_sample_prominence") is not True:
        errors.append("Moretti sign-role separation weakened")
    if mc.get("enable_decimi_scoring") is not False or mc.get("enable_temperament_classifier") is not False:
        errors.append("Moretti blocked scoring/classifier enabled")

    expected_policy_provenance={
        "POLICY_CJ_CONTEXTUAL_SYNTHESIS_V1":{
            "school_id":"JAMINIAN","policy_kind":"CONTEXTUAL_SYNTHESIS",
            "source_assertion_ids":["METHOD_CJ_CONTEXT"],"source_refs":[{"source_id":"CJ1892","locator":"pp.35–53 and pp.89–92"}],
            "empirical_status":"NOT_ESTABLISHED_AS_PERSONALITY_VALIDITY",
        },
        "POLICY_CJ_ABSENCE_GUARD_V1":{
            "school_id":"JAMINIAN","policy_kind":"MISSINGNESS_GUARDRAIL",
            "source_assertion_ids":["METHOD_CJ_ABSENCE"],"source_refs":[{"source_id":"CJ1892","locator":"pp.51–53"}],
            "empirical_status":"LOGICAL_GUARDRAIL_NOT_VALIDATION",
        },
        "POLICY_BIG_CORROBORATION_V1":{
            "school_id":"BIG_HILLIGER","policy_kind":"CORROBORATION",
            "source_assertion_ids":["METHOD_BIG_SUPPORT"],"source_refs":[{"source_id":"BIG26","locator":"p.3 B.5"}],
            "empirical_status":"SCHOOL_REQUIREMENT_NOT_STATISTICAL_PROOF",
        },
        "POLICY_MORETTI_TYPED_RELATIONS_V1":{
            "school_id":"MORETTIAN","policy_kind":"TYPED_SIGN_RELATION",
            "source_assertion_ids":["METHOD_MORETTI_RELATIONS"],"source_refs":[{"source_id":"CARBONARI","locator":"Quale tecnica, sign relations and laws"}],
            "empirical_status":"NOT_ESTABLISHED_AS_PERSONALITY_VALIDITY",
        },
    }
    for pol in policies:
        expected=expected_policy_provenance.get(pol["policy_id"])
        if not expected:
            continue
        for key,val in expected.items():
            if pol.get(key)!=val: errors.append(f"traditional method policy provenance drift {key}: {pol['policy_id']}")
        if any(r["source_id"] not in sources for r in pol.get("source_refs",[])): errors.append(f"policy source does not resolve: {pol['policy_id']}")
        if any(i not in claims for i in pol.get("source_assertion_ids",[])): errors.append(f"policy assertion does not resolve: {pol['policy_id']}")

    historical={k:v for k,v in claims.items() if v["claim_kind"]=="HISTORICAL_INTERPRETIVE_ASSOCIATION"}
    if len(associations)!=2 or len(historical)!=2: errors.append("historical association stub count changed")
    for a in associations:
        c=historical.get(a["source_assertion_id"])
        if not c:
            errors.append(f"association source assertion missing: {a['association_id']}"); continue
        exact={
          "source_id":c["source_id"],"locator":c["locator"],"paraphrase":c["paraphrase"],
          "source_premise_examples":c.get("premise_examples",[]),"remaining_gaps":c["remaining_gaps"],
          "empirical_status":c["empirical_status"],
        }
        for key,val in exact.items():
            if a.get(key)!=val: errors.append(f"association provenance drift {key}: {a['association_id']}")
        if a.get("school_id")!="JAMINIAN": errors.append(f"association school drift: {a['association_id']}")
        if a.get("traditional_interpretation",{}).get("source_term")!=c.get("source_term"): errors.append(f"association source term drift: {a['association_id']}")
        if a.get("traditional_interpretation",{}).get("status")!="SOURCE_TERM_ONLY_NO_MODERN_TRAIT_EXPANSION": errors.append(f"association interpretation status drift: {a['association_id']}")
        if a.get("edition")!="1892 English translation from the third French edition": errors.append(f"association edition drift: {a['association_id']}")
        if a.get("raw_source_wording_locator")!=c["locator"]: errors.append(f"association raw-source locator drift: {a['association_id']}")
        if a.get("source_fidelity")!="RESEARCH_ASSERTION_PRESERVED_WITH_RECORDED_GAPS": errors.append(f"association source-fidelity drift: {a['association_id']}")
        if a.get("premise_binding_status")!="UNOPERATIONALIZED_SOURCE_EXAMPLES": errors.append(f"association source examples operationalized: {a['association_id']}")
        expected_applicability={"status":"UNOPERATIONALIZED","note":"Full qualifying context and operational morphology remain unresolved."}
        if a.get("applicability")!=expected_applicability: errors.append(f"association applicability drift: {a['association_id']}")
        if any(a.get(x) for x in ["premise_concepts","all_of","any_of","modifiers","counter_signs","exclusions"]):
            errors.append(f"executable rule content invented: {a['association_id']}")
        if a.get("runtime_eligibility")!="BLOCKED_RESEARCH_ONLY" or a.get("eligible_for_rule_engine") or a.get("eligible_for_model_candidate"):
            errors.append(f"association activated: {a['association_id']}")

    policy_ids=set(p); association_ids={a["association_id"] for a in associations}
    if len(packs)!=5 or {x["school_id"] for x in packs}!=schools: errors.append("rule-pack school coverage changed")
    if any(set(x["method_policy_ids"])-policy_ids for x in packs): errors.append("rule-pack method policy does not resolve")
    if any(set(x["association_ids"])-association_ids for x in packs): errors.append("rule-pack association does not resolve")
    if any(x.get("runtime_activation") is not False or x.get("runtime_eligible_association_ids") for x in packs): errors.append("traditional rule pack activated")
    if any(x["association_ids"] for x in packs if x["school_id"]!="JAMINIAN"): errors.append("association invented for non-Jaminian pack")

    if gates.get("runtime_activation") is not False or gates.get("general_release_gates")!=research["release_gates"]:
        errors.append("traditional activation gates invalid")
    gate_rows=gates.get("association_gates",[])
    gate_ids=[x["association_id"] for x in gate_rows]
    if len(gate_ids)!=len(set(gate_ids)) or set(gate_ids)!=association_ids:
        errors.append("association activation gate coverage/uniqueness invalid")
    gate_by_id={x["association_id"]:x for x in gate_rows}
    for a in associations:
        g=gate_by_id.get(a["association_id"])
        if (
            not g
            or g.get("runtime_eligibility")!=a["runtime_eligibility"]
            or g.get("unresolved_requirements")!=a["remaining_gaps"]
            or g.get("may_enter_runtime_pack") is not False
        ):
            errors.append(f"association activation gate invalid: {a['association_id']}")
    if gates.get("pack_activation_rule")!="A pack remains inactive until every included association has reviewed operational premises, applicability, counterevidence behavior, source provenance, and explicit promotion evidence.":
        errors.append("traditional pack activation rule drift")

    pr3_trace=load(root/"traceability/pr3_traditional.json")["records"]
    expected_pr3={
        ("SCHOOL_ASSOCIATION_CONTRACT","school_association_contract","ASSOCIATION_CONTRACT","graphology-school-association-contract/1"),
        ("CANDIDATE_VALIDATION_POLICY","candidate_validation_policy","CANDIDATE_VALIDATION_POLICY","graphology-traditional-candidate-validation/1"),
        ("RELEASE_GATES","release_gates","ACTIVATION_GATES","graphology-traditional-activation-gates/1"),
        ("SOURCE_ASSERTION","METHOD_CJ_CONTEXT","METHOD_POLICY","POLICY_CJ_CONTEXTUAL_SYNTHESIS_V1"),
        ("SOURCE_ASSERTION","METHOD_CJ_ABSENCE","METHOD_POLICY","POLICY_CJ_ABSENCE_GUARD_V1"),
        ("SOURCE_ASSERTION","METHOD_BIG_SUPPORT","METHOD_POLICY","POLICY_BIG_CORROBORATION_V1"),
        ("SOURCE_ASSERTION","METHOD_MORETTI_RELATIONS","METHOD_POLICY","POLICY_MORETTI_TYPED_RELATIONS_V1"),
        ("SOURCE_ASSERTION","HIST_CJ_ANIMATION","TRADITIONAL_ASSOCIATION","ASSOC_HIST_CJ_ANIMATION"),
        ("SOURCE_ASSERTION","HIST_CJ_FIRMNESS","TRADITIONAL_ASSOCIATION","ASSOC_HIST_CJ_FIRMNESS"),
    }
    actual_pr3=[(x["research_kind"],x["research_id"],x["production_kind"],x["production_id"]) for x in pr3_trace]
    if len(actual_pr3)!=len(set(actual_pr3)) or set(actual_pr3)!=expected_pr3:
        errors.append("PR3 traditional traceability drift")
    return errors

def main():
    repo=Path(__file__).resolve().parents[1]; errors=validate(repo)
    print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2)); return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
