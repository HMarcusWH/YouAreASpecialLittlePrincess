#!/usr/bin/env python3
"""Validate T26 PR3 traditional graphology rule structures against frozen research."""
from __future__ import annotations

import json
from pathlib import Path
import sys


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


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    research = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")
    sources = load(root / "ontology/sources.json")
    schools = load(root / "ontology/schools.json")
    claims = load(root / "ontology/source_claims.json")
    concepts = load(root / "ontology/concepts.json")
    gaps = load(root / "traceability/source_gaps.json")["gaps"]
    value_sets = load(root / "values/value_sets.json")
    contract = load(root / "traditional/association_contract.json")
    candidate_policy = load(root / "traditional/candidate_validation_policy.json")
    policies = load(root / "traditional/method_policies.json")["records"]
    associations = load(root / "traditional/associations/jaminian.json")
    packs = load(root / "traditional/rule_pack_registry.json")["packs"]
    gates = load(root / "traditional/activation_gates.json")
    trace = load(root / "traceability/pr3_traditional.json")["records"]
    exclusions = load(root / "traceability/exclusions.json")
    manifest = load(root / "manifest.json")
    scaffold = load(repo / "schema/premium_interpretation_database_v1.json")
    tasks = load(repo / "docs/roadmap/tasks.json")

    errors = []

    def unique(values, label):
        values = list(values)
        if len(values) != len(set(values)):
            errors.append(f"duplicate {label}")

    source_ids = {x["source_id"] for x in sources}
    school_ids = {x["school_id"] for x in schools}
    claim_by_id = {x["assertion_id"]: x for x in claims}
    concept_ids = {x["concept_id"] for x in concepts}
    value_by_id = {x["value_set_id"]: x for x in value_sets}

    unique((x["policy_id"] for x in policies), "method policy")
    unique((x["association_id"] for x in associations), "traditional association")
    unique((x["pack_id"] for x in packs), "rule pack")

    stripped_contract = {k: v for k, v in contract.items() if k not in {"version", "production_status", "runtime_activation"}}
    if stripped_contract != research["school_association_contract"]:
        errors.append("association contract drifted from frozen research")
    stripped_candidate = {k: v for k, v in candidate_policy.items() if k not in {"version", "production_status", "runtime_activation"}}
    if stripped_candidate != research["candidate_validation_policy"]:
        errors.append("candidate-validation policy drifted from frozen research")
    if contract["runtime_activation"] is not False or candidate_policy["runtime_activation"] is not False:
        errors.append("traditional contract/policy became runtime-active")

    if len(policies) != 4:
        errors.append("expected four source-backed method policies")
    if any(x["school_id"] not in school_ids for x in policies):
        errors.append("method policy school does not resolve")
    if any(set(x["source_assertion_ids"]) - set(claim_by_id) for x in policies):
        errors.append("method policy source assertion does not resolve")
    if any({r["source_id"] for r in x["source_refs"]} - source_ids for x in policies):
        errors.append("method policy source does not resolve")
    if any(x["runtime_status"] != "DRAFT_NOT_ACTIVE" for x in policies):
        errors.append("method policy became active")

    by_policy = {x["policy_id"]: x for x in policies}
    cj_context = by_policy["POLICY_CJ_CONTEXTUAL_SYNTHESIS_V1"]
    if cj_context["constraints"]["isolated_sign_is_sufficient"] is not False:
        errors.append("Jamin contextual policy allows isolated-sign sufficiency")
    if cj_context["constraints"]["allow_arbitrary_trait_weights"] is not False:
        errors.append("Jamin contextual policy allows arbitrary weights")

    cj_absence = by_policy["POLICY_CJ_ABSENCE_GUARD_V1"]["constraints"]
    if any(cj_absence[x] is not False for x in [
        "absent_positive_sign_activates_opposite",
        "not_assessable_activates_opposite",
        "not_applicable_activates_opposite",
    ]):
        errors.append("Jamin absence guard permits inverse inference")

    big = by_policy["POLICY_BIG_CORROBORATION_V1"]
    big_claim = claim_by_id["METHOD_BIG_SUPPORT"]
    if big["application_adaptation"] != big_claim["app_adaptation"]:
        errors.append("BIG application adaptation drifted from frozen source assertion")
    if big["constraints"]["minimum_distinct_support_groups"] != 3:
        errors.append("BIG policy must require three distinct support groups under the recorded app adaptation")
    if big["constraints"]["correlated_summaries_count_once"] is not True:
        errors.append("BIG policy would double-count correlated summaries")
    if big["constraints"]["support_count_is_statistical_proof"] is not False:
        errors.append("BIG support count incorrectly treated as statistical proof")

    moretti = by_policy["POLICY_MORETTI_TYPED_RELATIONS_V1"]
    sign_relation = {x["value_id"] for x in value_by_id["SIGN_RELATION"]["values"]}
    if set(moretti["allowed_relation_value_ids"]) != {"SUPPORTS", "OPPOSES", "NEUTRAL"}:
        errors.append("Moretti relation policy contains unsupported relation values")
    if set(moretti["allowed_relation_value_ids"]) - sign_relation:
        errors.append("Moretti relation value does not resolve")
    if moretti["constraints"]["enable_decimi_scoring"] is not False or moretti["constraints"]["enable_temperament_classifier"] is not False:
        errors.append("Moretti blocked scoring/classification was enabled")

    historical_claims = {
        x["assertion_id"]: x for x in claims
        if x["claim_kind"] == "HISTORICAL_INTERPRETIVE_ASSOCIATION"
    }
    if len(historical_claims) != 2 or len(associations) != 2:
        errors.append("expected exactly two researched historical association stubs")

    for a in associations:
        claim = historical_claims.get(a["source_assertion_id"])
        if claim is None:
            errors.append(f"association source assertion is not a researched historical claim: {a['association_id']}")
            continue
        if a["source_id"] != claim["source_id"] or a["locator"] != claim["locator"]:
            errors.append(f"association provenance drift: {a['association_id']}")
        if a["paraphrase"] != claim["paraphrase"]:
            errors.append(f"association paraphrase drift: {a['association_id']}")
        if a["source_premise_examples"] != claim.get("premise_examples", []):
            errors.append(f"association source examples drift: {a['association_id']}")
        if a["traditional_interpretation"]["source_term"] != claim.get("source_term"):
            errors.append(f"association source term drift: {a['association_id']}")
        if a["remaining_gaps"] != claim["remaining_gaps"]:
            errors.append(f"association gap list drift: {a['association_id']}")
        if a["school_id"] != "JAMINIAN":
            errors.append(f"historical Jamin association assigned to wrong school: {a['association_id']}")
        if a["premise_concepts"] or a["all_of"] or a["any_of"] or a["modifiers"] or a["counter_signs"] or a["exclusions"]:
            errors.append(f"uninspected executable rule content invented: {a['association_id']}")
        if a["premise_binding_status"] != "UNOPERATIONALIZED_SOURCE_EXAMPLES":
            errors.append(f"historical source examples were operationalized: {a['association_id']}")
        if a["runtime_eligibility"] != "BLOCKED_RESEARCH_ONLY" or a["eligible_for_rule_engine"] or a["eligible_for_model_candidate"]:
            errors.append(f"historical association became runtime/model eligible: {a['association_id']}")

    policy_ids = {x["policy_id"] for x in policies}
    association_ids = {x["association_id"] for x in associations}
    expected_school_ids = {x["school_id"] for x in schools if x["school_kind"] == "GRAPHOLOGY_TRADITION_PROFILE"}
    if len(packs) != 5 or {x["school_id"] for x in packs} != expected_school_ids:
        errors.append("rule-pack shells do not cover exactly the five graphology traditions")
    if any(set(x["method_policy_ids"]) - policy_ids for x in packs):
        errors.append("rule pack method policy does not resolve")
    if any(set(x["association_ids"]) - association_ids for x in packs):
        errors.append("rule pack association does not resolve")
    if any(x["runtime_eligible_association_ids"] or x["runtime_activation"] is not False for x in packs):
        errors.append("rule pack contains runtime-eligible association")
    non_jamin = [x for x in packs if x["school_id"] != "JAMINIAN"]
    if any(x["association_ids"] for x in non_jamin):
        errors.append("association was invented for an unpopulated school pack")

    if gates["general_release_gates"] != research["release_gates"]:
        errors.append("traditional activation gates drifted from frozen research release gates")
    if gates["runtime_activation"] is not False:
        errors.append("traditional activation gates are active")
    gate_by_id = {x["association_id"]: x for x in gates["association_gates"]}
    for a in associations:
        gate = gate_by_id.get(a["association_id"])
        if gate is None or gate["unresolved_requirements"] != a["remaining_gaps"] or gate["may_enter_runtime_pack"] is not False:
            errors.append(f"association activation gate invalid: {a['association_id']}")

    required_trace = {
        ("SCHOOL_ASSOCIATION_CONTRACT", "school_association_contract"),
        ("CANDIDATE_VALIDATION_POLICY", "candidate_validation_policy"),
        ("RELEASE_GATES", "release_gates"),
        ("SOURCE_ASSERTION", "METHOD_CJ_CONTEXT"),
        ("SOURCE_ASSERTION", "METHOD_CJ_ABSENCE"),
        ("SOURCE_ASSERTION", "METHOD_BIG_SUPPORT"),
        ("SOURCE_ASSERTION", "METHOD_MORETTI_RELATIONS"),
        ("SOURCE_ASSERTION", "HIST_CJ_ANIMATION"),
        ("SOURCE_ASSERTION", "HIST_CJ_FIRMNESS"),
    }
    actual_trace = {(x["research_kind"], x["research_id"]) for x in trace}
    if required_trace != actual_trace:
        errors.append("PR3 traditional traceability differs from expected research inputs")

    blocked_concepts = {
        x["object_id"] for x in gaps
        if x["object_kind"] == "CONCEPT" and x["blocks_runtime_activation"]
    }
    if blocked_concepts != concept_ids:
        errors.append("existing concept activation gaps changed during PR3")

    required_exclusions = {
        "Production question text and executable question packs",
        "Runtime activation of any traditional association or rule pack",
        "Source-complete association population beyond the two researched blocked Jaminian stubs",
        "Candidate generator implementations",
        "Soft-field activation and tone profiles",
        "Report mappings",
        "Localization",
        "Compiled premium_interpretation_database_v1.json",
    }
    if set(exclusions["intentionally_not_in_scope"]) != required_exclusions:
        errors.append("PR3 exclusions differ from reviewed scope")

    expected_counts = {
        "traditional_method_policies": 4,
        "association_contracts": 1,
        "candidate_validation_policies": 1,
        "historical_association_stubs": 2,
        "runtime_eligible_associations": 0,
        "rule_pack_shells": 5,
        "active_rule_packs": 0,
    }
    for key, value in expected_counts.items():
        if manifest["counts"].get(key) != value:
            errors.append(f"manifest PR3 count differs for {key}")
    if manifest["runtime_activation"] is not False or manifest["t26_status"] != "PLANNED":
        errors.append("manifest/T26 unexpectedly activated")
    if manifest["production_scope"] != "ONTOLOGY_PROVENANCE_OBSERVATIONS_SELECTORS_VALUES_TRADITIONAL_RULE_STRUCTURES":
        errors.append("manifest PR3 scope invalid")
    if scaffold.get("status") != "UNPOPULATED":
        errors.append("compiled Premium scaffold must remain UNPOPULATED in PR3")
    if next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] != "PLANNED":
        errors.append("T26 must remain PLANNED in PR3")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "scope": "T26_PR3_TRADITIONAL_RULE_STRUCTURES"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
