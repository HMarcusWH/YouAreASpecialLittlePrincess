"""T08A presentation registry and broad deterministic first-reveal selection."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import generate_presentation_content as generator
from princess_app.domain.content.presentation import (
    content_text,
    display_domain,
    family_nominees,
    feature_label,
    presentation_registry,
    select_highlights,
)

ROOT = Path(__file__).resolve().parents[1]


def fact(feature_id: str, value: float, *, n: int, availability: str = "UNCALIBRATED") -> dict:
    return {
        "fact_id": f"fact.{feature_id}",
        "feature_id": feature_id,
        "availability": availability,
        "value": value,
        "quality": {"n_observations": n},
    }


def witness_facts(candidate: dict) -> list[dict]:
    n = candidate["minimum_observations"]
    assert set(candidate["witness"]) == set(candidate["support_features"])
    return [fact(feature_id, candidate["witness"][feature_id], n=n)
            for feature_id in candidate["support_features"]]


def test_presentation_compiler_outputs_are_exact_and_reviewed():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    generator.validate(source)
    expected = generator.render(generator.compiled_registry(source))
    assert all(path.read_text(encoding="utf-8") == expected for path in generator.OUTPUTS)


def test_registry_access_is_defensive():
    registry = presentation_registry()
    registry["feature_labels"]["SLANT_ANGLE_MEAN"]["en"] = "mutated"
    assert feature_label("SLANT_ANGLE_MEAN", "en") != "mutated"


def test_registry_is_broad_across_six_mechanical_families():
    registry = presentation_registry()
    assert len(registry["feature_labels"]) == 64
    assert len(registry["candidates"]) >= 42
    counts = {family: 0 for family in registry["family_order"]}
    for candidate in registry["candidates"]:
        counts[candidate["family"]] += 1
    assert set(counts) == {"slant", "layout", "baseline", "spacing", "size", "ink"}
    assert min(counts.values()) >= 5
    assert len(registry["candidates"]) == 54
    assert registry["primary_families"] == ["slant", "layout", "baseline", "spacing", "size"]
    assert "ink" not in registry["primary_families"]


def test_every_reviewed_candidate_has_a_reachable_synthetic_witness():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    for row in source["candidates"]:
        facts = witness_facts(row)
        nominees = {candidate.family: candidate for candidate in family_nominees(facts)}
        assert row["family"] in nominees, row["candidate_id"]
        assert nominees[row["family"]].candidate_id == row["candidate_id"], row["candidate_id"]


def test_image_proxy_family_can_be_secondary_but_never_primary():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    wanted = {"ink.stroke_uniform", "slant.right.most"}
    rows = [row for row in source["candidates"] if row["candidate_id"] in wanted]
    facts_by_id = {}
    for row in rows:
        for item in witness_facts(row):
            facts_by_id[item["fact_id"]] = item
    selected = select_highlights(list(facts_by_id.values()), limit=2)
    assert selected
    assert selected[0].family == "slant"
    assert any(candidate.family == "ink" for candidate in selected[1:])


def test_image_proxy_is_secondary_fallback_not_routine_slot():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    wanted = {
        "slant.right.almost_all",
        "layout.margins_asymmetric",
        "baseline.rising",
        "ink.saturation_low",
    }
    facts_by_id = {}
    for row in source["candidates"]:
        if row["candidate_id"] not in wanted:
            continue
        for item in witness_facts(row):
            facts_by_id[item["fact_id"]] = item
    selected = select_highlights(list(facts_by_id.values()), limit=3)
    assert len(selected) == 3
    assert {candidate.family for candidate in selected} == {"slant", "layout", "baseline"}
    assert all(candidate.family != "ink" for candidate in selected)

def test_selection_is_order_invariant_and_returns_distinct_families():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    wanted = {
        "slant.right.almost_all",
        "layout.margins_asymmetric",
        "baseline.rising",
        "spacing.lines_open",
        "size.taller_components",
        "ink.stroke_uniform",
    }
    rows = [row for row in source["candidates"] if row["candidate_id"] in wanted]
    facts_by_id = {}
    for row in rows:
        for item in witness_facts(row):
            facts_by_id[item["fact_id"]] = item
    facts = list(facts_by_id.values())
    first = select_highlights(facts)
    second = select_highlights(list(reversed(facts)))
    assert first == second
    assert len(first) == 3
    assert len({candidate.family for candidate in first}) == 3


def test_common_neutral_states_do_not_monopolize_primary():
    neutral_ids = {
        "layout.centered",
        "baseline.near_level",
        "spacing.lines_consistent",
        "size.balanced_aspect",
        "slant.consistent",
    }
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    rows = {row["candidate_id"]: row for row in source["candidates"]}

    def profile(target: str, overrides: dict[str, float]) -> list[dict]:
        facts_by_id = {}
        for candidate_id in neutral_ids | {target}:
            row = rows[candidate_id]
            for item in witness_facts(row):
                facts_by_id[item["fact_id"]] = item
        for feature_id, value in overrides.items():
            fact_id = f"fact.{feature_id}"
            if fact_id not in facts_by_id:
                facts_by_id[fact_id] = fact(feature_id, value, n=8)
            else:
                facts_by_id[fact_id]["value"] = value
        return list(facts_by_id.values())

    cases = [
        ("slant.right.almost_all", {"SLANT_RIGHT_FRACTION": 0.98}, "slant"),
        ("layout.margins_asymmetric", {"MARGIN_SYMMETRY": 0.05}, "layout"),
        ("baseline.rising", {"BASELINE_ANGLE_MEAN": 8.0}, "baseline"),
        ("spacing.lines_more_consistent", {"LINE_SPACING_CV": 0.03, "WORD_SPACING_CV": 0.6}, "spacing"),
        ("size.taller_components", {"GLYPH_ASPECT_RATIO_MEAN": 0.2}, "size"),
    ]
    for candidate_id, overrides, expected_family in cases:
        selected = select_highlights(profile(candidate_id, overrides))
        assert selected and selected[0].family == expected_family, candidate_id

def test_missing_and_low_observation_support_never_becomes_a_highlight():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    row = source["candidates"][0]
    facts = witness_facts(row)
    facts[0]["availability"] = "MISSING"
    facts[0]["value"] = None
    assert select_highlights(facts) == ()
    facts = witness_facts(row)
    facts[0]["quality"]["n_observations"] = row["minimum_observations"] - 1
    assert select_highlights(facts) == ()


def test_feature_labels_and_highlight_copy_are_bilingual_and_fail_closed():
    registry = presentation_registry()
    for feature_id in registry["feature_labels"]:
        assert feature_label(feature_id, "en")
        assert feature_label(feature_id, "sv-SE")
    for content_id in registry["content"]:
        assert content_text(content_id, "en")
        assert content_text(content_id, "sv")
    try:
        feature_label("NOT_A_FEATURE", "en")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown feature label must fail closed")


def test_registry_validator_rejects_claim_drift_and_rule_configuration_faults():
    source = json.loads(generator.SOURCE.read_text(encoding="utf-8"))

    cases = []

    missing_label = copy.deepcopy(source)
    missing_label["feature_labels"].pop("SLANT_ANGLE_MEAN")
    cases.append(missing_label)

    population_claim = copy.deepcopy(source)
    population_claim["content"]["content.highlight.v1.slant.mixed"]["en"] = "This is a rare slant pattern."
    cases.append(population_claim)

    wrong_domain_unit = copy.deepcopy(source)
    wrong_domain_unit["display_domains"]["SLANT_ANGLE_MEAN"]["unit"] = "ratio"
    cases.append(wrong_domain_unit)

    image_claim = copy.deepcopy(source)
    image_claim["content"]["content.highlight.v1.ink.stroke_uniform"]["en"] = "Stroke thickness is highly consistent."
    cases.append(image_claim)

    bad_spacing_gate = copy.deepcopy(source)
    next(row for row in bad_spacing_gate["candidates"] if row["family"] == "spacing")["minimum_observations"] = 2
    cases.append(bad_spacing_gate)

    zero_width_strength = copy.deepcopy(source)
    row = next(row for row in zero_width_strength["candidates"] if row["strength"]["op"] == "normalize")
    row["strength"]["max"] = row["strength"]["min"]
    cases.append(zero_width_strength)

    invalid_weight = copy.deepcopy(source)
    invalid_weight["candidates"][0]["strength"]["weight"] = 1.1
    cases.append(invalid_weight)

    typo_clause = copy.deepcopy(source)
    typo_clause["candidates"][0]["clauses"][0]["maxx"] = 999
    cases.append(typo_clause)

    typo_strength = copy.deepcopy(source)
    typo_strength["candidates"][0]["strength"]["weigth"] = 0.5
    cases.append(typo_strength)
    for bad in cases:
        try:
            generator.validate(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid presentation registry mutation unexpectedly validated")


def test_duplicate_json_keys_fail_closed(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":"presentation/1","version":"presentation/2"}', encoding="utf-8")
    try:
        generator._load_json(path)
    except ValueError as exc:
        assert "duplicate JSON key" in str(exc)
    else:
        raise AssertionError("duplicate JSON keys must fail closed")


def test_display_domain_access_is_defensive():\n    first = display_domain("SLANT_ANGLE_MEAN")\n    assert first is not None\n    first["min"] = 0\n    assert display_domain("SLANT_ANGLE_MEAN")["min"] == -90\n\ndef test_display_domains_are_non_population_and_slant_canvas_keeps_acceptance_boundary():
    registry = presentation_registry()
    assert {row["kind"] for row in registry["display_domains"].values()} <= {
        "GEOMETRIC_CANVAS", "MATHEMATICAL_DOMAIN",
    }
    slant = display_domain("SLANT_ANGLE_MEAN")
    assert slant == {
        "min": -90,
        "max": 90,
        "unit": "degrees",
        "kind": "GEOMETRIC_CANVAS",
        "accepted_min": -60,
        "accepted_max": 60,
    }
    assert display_domain("MARGIN_RIGHT_REL") is None


def test_ink_content_is_image_qualified_not_physical_pressure():
    registry = presentation_registry()
    for row in registry["candidates"]:
        if row["family"] != "ink":
            continue
        en = content_text(row["content_id"], "en").lower()
        sv = content_text(row["content_id"], "sv").lower()
        assert "image" in en and "bild" in sv
        assert "pressure" not in en and "pentryck" not in sv
