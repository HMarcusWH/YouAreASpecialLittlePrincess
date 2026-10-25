"""Inactive R2 /4 story composition using synthetic v2 content, never AI."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import generate_presentation_content as generator
from princess_app.domain.content import presentation as runtime
from princess_app.domain.content.reading import select_descriptors
from princess_app.domain.reports.story import (
    CHAPTER_ORDER, STORY_TEMPLATE_VERSION, ChapterCopy, StoryPolicy,
    build_story_sections,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def synthetic_v2(tmp_path, monkeypatch):
    """Install a test-only v2 clone; it is NOT approved product content."""
    baseline = json.loads(generator.SOURCE.read_text(encoding="utf-8"))
    authored = copy.deepcopy(baseline)
    authored["version"] = "presentation/2"
    authored["policy_version"] = "highlight-policy/2"

    def change(value):
        assert value.startswith("content.highlight.v1.")
        return value.replace("content.highlight.v1.", "content.highlight.v2.", 1)

    authored["content"] = {change(key): value for key, value in baseline["content"].items()}
    authored["fallback_content_id"] = change(baseline["fallback_content_id"])
    for row in authored["candidates"]:
        row["content_id"] = change(row["content_id"])
    generator.validate_v2(authored, baseline)
    compiled = generator.compiled_registry(authored)
    path = tmp_path / "presentation-v2-synthetic.json"
    path.write_text(generator.render(compiled), encoding="utf-8")
    monkeypatch.setattr(runtime, "_V2_PATH", path)
    runtime._load_v2_registry.cache_clear()
    try:
        yield
    finally:
        runtime._load_v2_registry.cache_clear()


def saved_story_input():
    saved = json.loads((ROOT / "fixtures" / "reports" / "report-document.v2.json")
                       .read_text(encoding="utf-8"))
    saved["analysis"]["versions"]["template"] = STORY_TEMPLATE_VERSION
    return saved


def copy_policy(relations=None):
    chapters = tuple(ChapterCopy(section_id=section_id,
                                 neutral_content_id=f"synthetic.neutral.{section_id}",
                                 unavailable_content_id=f"synthetic.missing.{section_id}")
                     for section_id in CHAPTER_ORDER)
    return StoryPolicy(
        presentation_version="presentation/2", chapters=chapters,
        neutral_overview_content_id="synthetic.first_reveal.neutral",
        unqualified_overview_content_id="synthetic.first_reveal.unqualified",
        relation_registry={"policy_version": "combination-policy/1",
                           "relations": [] if relations is None else relations},
    )


def technical_facts(sections):
    return [fid for section in sections
            if section["section_id"] in {"section.sample", *CHAPTER_ORDER}
            for fid in section["fact_ids"]]


def test_six_chapter_story_preserves_all_fact_ownership_and_source_identity(synthetic_v2):
    source = saved_story_input()
    before = copy.deepcopy(source)
    result = build_story_sections(source, copy_policy())
    assert source == before
    expected = ("section.sample", *CHAPTER_ORDER)
    assert tuple(s["section_id"] for s in result if s["section_id"] in expected) == expected
    assert len(technical_facts(result)) == len(set(technical_facts(result))) == 64
    assert set(technical_facts(result)) == {f["fact_id"] for f in source["facts"]}
    assert result[0]["section_id"] == "section.highlight.primary"
    assert result[0]["premium_section_id"] is None
    assert all(s["premium_section_id"] is None for s in result)
    assert all(len(s["content_ids"]) == 1 for s in result
               if s["section_id"] in CHAPTER_ORDER)


def test_blank_sample_cannot_get_a_fabricated_highlight(synthetic_v2):
    doc = saved_story_input()
    for fact in doc["facts"]:
        fact["availability"] = "MISSING"
        fact["value"] = None
    result = build_story_sections(doc, copy_policy())
    assert [section["section_id"] for section in result if section["section_id"].startswith(
        "section.highlight.")] == ["section.highlight.primary"]
    assert result[0]["availability"] == "INELIGIBLE"
    assert result[0]["fact_ids"] == []
    assert result[0]["content_ids"] == ["synthetic.first_reveal.unqualified"]
    assert all(section["availability"] == "INELIGIBLE" for section in result
               if section["section_id"] in ("section.sample", *CHAPTER_ORDER))
    assert len(technical_facts(result)) == 64


def test_supported_without_salient_highlight_uses_neutral_overview(synthetic_v2):
    doc = saved_story_input()
    keep = {"PAGE_LINE_COUNT", "PAGE_WORD_COUNT"}
    for fact in doc["facts"]:
        if fact["feature_id"] not in keep:
            fact["availability"] = "MISSING"
            fact["value"] = None
    result = build_story_sections(doc, copy_policy())
    assert result[0]["availability"] == "UNCALIBRATED"
    assert result[0]["content_ids"] == ["synthetic.first_reveal.neutral"]
    assert set(result[0]["fact_ids"]) == {"fact.PAGE_LINE_COUNT", "fact.PAGE_WORD_COUNT"}
    assert len(technical_facts(result)) == 64


def test_valid_relation_survives_as_free_fact_bound_section(synthetic_v2):
    doc = saved_story_input()
    descriptors = select_descriptors(doc["facts"], runtime.presentation_registry(version="presentation/2"))
    first, second = next(
        (left, right) for left in descriptors for right in descriptors
        if left.family != right.family
    )
    relations = [{
        "relation_id": "synthetic.2family",
        "kind": "CONTRAST",
        "content_id": "synthetic.free.relation",
        "required_descriptors": [first.candidate_id, second.candidate_id],
    }]
    sections = build_story_sections(doc, copy_policy(relations))
    connection = [section for section in sections if section["template"] == "PATTERN_CONNECTION"]
    assert len(connection) == 1
    assert connection[0]["section_id"] == "section.connection.1"
    assert connection[0]["content_ids"] == ["synthetic.free.relation"]
    assert set(connection[0]["fact_ids"]) == set(first.support_fact_ids) | set(second.support_fact_ids)
    assert len(technical_facts(sections)) == 64


def test_story_refuses_unknown_version_or_missing_policy(synthetic_v2):
    doc = saved_story_input()
    wrong = copy.deepcopy(doc)
    wrong["analysis"]["versions"]["template"] = "individual-report/2"
    with pytest.raises(ValueError, match="explicit /4"):
        build_story_sections(wrong, copy_policy())
    wrong_policy = copy_policy()
    from dataclasses import replace
    with pytest.raises(ValueError, match="reviewed presentation/2"):
        build_story_sections(doc, replace(wrong_policy, presentation_version="presentation/1"))
    with pytest.raises(ValueError, match="misordered"):
        build_story_sections(doc, replace(wrong_policy, chapters=wrong_policy.chapters[:-1]))


def test_duplicate_facts_fail_closed_before_story_copy(synthetic_v2):
    doc = saved_story_input()
    doc["facts"][1] = dict(doc["facts"][0])
    with pytest.raises(ValueError, match="repeated"):
        build_story_sections(doc, copy_policy())


def test_story_report_assembly_is_immutable_and_authorized_projection_is_free(synthetic_v2):
    """The gated v4 assembler preserves original analysis and 64 facts."""
    from datetime import datetime, timezone
    from princess_app.domain.analysis import analysis_reference
    from princess_app.domain.reports.assembly import assemble_report, check_revision, revise_report
    from princess_app.domain.reports.projection import ProjectionRequest, project_report
    import generate_report_fixtures as fixtures

    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    result = fixtures.load("engine-result.synthetic.json")
    analysis = analysis_reference(
        analysis_id="analysis_story_synthetic", run_id="run_story_synthetic",
        owner_id="owner_story_synthetic", input_asset_id="asset_story_synthetic",
        input_sha256="0" * 64,
        processed_sha256=result["metadata"]["input_pixels_sha256"],
        created_at=now, engine_version="0.1.0",
        analysis_config_sha256="1" * 64, template=STORY_TEMPLATE_VERSION,
    )
    before_analysis, before_result = copy.deepcopy(analysis), copy.deepcopy(result)

    absent = assemble_report(
        report_id="report_story_synthetic", analysis=analysis, result=result,
        created_at=now, locale="en", evidence=None,
    )
    assert {issue.code for issue in absent.issues} == {"STORY_CONTENT_NOT_INSTALLED"}

    created = assemble_report(
        report_id="report_story_synthetic", analysis=analysis, result=result,
        created_at=now, locale="en", evidence=None, story_policy=copy_policy(),
    )
    assert created.ok, created.issues[:5]
    snapshot = created.value
    data = snapshot.to_dict()
    assert data["revision"] == 1
    assert data["analysis"] == before_analysis
    assert len(data["facts"]) == 64
    assert set(row["fact_id"] for row in data["facts"]) == {
        f"fact.{feature_id}" for feature_id in result["measurements"]
    }
    assert data["premium_overlay_id"] is None
    assert data["sections"][-2]["section_id"] == "section.reference"
    assert data["sections"][-1]["section_id"] == "section.premium"
    assert data["sections"][-1]["availability"] == "LOCKED"
    assert analysis == before_analysis and result == before_result

    projected = project_report(snapshot, ProjectionRequest(
        projection="FREE", generated_at=now, actions={"PURCHASE": "commerce_disabled"},
    ))
    assert projected.ok, projected.issues[:5]
    assert projected.value.data["source_digest"] == data["document_digest"]
    assert len(projected.value.data["facts"]) == 64
    assert not any(s["premium_section_id"] for s in projected.value.data["sections"])

    blocked = revise_report(snapshot, created_at=now, premium_overlay_id="overlay_unreviewed")
    assert {issue.code for issue in blocked.issues} == {"STORY_REVISION_NOT_ENABLED"}
    assert {issue.code for issue in check_revision(snapshot, snapshot)} == {"STORY_REVISION_NOT_ENABLED"}
    with_paid = assemble_report(
        report_id="report_story_synthetic", analysis=analysis, result=result,
        created_at=now, locale="en", story_policy=copy_policy(),
        premium_overlay_id="overlay_unreviewed",
    )
    assert {issue.code for issue in with_paid.issues} == {"STORY_PREMIUM_NOT_ENABLED"}


def test_partial_v4_free_dossier_preserves_missingness_and_disables_paid(synthetic_v2):
    from datetime import datetime, timezone
    from princess_app.domain.analysis import analysis_reference
    from princess_app.domain.reports.assembly import assemble_report
    import generate_report_fixtures as fixtures

    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    result = fixtures.load("engine-result.synthetic.json")
    result["measurements"]["PAGE_WORD_COUNT"]["raw_value"] = 0
    result["measurements"]["PAGE_WORD_COUNT"]["quality_flag"] = "EXPERIMENTAL"
    analysis = analysis_reference(
        analysis_id="analysis_story_partial", run_id="run_story_partial",
        owner_id="owner_story_partial", input_asset_id="asset_story_partial",
        input_sha256="0" * 64,
        processed_sha256=result["metadata"]["input_pixels_sha256"], created_at=now,
        engine_version="0.1.0", analysis_config_sha256="1" * 64,
        template=STORY_TEMPLATE_VERSION,
    )
    compiled = assemble_report(
        report_id="report_story_partial", analysis=analysis, result=result,
        created_at=now, locale="sv", story_policy=copy_policy(),
    )
    assert compiled.ok, compiled.issues[:5]
    data = compiled.value.data
    word = next(x for x in data["facts"] if x["feature_id"] == "PAGE_WORD_COUNT")
    assert word["value"] == 0  # observed zero is not silently renamed MISSING
    assert data["sections"][-1]["availability"] == "INELIGIBLE"
    assert any(n["localization_key"] == "notice.image_only" for n in data["notices"])
