"""Tests for the complete T26 database pending review."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "tools/validate_graphology_database.py"
SPEC = importlib.util.spec_from_file_location("graphology_database_validator", VALIDATOR)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def load(relative: str):
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


def test_complete_database_validator_passes():
    assert module.validate(REPO) == []


def test_compiled_artifact_is_populated_but_not_active():
    db = load("schema/premium_interpretation_database_v1.json")
    assert db["status"] == "POPULATED_PENDING_REVIEW"
    assert db["runtime_activation"] is False
    assert len(db["selector_definitions"]) == 89
    assert len(db["question_definitions"]) == 89
    assert len(db["question_packs"]) == 5
    assert len(db["soft_field_definitions"]) == 8
    assert len(db["report_mappings"]) == 97


def test_question_and_soft_copy_cannot_add_new_numeric_claims():
    db = load("schema/premium_interpretation_database_v1.json")
    assert all(x["allow_new_numbers"] is False for x in db["soft_field_definitions"])
    tone = db["tone_profiles"][0]
    assert "NEW_NUMERIC_MEASUREMENT_PERCENTILE_PROBABILITY_OR_SCORE" in tone["prohibited_claim_classes"]


def test_traditional_pack_is_still_blocked():
    db = load("schema/premium_interpretation_database_v1.json")
    pack = next(x for x in db["question_packs"] if x["pack_id"] == "PREMIUM_TRADITIONAL_READING_V1")
    assert pack["production_status"] == "BLOCKED_NO_RUNTIME_ELIGIBLE_ASSOCIATIONS"
    assert all(x["runtime_activation"] is False for x in db["traditional"]["rule_pack_registry"])
    assert all(x["runtime_eligible_association_ids"] == [] for x in db["traditional"]["rule_pack_registry"])


def test_t26_is_implemented_pending_review_not_complete():
    tasks = load("docs/roadmap/tasks.json")
    assert next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] == "IMPLEMENTED_PENDING_REVIEW"
