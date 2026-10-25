"""R1 reading-v2 compilation: source-locked and never Premium activation."""
from __future__ import annotations

import copy
import json

import pytest

import generate_report_reading_content as compiler


def prepared():
    sources = {name: compiler._read(path) for name, path in compiler.INPUTS.items()}
    baseline = compiler._read(compiler.V1_SOURCE)
    return sources, baseline


def test_six_chapters_and_relations_compile_to_versioned_inactive_registry():
    sources, baseline = prepared()
    compiler.validate_reading_content(
        sources["presentation"], sources["chapters"],
        sources["relations"], sources["manifest"], baseline,
    )
    outputs = compiler.build()
    assert all(path.read_text(encoding="utf-8") == body for path, body in outputs.items())
    compiled = json.loads(outputs[compiler.SERVER_OUTPUT])
    assert compiled["runtime_activation"] is False
    assert compiled["status"] == "DRAFT_FOR_REVIEW"
    assert len(compiled["chapters"]) == len(compiled["relations"]) == 6
    assert {row["section_id"] for row in compiled["chapters"]} == {
        f"section.{family}" for family in compiler.CHAPTERS
    }


def test_v2_cannot_change_one_of_the_54_measurement_highlight_predicates():
    sources, baseline = prepared()
    modified = copy.deepcopy(sources["presentation"])
    modified["candidates"][0]["priority"] += 1
    with pytest.raises(ValueError):
        compiler.validate_reading_content(
            modified, sources["chapters"], sources["relations"],
            sources["manifest"], baseline,
        )


def test_relation_cannot_reference_foreign_or_single_family_candidate():
    sources, baseline = prepared()
    modified = copy.deepcopy(sources["relations"])
    modified["rules"][0]["required_descriptor_ids"][1] = "invented.candidate"
    with pytest.raises(ValueError, match="known distinct families"):
        compiler.validate_reading_content(
            sources["presentation"], sources["chapters"], modified,
            sources["manifest"], baseline,
        )


def test_recovered_manifest_must_remain_draft_and_inactive():
    sources, baseline = prepared()
    for field, value in (
        ("runtime_activation", True),
        ("traditional_runtime_eligible_associations", 1),
        ("does_not_activate_base_pack", False),
        ("max_attempts", 99),
    ):
        modified = copy.deepcopy(sources["manifest"])
        modified[field] = value
        with pytest.raises(ValueError):
            compiler.validate_reading_content(
                sources["presentation"], sources["chapters"],
                sources["relations"], modified, baseline,
            )


def test_client_registry_excludes_authority_and_private_selector_rules():
    outputs = compiler.build()
    client = outputs[compiler.CLIENT_OUTPUT]
    for forbidden in (
        "required_descriptors", "selector_question_ids", "max_model_output_tokens",
        "runtime_activation", "policy_manifest_sha256", "candidate_id",
    ):
        assert forbidden not in client
    assert "Lutning och riktning" in client
    assert "Slant and direction" in client
