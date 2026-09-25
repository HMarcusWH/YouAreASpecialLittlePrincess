"""Tests for T26 PR2 graphology observation/value/selector foundation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "tools/validate_graphology_selector_foundation.py"
SPEC = importlib.util.spec_from_file_location("graphology_selector_validator", VALIDATOR)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)

DOMAINS = module.DOMAINS


def load(relative: str):
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


def concat(relative: str):
    return [item for name in DOMAINS for item in load(f"{relative}/{name}.json")]


def test_selector_foundation_validator_passes():
    assert module.validate(REPO) == []


def test_all_89_selectors_exist_but_none_are_active():
    selectors = concat("schema/graphology_interpretation/v1/selectors")
    assert len(selectors) == 89
    assert len({x["selector_id"] for x in selectors}) == 89
    assert all(x["runtime_status"] == "DRAFT_NOT_ACTIVE" for x in selectors)


def test_fixed_and_dynamic_selector_domains_are_exact():
    selectors = concat("schema/graphology_interpretation/v1/selectors")
    assert sum(x["selection_domain"] == "FIXED" for x in selectors) == 54
    assert sum(x["selection_domain"] == "DYNAMIC" for x in selectors) == 35
    assert all((x["value_set_id"] is not None) != (x["candidate_kind"] is not None) for x in selectors)


def test_value_sets_are_complete_and_inactive():
    sets = load("schema/graphology_interpretation/v1/values/value_sets.json")
    assert len(sets) == 44
    assert sum(len(x["values"]) for x in sets) == 156
    assert all(x["runtime_activation"] is False and x["production_status"] == "DRAFT_NOT_ACTIVE" for x in sets)


def test_observation_boundary_is_explicit_and_inactive():
    observations = concat("schema/graphology_interpretation/v1/ontology/observations")
    assert len(observations) == 49
    assert all(x["runtime_status"] == "DRAFT_NOT_ACTIVE" for x in observations)
    assert all(x["domain_id"] not in {"INTERPRETATION", "PAIR", "HISTORY"} for x in observations)
    assert all(x["source_question_id"] != "Q_HIERARCHY_RELATION" for x in observations)


def test_feature_mappings_are_support_only():
    mappings = concat("schema/graphology_interpretation/v1/ontology/feature_mappings")
    assert len(mappings) == 50
    assert len({x["canonical_feature_id"] for x in mappings}) == 50
    assert all(x["relationship"] == "SUPPORTING_NOT_AUTOMATIC_SEMANTIC_EQUIVALENCE" for x in mappings)
    assert all(x["mapping_status"] == "DRAFT_SUPPORT_ONLY" and x["runtime_activation"] is False for x in mappings)


def test_candidate_kinds_are_registered_names_not_generators():
    records = load("schema/graphology_interpretation/v1/candidates/candidate_definitions.json")["records"]
    assert len(records) == 33
    assert all(x["definition_status"] == "REGISTERED_NAME_FROM_FROZEN_RESEARCH" for x in records)
    assert all(x["generator_status"] == "NOT_IMPLEMENTED_IN_T26_PR2" for x in records)


def test_answer_states_keep_absence_assessability_and_applicability_separate():
    states = load("schema/graphology_interpretation/v1/values/answer_states.json")["states"]
    assert set(states) == {
        "ANSWERED", "OBSERVED_ABSENT", "NOT_ASSESSABLE", "NOT_APPLICABLE",
        "CONFLICTING_EVIDENCE", "NO_ELIGIBLE_CANDIDATE",
    }


def test_runtime_scaffold_and_t26_remain_unactivated():
    assert load("schema/premium_interpretation_database_v1.json")["status"] == "UNPOPULATED"
    tasks = load("docs/roadmap/tasks.json")
    assert next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] == "PLANNED"
