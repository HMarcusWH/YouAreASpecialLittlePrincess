"""Traditional-rule safety regressions."""

from pathlib import Path
import importlib.util
import json

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
spec = importlib.util.spec_from_file_location("trad", TOOLS / "validate_graphology_traditional_rules.py")
m = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(m)


def load(p):
    return json.loads((REPO / p).read_text())


def test_validator_passes():
    assert m.validate(REPO) == []


def test_historical_stubs_stay_blocked():
    rows = load("schema/graphology_interpretation/v1/traditional/associations/jaminian.json")
    assert len(rows) == 2 and all(
        x["runtime_eligibility"] == "BLOCKED_RESEARCH_ONLY"
        and not x["eligible_for_rule_engine"]
        and not x["eligible_for_model_candidate"]
        for x in rows
    )


def test_jamin_absence_guard_blocks_inverse_inference():
    rows = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in rows if x["policy_id"] == "POLICY_CJ_ABSENCE_GUARD_V1")["constraints"]
    assert (
        p["absent_positive_sign_activates_opposite"] is False
        and p["not_assessable_activates_opposite"] is False
        and p["not_applicable_activates_opposite"] is False
        and p["explicit_opposing_evidence_required_for_opposite"] is True
    )


def test_big_support_is_distinct_and_not_statistical_proof():
    rows = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in rows if x["policy_id"] == "POLICY_BIG_CORROBORATION_V1")["constraints"]
    assert (
        p["minimum_distinct_support_groups"] == 3
        and p["correlated_summaries_count_once"] is True
        and p["repeated_measurements_of_same_graphic_family_count_once"] is True
        and p["support_count_is_statistical_proof"] is False
    )


def test_moretti_unreviewed_scoring_and_classifier_remain_disabled():
    rows = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in rows if x["policy_id"] == "POLICY_MORETTI_TYPED_RELATIONS_V1")
    assert (
        set(p["allowed_relation_value_ids"]) == {"SUPPORTS", "OPPOSES", "NEUTRAL"}
        and p["constraints"]["enable_decimi_scoring"] is False
        and p["constraints"]["enable_temperament_classifier"] is False
    )


def test_rule_packs_stay_inactive():
    packs = load("schema/graphology_interpretation/v1/traditional/rule_pack_registry.json")["packs"]
    assert all(not p["runtime_activation"] and p["runtime_eligible_association_ids"] == [] for p in packs)
