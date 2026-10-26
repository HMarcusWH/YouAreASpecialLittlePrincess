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


def test_reviewed_r1_policy_uses_exact_bilingual_copy_and_is_immutable():
    """The real generated R1 source, not a synthetic StoryPolicy, is usable."""
    from types import MappingProxyType
    from princess_app.domain.content import reading
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading

    policy = story_policy_from_reviewed_reading()
    source = reading.reading_registry()
    assert policy.presentation_version == "presentation/2"
    assert tuple(ch.section_id for ch in policy.chapters) == CHAPTER_ORDER
    assert tuple(row["relation_id"] for row in policy.relation_registry["relations"]) == tuple(
        row["relation_id"] for row in source["relations"]
    )
    assert len(policy.relation_registry["relations"]) == 6
    assert isinstance(policy.relation_registry, MappingProxyType)
    assert all(isinstance(row, MappingProxyType)
               and isinstance(row["required_descriptors"], tuple)
               for row in policy.relation_registry["relations"])
    with pytest.raises(TypeError):
        policy.relation_registry["policy_version"] = "adversarial/1"
    with pytest.raises(TypeError):
        policy.relation_registry["relations"][0]["relation_id"] = "forged"

    for state, content_id in (("NEUTRAL", policy.neutral_overview_content_id),
                              ("PARTIAL", policy.partial_overview_content_id),
                              ("UNQUALIFIED", policy.unqualified_overview_content_id)):
        assert content_id == reading.reading_state_content_id(state)
        for locale in ("en", "sv"):
            assert reading.reading_content_text(content_id, locale) == source["states"][state][locale]
    for chapter, record in zip(policy.chapters, source["chapters"]):
        for locale in ("en", "sv"):
            assert reading.reading_chapter_title(chapter.section_id, locale) == record["title"][locale]
            assert reading.reading_content_text(chapter.neutral_content_id, locale) == record["neutral"][locale]
            assert reading.reading_content_text(chapter.unavailable_content_id, locale) == record["unavailable"][locale]
    for relation in source["relations"]:
        for locale in ("en", "sv"):
            assert reading.reading_content_text(relation["content_id"], locale) == relation["copy"][locale]

    # A returned source copy cannot poison the independently cached authority.
    source["chapters"][0]["title"]["en"] = "forged"
    source["relations"][0]["required_descriptors"].clear()
    assert reading.reading_chapter_title("section.slant", "en") == "Slant and direction"
    assert len(story_policy_from_reviewed_reading().relation_registry["relations"][0]["required_descriptors"]) == 2


def test_reviewed_r1_story_keeps_64_facts_and_resolves_every_emitted_copy():
    from princess_app.domain.content import reading
    from princess_app.domain.content.presentation import content_text
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading

    source = saved_story_input()
    before = copy.deepcopy(source)
    sections = build_story_sections(source, story_policy_from_reviewed_reading())
    assert source == before
    assert len(technical_facts(sections)) == len(set(technical_facts(sections))) == 64
    assert set(technical_facts(sections)) == {f["fact_id"] for f in source["facts"]}
    assert tuple(row["section_id"] for row in sections if row["section_id"] in CHAPTER_ORDER) == CHAPTER_ORDER
    for section in sections:
        assert section["premium_section_id"] is None
        for content_id in section["content_ids"]:
            for locale in ("en", "sv"):
                if content_id.startswith("content.highlight.v2."):
                    assert content_text(content_id, locale, version="presentation/2").strip()
                else:
                    assert reading.reading_content_text(content_id, locale).strip()


def test_reviewed_r1_fallbacks_are_honest_for_neutral_partial_and_unqualified():
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading

    policy = story_policy_from_reviewed_reading()
    sample = saved_story_input()
    for fact in sample["facts"]:
        if fact["feature_id"] not in {"PAGE_LINE_COUNT", "PAGE_WORD_COUNT"}:
            fact["availability"], fact["value"] = "MISSING", None
    neutral = build_story_sections(sample, policy)
    assert neutral[0]["content_ids"] == [policy.neutral_overview_content_id]
    assert neutral[0]["availability"] == "UNCALIBRATED"
    assert len(technical_facts(neutral)) == 64

    partial = copy.deepcopy(sample)
    next(f for f in partial["facts"] if f["feature_id"] == "PAGE_WORD_COUNT")["value"] = 0
    limited = build_story_sections(partial, policy)
    assert limited[0]["content_ids"] == [policy.partial_overview_content_id]
    assert limited[0]["availability"] == "UNCALIBRATED"
    assert len(technical_facts(limited)) == 64

    unqualified = copy.deepcopy(sample)
    next(f for f in unqualified["facts"] if f["feature_id"] == "PAGE_LINE_COUNT")["value"] = 0
    absent = build_story_sections(unqualified, policy)
    assert absent[0]["content_ids"] == [policy.unqualified_overview_content_id]
    assert absent[0]["availability"] == "INELIGIBLE"
    assert not any(row["template"] == "PATTERN_CONNECTION" for row in absent)
    assert len(technical_facts(absent)) == 64


def test_reviewed_registry_requires_known_ids_and_locales_and_preserves_v1():
    from princess_app.domain.content import reading
    from princess_app.domain.content.presentation import presentation_registry, content_text
    before = (ROOT / "src/princess_app/domain/content/_presentation_v1.json").read_bytes()
    v1 = presentation_registry(version="presentation/1")
    policy = reading.reading_registry()
    assert policy["runtime_activation"] is False
    assert policy["reading_pack_version"] == "premium-reading/2"
    assert set(policy["source_sha256"]) == {"presentation", "chapters", "relations", "manifest"}
    assert len(presentation_registry(version="presentation/2")["feature_labels"]) == 64
    assert len(presentation_registry(version="presentation/2")["candidates"]) == 54
    with pytest.raises(KeyError, match="unreviewed reading content"):
        reading.reading_content_text("content.reading.v2.state.forged", "en")
    with pytest.raises(KeyError, match="unknown reading chapter"):
        reading.reading_chapter_title("section.foreign", "sv")
    with pytest.raises(ValueError, match="unknown reviewed reading state"):
        reading.reading_state_content_id("REWRITTEN")
    with pytest.raises(ValueError, match="unsupported reading locale"):
        reading.reading_content_text(reading.reading_state_content_id("NEUTRAL"), "de")
    assert reading.reading_content_text(reading.reading_state_content_id("NEUTRAL"), "sv-SE").strip()
    assert (ROOT / "src/princess_app/domain/content/_presentation_v1.json").read_bytes() == before
    assert presentation_registry(version="presentation/1") == v1
    assert content_text(v1["fallback_content_id"], "en").strip()


def test_reviewed_registry_byte_and_source_pins_are_immutable(tmp_path, monkeypatch):
    from princess_app.domain.content import reading
    from hashlib import sha256

    raw = reading._READING_PATH.read_bytes()
    original_path = reading._READING_PATH
    data = json.loads(raw)
    source_paths = {
        "presentation": ROOT / "content/presentation/v2/presentation.json",
        "chapters": ROOT / "content/presentation/v2/chapters.json",
        "relations": ROOT / "content/premium/reading-v2/relations.json",
        "manifest": ROOT / "content/premium/reading-v2/manifest.json",
    }
    assert reading._READING_SOURCE_PINS == {
        name: sha256(path.read_bytes()).hexdigest() for name, path in source_paths.items()
    }
    assert reading._READING_SHA256 == sha256(raw).hexdigest()
    assert reading._PRESENTATION_SHA256 == sha256((
        ROOT / "src/princess_app/domain/content/_presentation_v2.json"
    ).read_bytes()).hexdigest()

    try:
        monkeypatch.setattr(reading, "_READING_PATH", tmp_path / "missing.json")
        reading._load_reading_registry.cache_clear()
        with pytest.raises(ValueError, match="not installed"):
            reading.reading_registry()
        malicious = tmp_path / "malicious.json"
        malicious.write_bytes(raw)
        symbolic = tmp_path / "symbolic.json"
        symbolic.symlink_to(malicious)
        monkeypatch.setattr(reading, "_READING_PATH", symbolic)
        with pytest.raises(ValueError, match="not installed"):
            reading.reading_registry()

        modified = copy.deepcopy(data)
        modified["chapters"][0]["neutral"]["en"] = "Unreviewed claim"
        malicious.write_text(json.dumps(modified), encoding="utf-8")
        monkeypatch.setattr(reading, "_READING_PATH", malicious)
        with pytest.raises(ValueError, match="byte digest mismatch"):
            reading.reading_registry()

        # Even if a future generated byte hash is reviewed, source identity,
        # chapter order, copy closure, and locale constraints still fail shut.
        variants = [
            ({**data, "source_sha256": {**data["source_sha256"], "manifest": "0" * 64}},
             "source/version/inactivity mismatch"),
            ({**data, "chapters": list(reversed(data["chapters"]))},
             "chapter identity/locale drift"),
            ({**data, "states": {**data["states"], "EXTRA": {"en": "x", "sv": "x"}}},
             "state copy/locale drift"),
            ({**data, "runtime_activation": True}, "source/version/inactivity mismatch"),
            ({**data, "relations": [
                {**data["relations"][0], "required_descriptors": [
                    data["relations"][0]["required_descriptors"][0], "foreign.candidate",
                ]}, *data["relations"][1:],
            ]}, "relation requires two reviewed feature families"),
        ]
        for obj, message in variants:
            # The test's altered byte pin stands in for a signed regeneration;
            # production's installed pinned SHA never changes.
            payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            malicious.write_bytes(payload)
            monkeypatch.setattr(reading, "_READING_SHA256", sha256(payload).hexdigest())
            reading._load_reading_registry.cache_clear()
            with pytest.raises(ValueError, match=message):
                reading.reading_registry()
    finally:
        monkeypatch.setattr(reading, "_READING_PATH", original_path)
        reading._load_reading_registry.cache_clear()


def test_loading_r1_free_copy_does_not_import_model_provider_or_enable_v4(monkeypatch):
    import sys
    from princess_app.domain.content import reading
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading
    providers = {"openai", "anthropic", "supabase", "boto3", "stripe"}
    before = providers & set(sys.modules)
    reading._load_reading_registry.cache_clear()
    policy = story_policy_from_reviewed_reading()
    assert len(policy.chapters) == 6
    assert providers & set(sys.modules) == before
    # The worker and API require a separate reviewed activation seam; this
    # pure function does not set process-level environmental activation flags.
    assert policy.presentation_version == "presentation/2"


def test_installed_r1_policy_assembles_an_immutable_free_v4_snapshot():
    """First R2-A acceptance: real R1 policy fits the existing gated assembler."""
    from datetime import datetime, timezone
    from princess_app.domain.analysis import analysis_reference
    from princess_app.domain.content import reading
    from princess_app.domain.reports.story import story_policy_from_reviewed_reading
    from princess_app.domain.reports.assembly import assemble_report
    import generate_report_fixtures as fixtures

    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    result = fixtures.load("engine-result.synthetic.json")
    analysis = analysis_reference(
        analysis_id="analysis_r2a", run_id="run_r2a", owner_id="owner_r2a",
        input_asset_id="asset_r2a", input_sha256="0" * 64,
        processed_sha256=result["metadata"]["input_pixels_sha256"],
        created_at=now, engine_version="0.1.0", analysis_config_sha256="1" * 64,
        template=STORY_TEMPLATE_VERSION,
    )
    original_analysis, original_result = copy.deepcopy(analysis), copy.deepcopy(result)
    approved = story_policy_from_reviewed_reading()
    compiled = assemble_report(
        report_id="report_r2a", analysis=analysis, result=result,
        created_at=now, locale="sv", story_policy=approved,
    )
    assert compiled.ok, compiled.issues
    doc = compiled.value.to_dict()
    assert doc["revision"] == 1
    assert doc["premium_overlay_id"] is None
    assert doc["analysis"] == original_analysis
    assert len(doc["facts"]) == 64
    assert len({f["feature_id"] for f in doc["facts"]}) == 64
    assert len({f["fact_id"] for f in doc["facts"]}) == 64
    assert tuple(s["section_id"] for s in doc["sections"]
                 if s["section_id"] in CHAPTER_ORDER) == CHAPTER_ORDER
    assert doc["sections"][-1]["availability"] == "LOCKED"
    assert all(not s["premium_section_id"] for s in doc["sections"])
    assert result == original_result and analysis == original_analysis
    # Saved content is versioned, not reevaluated from user/client input.
    for section in doc["sections"]:
        for content_id in section["content_ids"]:
            if content_id.startswith("content.reading.") or content_id.startswith("content.chapter."):
                assert reading.reading_content_text(content_id, "sv")
