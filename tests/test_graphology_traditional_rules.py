"""Tests for T26 PR3 traditional graphology rule structures."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "tools/validate_graphology_traditional_rules.py"
SPEC = importlib.util.spec_from_file_location("graphology_traditional_validator", VALIDATOR)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def load(relative: str):
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


def test_traditional_rule_validator_passes():
    assert module.validate(REPO) == []


def test_only_two_historical_association_stubs_exist_and_are_blocked():
    records = load("schema/graphology_interpretation/v1/traditional/associations/jaminian.json")
    assert len(records) == 2
    assert all(x["runtime_eligibility"] == "BLOCKED_RESEARCH_ONLY" for x in records)
    assert all(x["eligible_for_rule_engine"] is False for x in records)
    assert all(x["eligible_for_model_candidate"] is False for x in records)


def test_historical_stubs_have_no_invented_executable_premises():
    records = load("schema/graphology_interpretation/v1/traditional/associations/jaminian.json")
    for record in records:
        assert record["premise_concepts"] == []
        assert record["all_of"] == []
        assert record["any_of"] == []
        assert record["modifiers"] == []
        assert record["counter_signs"] == []
        assert record["exclusions"] == []
        assert record["premise_binding_status"] == "UNOPERATIONALIZED_SOURCE_EXAMPLES"


def test_jamin_absence_guard_blocks_inverse_inference():
    policies = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in policies if x["policy_id"] == "POLICY_CJ_ABSENCE_GUARD_V1")["constraints"]
    assert p["absent_positive_sign_activates_opposite"] is False
    assert p["not_assessable_activates_opposite"] is False
    assert p["not_applicable_activates_opposite"] is False
    assert p["explicit_opposing_evidence_required_for_opposite"] is True


def test_big_support_policy_requires_distinct_groups_not_statistical_proof():
    policies = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in policies if x["policy_id"] == "POLICY_BIG_CORROBORATION_V1")["constraints"]
    assert p["minimum_distinct_support_groups"] == 3
    assert p["correlated_summaries_count_once"] is True
    assert p["repeated_measurements_of_same_graphic_family_count_once"] is True
    assert p["support_count_is_statistical_proof"] is False


def test_moretti_policy_does_not_enable_unreviewed_scores_or_classifier():
    policies = load("schema/graphology_interpretation/v1/traditional/method_policies.json")["records"]
    p = next(x for x in policies if x["policy_id"] == "POLICY_MORETTI_TYPED_RELATIONS_V1")
    assert set(p["allowed_relation_value_ids"]) == {"SUPPORTS", "OPPOSES", "NEUTRAL"}
    assert p["constraints"]["enable_decimi_scoring"] is False
    assert p["constraints"]["enable_temperament_classifier"] is False


def test_all_five_school_packs_are_inactive():
    packs = load("schema/graphology_interpretation/v1/traditional/rule_pack_registry.json")["packs"]
    assert len(packs) == 5
    assert all(x["runtime_activation"] is False for x in packs)
    assert all(x["runtime_eligible_association_ids"] == [] for x in packs)


def test_runtime_scaffold_and_t26_remain_unactivated():
    assert load("schema/premium_interpretation_database_v1.json")["status"] == "UNPOPULATED"
    tasks = load("docs/roadmap/tasks.json")
    assert next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] == "PLANNED"
