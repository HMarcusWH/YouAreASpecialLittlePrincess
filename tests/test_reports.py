"""T09 report assembly, revisions and authorized projections."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import generate_report_fixtures as fixtures
from princess_app.adapters.fakes import FakeClock
from princess_app.application.reports import InMemoryReportStore, ReportReader, ShareAccess
from princess_app.domain.analysis import analysis_reference
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.reports.assembly import build_sections
from princess_app.domain.reports import (
    PremiumAccess,
    PremiumAuthorization,
    ProjectionRequest,
    assemble_report,
    check_revision,
    facts_from_result,
    project_report,
    revise_report,
)
from princess_app.domain.reports.template import (BASE_TEMPLATE_VERSION, FACT_SECTIONS,
                                                    HIGHLIGHT_POLICY_VERSION, HIGHLIGHT_PRESENTATION_VERSION,
                                                    HIGHLIGHT_TEMPLATE_VERSION)
from princess_app.ports.base import Conflict, NotAuthorized, NotFound
from princess_contracts import compile_document, validate_projection
from princess_graphology import GraphologyEngine
from princess_graphology.measurements import IMPLEMENTED_FEATURE_IDS

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
RESULT = fixtures.load("engine-result.synthetic.json")
PAYLOAD = fixtures.load("evidence-payload.synthetic.json")
REFERENCE = fixtures.load("analysis-reference.synthetic.json")
ACTIONS = fixtures.OWNER_ACTIONS


def evidence(reference=REFERENCE):
    return build_evidence_bundle(PAYLOAD, reference, "evidence_1").value


def report(**overrides):
    args = dict(report_id="report_1", analysis=REFERENCE, result=RESULT, created_at=T0, locale="en",
                evidence=evidence())
    args.update(overrides)
    outcome = assemble_report(**args)
    assert outcome.ok, outcome.issues[:5]
    return outcome.value


def codes(outcome):
    return {issue.code for issue in outcome.issues}


def test_template_covers_every_free_feature_exactly_once():
    listed = [f for _, _, ids in FACT_SECTIONS for f in ids]
    assert len(listed) == len(set(listed))
    assert set(listed) == set(IMPLEMENTED_FEATURE_IDS)


def test_report_binds_all_facts_and_is_deterministic():
    doc = report()
    data = doc.to_dict()
    assert len(data["facts"]) == len(RESULT["measurements"]) == 64
    in_sections = [fid for s in data["sections"] for fid in s["fact_ids"]]
    assert sorted(in_sections) == sorted(f["fact_id"] for f in data["facts"])
    assert report().digest == doc.digest
    assert data["evidence_bundle_id"] == "evidence_1"


def test_missing_stays_missing_and_values_are_never_coerced():
    blank = GraphologyEngine().analyze(np.full((80, 120), 255, np.uint8)).to_dict()
    ref = analysis_reference(analysis_id="a2", run_id="r2", owner_id="owner_fixture_1", input_asset_id="asset_2",
                             input_sha256="0" * 64, processed_sha256=blank["metadata"]["input_pixels_sha256"],
                             created_at=T0,
                             engine_version="0.1.0", analysis_config_sha256="1" * 64)
    data = report(result=blank, analysis=ref, evidence=None).to_dict()
    missing = [f for f in data["facts"] if f["availability"] == "MISSING"]
    assert missing and all(f["value"] is None and f["quality"]["missing_reason"] for f in missing)
    by_id = {s["section_id"]: s for s in data["sections"]}
    assert by_id["section.slant"]["availability"] == "MISSING"
    assert by_id["section.sample"]["availability"] == "READY"  # exact image dimensions


def test_compound_highlight_is_uncalibrated_when_any_support_is_uncalibrated():\n    facts = [\n        {\n            "fact_id": "fact.GLYPH_WIDTH_CV", "feature_id": "GLYPH_WIDTH_CV",\n            "availability": "READY", "value": 0.35, "quality": {"n_observations": 20},\n        },\n        {\n            "fact_id": "fact.GLYPH_HEIGHT_CV", "feature_id": "GLYPH_HEIGHT_CV",\n            "availability": "UNCALIBRATED", "value": 0.15, "quality": {"n_observations": 20},\n        },\n    ]\n    sections = build_sections(facts, reference_claims=(), premium_overlay_id=None,\n                              template_version=HIGHLIGHT_TEMPLATE_VERSION)\n    highlight = next(section for section in sections if section["section_id"] == "section.highlight.primary")\n    assert highlight["content_ids"] == ["content.highlight.v1.size.width_more_variable"]\n    assert highlight["availability"] == "UNCALIBRATED"\n\ndef test_highlight_template_pins_presentation_authority():
    from princess_app.domain.content import HIGHLIGHT_POLICY_VERSION as RUNTIME_POLICY_VERSION, PRESENTATION_VERSION
    assert HIGHLIGHT_PRESENTATION_VERSION == PRESENTATION_VERSION == "presentation/1"
    assert HIGHLIGHT_POLICY_VERSION == RUNTIME_POLICY_VERSION == "highlight-policy/1"


def test_current_template_persists_broad_server_owned_highlights():
    current = copy.deepcopy(REFERENCE)
    current["versions"]["template"] = HIGHLIGHT_TEMPLATE_VERSION
    data = report(analysis=current, evidence=None).to_dict()
    highlights = [section for section in data["sections"] if section["section_id"].startswith("section.highlight.")]
    assert [section["section_id"] for section in highlights] == [
        "section.highlight.primary", "section.highlight.secondary.1", "section.highlight.secondary.2",
    ]
    assert [section["content_ids"][0] for section in highlights] == [
        "content.highlight.v1.slant.right.almost_all",
        "content.highlight.v1.layout.margins_asymmetric",
        "content.highlight.v1.baseline.angle_stable",
    ]
    assert all(section["fact_ids"] for section in highlights)
    assert data["analysis"]["versions"]["template"] == "individual-report/2"


def test_v2_revision_preserves_selected_highlights_and_base_fact_coverage():
    current = copy.deepcopy(REFERENCE)
    current["versions"]["template"] = HIGHLIGHT_TEMPLATE_VERSION
    first = report(analysis=current, evidence=None)
    first_data = first.to_dict()
    base_fact_ids = [
        fact_id
        for section in first_data["sections"]
        if not section["section_id"].startswith("section.highlight.")
        for fact_id in section["fact_ids"]
    ]
    assert sorted(base_fact_ids) == sorted(fact["fact_id"] for fact in first_data["facts"])
    first_highlights = [
        section for section in first_data["sections"]
        if section["section_id"].startswith("section.highlight.")
    ]
    second = revise_report(first, created_at=T0 + timedelta(minutes=1), premium_overlay_id="overlay_v2").value
    second_highlights = [
        section for section in second.to_dict()["sections"]
        if section["section_id"].startswith("section.highlight.")
    ]
    assert second_highlights == first_highlights
    assert check_revision(first, second) == ()

def test_legacy_template_never_gains_highlights_on_revision():
    assert REFERENCE["versions"]["template"] == BASE_TEMPLATE_VERSION
    first = report()
    assert not any(section["section_id"].startswith("section.highlight.") for section in first.data["sections"])
    second = revise_report(first, created_at=T0 + timedelta(minutes=1), premium_overlay_id="overlay_legacy").value
    assert not any(section["section_id"].startswith("section.highlight.") for section in second.data["sections"])


def test_highlights_are_not_silently_disclosed_by_existing_share_scopes():
    current = copy.deepcopy(REFERENCE)
    current["versions"]["template"] = HIGHLIGHT_TEMPLATE_VERSION
    doc = report(analysis=current, evidence=None)
    share = project_report(doc, ProjectionRequest("SHARE", T0, share_scope=frozenset({"section.slant"}))).value
    assert [section["section_id"] for section in share.data["sections"]] == ["section.slant"]
    assert not any(section["section_id"].startswith("section.highlight.") for section in share.data["sections"])


def test_v2_no_candidate_emits_ineligible_first_reveal_fallback():
    blank = GraphologyEngine().analyze(np.full((80, 120), 255, np.uint8)).to_dict()
    ref = analysis_reference(analysis_id="a3", run_id="r3", owner_id="owner_fixture_1", input_asset_id="asset_3",
                             input_sha256="0" * 64, processed_sha256=blank["metadata"]["input_pixels_sha256"],
                             created_at=T0, engine_version="0.1.0", analysis_config_sha256="1" * 64,
                             template=HIGHLIGHT_TEMPLATE_VERSION)
    data = report(result=blank, analysis=ref, evidence=None).to_dict()
    highlight = next(section for section in data["sections"] if section["section_id"] == "section.highlight.primary")
    assert highlight["availability"] == "INELIGIBLE"
    assert highlight["fact_ids"] == []
    assert highlight["content_ids"] == ["content.highlight.v1.none"]


def test_no_reference_and_no_traditional_is_honest():
    data = report().to_dict()
    ref = next(s for s in data["sections"] if s["section_id"] == "section.reference")
    assert ref["availability"] == "INELIGIBLE" and ref["fact_ids"] == []
    keys = {n["localization_key"] for n in data["notices"]}
    assert {"notice.reference_unavailable", "notice.traditional_not_included", "notice.proxy_uncalibrated"} <= keys
    assert data["reference_claims"] == []
    premium = next(s for s in data["sections"] if s["section_id"] == "section.premium")
    assert premium["availability"] == "LOCKED" and premium["premium_section_id"] is None


def test_free_projection_never_carries_premium_content():
    premium = revise_report(report(), created_at=T0 + timedelta(hours=1), premium_overlay_id="overlay_9").value
    unlocked = PremiumAuthorization("report_1", "overlay_9", PremiumAccess.UNLOCKED)
    free = project_report(premium, ProjectionRequest("FREE", T0, premium=unlocked, actions=ACTIONS))
    assert free.ok
    text = json.dumps(free.value.to_dict())
    assert "overlay_9" not in text and '"AI"' not in text
    owner = project_report(premium, ProjectionRequest("OWNER", T0, premium=unlocked)).value
    assert any(s["premium_section_id"] == "premium.overlay_9" for s in owner.data["sections"])


@pytest.mark.parametrize("authorization", [
    None,
    PremiumAuthorization("report_1", "overlay_9", PremiumAccess.REVOKED),
    PremiumAuthorization("report_1", "overlay_9", PremiumAccess.NONE),
    PremiumAuthorization("report_other", "overlay_9", PremiumAccess.UNLOCKED),  # another report
    PremiumAuthorization("report_1", "overlay_old", PremiumAccess.UNLOCKED),    # another overlay
])
def test_premium_requires_current_unlock_bound_to_this_snapshot(authorization):
    premium = revise_report(report(), created_at=T0, premium_overlay_id="overlay_9").value
    assert "PREMIUM_NOT_AUTHORIZED" in codes(project_report(premium, ProjectionRequest("PREMIUM", T0,
                                                                                       premium=authorization)))
    owner = project_report(premium, ProjectionRequest("OWNER", T0, premium=authorization)).value
    assert all(s["premium_section_id"] is None for s in owner.data["sections"])
    if authorization is not None and authorization.state is PremiumAccess.REVOKED:
        assert any(n["localization_key"] == "notice.premium_revoked" for n in owner.data["notices"])


def test_share_scope_limits_sections_facts_assets_and_actions():
    doc = report()
    share = project_report(doc, ProjectionRequest("SHARE", T0, share_scope=frozenset({"section.slant"}),
                                                  actions=ACTIONS)).value.to_dict()
    assert [s["section_id"] for s in share["sections"]] == ["section.slant"]
    assert all(f["feature_id"].startswith("SLANT_") for f in share["facts"])
    assert share["actions"] == [] and share["authorized_asset_ids"] == []
    with_image = project_report(doc, ProjectionRequest("SHARE", T0,
                                                       share_scope=frozenset({"section.slant", "source_image"})))
    assert with_image.value.data["authorized_asset_ids"] == (REFERENCE["input_asset_id"],)


def test_revoked_image_and_export_without_image():
    doc = report()
    revoked = project_report(doc, ProjectionRequest("OWNER", T0, source_image_available=False)).value.to_dict()
    assert revoked["authorized_asset_ids"] == []
    assert any(n["localization_key"] == "notice.source_image_unavailable" for n in revoked["notices"])
    export = project_report(doc, ProjectionRequest("EXPORT", T0, include_source_image=False)).value.to_dict()
    assert export["authorized_asset_ids"] == [] and export["actions"] == []
    assert any(n["localization_key"] == "notice.source_image_omitted" for n in export["notices"])


def test_foreign_evidence_and_non_free_methods_and_schema_drift_fail():
    other = copy.deepcopy(REFERENCE)
    other["run_id"] = "run_other"
    foreign = build_evidence_bundle(PAYLOAD, other, "evidence_other").value
    outcome = assemble_report(report_id="r", analysis=REFERENCE, result=RESULT, created_at=T0, locale="en",
                              evidence=foreign)
    assert codes(outcome) == {"EVIDENCE_ANALYSIS_MISMATCH"}
    learned = copy.deepcopy(RESULT)
    learned["measurements"]["SLANT_ANGLE_MEAN"]["method_version"] = "sigver_representation_v1"
    assert "NON_FREE_METHOD" in codes(assemble_report(report_id="r", analysis=REFERENCE, result=learned,
                                                      created_at=T0, locale="en"))
    drift = copy.deepcopy(RESULT)
    drift["metadata"]["schema_version"] = "0.9"
    assert codes(assemble_report(report_id="r", analysis=REFERENCE, result=drift, created_at=T0,
                                 locale="en")) == {"RESULT_SCHEMA_DRIFT"}


def test_missing_value_cannot_be_smuggled_as_zero():
    bad = copy.deepcopy(RESULT)
    feature = next(k for k, m in bad["measurements"].items() if m["raw_value"] is not None
                   and m["confidence_kind"] == "UNCALIBRATED")
    bad["measurements"][feature].update(raw_value=0.0, quality_flag="MISSING", missing_reason="x")
    facts, _ = facts_from_result(bad)
    fact = next(f for f in facts if f["feature_id"] == feature)
    assert fact["availability"] == "MISSING" and fact["value"] is None


def test_source_regions_are_coarsened_within_contract_bounds():
    big = copy.deepcopy(RESULT)
    regions = [{"region_id": "page_0", "scope": "PAGE", "box": [0, 0, 500, 500], "parent_id": None, "confidence": None}]
    regions += [{"region_id": f"component_{i}", "scope": "COMPONENT", "box": [i, 0, 1, 1], "parent_id": "page_0",
                 "confidence": None} for i in range(300)]
    big["regions"] = regions
    big["measurements"]["SLANT_ANGLE_MEAN"]["source_regions"] = [f"component_{i}" for i in range(300)]
    fact = next(f for f in facts_from_result(big)[0] if f["feature_id"] == "SLANT_ANGLE_MEAN")
    assert fact["source_region_ids"] == ["page_0"]


def test_revisions_carry_facts_and_reject_silent_rebenchmark():
    first = report()
    second = revise_report(first, created_at=T0 + timedelta(minutes=5), premium_overlay_id="overlay_1").value
    assert check_revision(first, second) == ()
    assert second.data["facts"] == first.data["facts"] and second.data["revision"] == 2
    rebenchmarked = copy.deepcopy(second.to_dict())
    rebenchmarked["analysis"]["versions"]["benchmark_release"] = "bench_2027"
    rebenchmarked["document_digest"] = None
    from princess_contracts import canonical_digest
    rebenchmarked["document_digest"] = canonical_digest(rebenchmarked)
    candidate = compile_document("ReportDocument", rebenchmarked).value
    assert "REVISION_MUTATES_ANALYSIS" in {i.code for i in check_revision(first, candidate)}
    assert "REVISION_BEFORE_PREVIOUS" in codes(revise_report(first, created_at=T0 - timedelta(seconds=1),
                                                             premium_overlay_id=None))


def test_views_cannot_be_forged_against_another_revision():
    first = report()
    second = revise_report(first, created_at=T0, premium_overlay_id="overlay_1").value
    view = project_report(first, ProjectionRequest("FREE", T0)).value
    assert {i.code for i in validate_projection(second, view)} >= {"PROJECTION_REVISION_MISMATCH",
                                                                   "PROJECTION_DIGEST_MISMATCH"}


def test_reader_enforces_ownership_and_share_grants():
    store = InMemoryReportStore()
    owner = REFERENCE["owner_id"]
    first = report()
    store.append(owner, first)
    with pytest.raises(NotAuthorized):
        store.append("intruder", revise_report(first, created_at=T0, premium_overlay_id="o").value)
    with pytest.raises(Conflict):
        store.append(owner, first)  # same revision again
    reader = ReportReader(store, FakeClock(T0))
    assert reader.view(report_id="report_1", principal_id=owner, projection="FREE").data["projection"] == "FREE"
    for principal, report_id in (("someone_else", "report_1"), (owner, "report_guess")):
        with pytest.raises(NotFound):
            reader.view(report_id=report_id, principal_id=principal, projection="OWNER")
    with pytest.raises(NotFound):
        reader.view(report_id="report_1", principal_id=None, projection="SHARE",
                    share=ShareAccess("report_1", frozenset({"section.slant"}), revoked=True))
    shared = reader.view(report_id="report_1", principal_id=None, projection="SHARE",
                         share=ShareAccess("report_1", frozenset({"section.slant"})))
    assert [s["section_id"] for s in shared.data["sections"]] == ["section.slant"]
    with pytest.raises(NotAuthorized):
        reader.view(report_id="report_1", principal_id=owner, projection="PREMIUM")


def test_shared_fixtures_are_current():
    outputs = fixtures.build()
    stale = [n for n, text in outputs.items() if (fixtures.FIXTURES / n).read_text(encoding="utf-8") != text]
    assert stale == []


def test_result_must_come_from_this_analysis_and_be_complete():
    other = copy.deepcopy(REFERENCE)
    other["processed_sha256"] = "e" * 64
    assert codes(assemble_report(report_id="r", analysis=other, result=RESULT, created_at=T0,
                                 locale="en")) == {"RESULT_ANALYSIS_MISMATCH"}
    partial = copy.deepcopy(RESULT)
    del partial["measurements"]["SLANT_ANGLE_MEAN"]
    assert codes(assemble_report(report_id="r", analysis=REFERENCE, result=partial, created_at=T0,
                                 locale="en")) == {"INCOMPLETE_RESULT"}
    untemplated = copy.deepcopy(REFERENCE)
    untemplated["versions"]["template"] = None
    assert codes(assemble_report(report_id="r", analysis=untemplated, result=RESULT, created_at=T0,
                                 locale="en")) == {"TEMPLATE_VERSION_MISMATCH"}


def test_persistence_guard_rejects_revisions_that_hide_facts_or_change_locale():
    from princess_contracts import canonical_digest
    first = report()
    base = revise_report(first, created_at=T0, premium_overlay_id="o").value.to_dict()
    hidden = copy.deepcopy(base)
    hidden["sections"][0]["fact_ids"] = []
    relocale = copy.deepcopy(base)
    relocale["locale"] = "sv"
    for doc, code in ((hidden, "REVISION_SECTIONS_NOT_DERIVED"), (relocale, "REVISION_MUTATES_LOCALE")):
        doc["document_digest"] = None
        doc["document_digest"] = canonical_digest(doc)
        candidate = compile_document("ReportDocument", doc)
        assert candidate.ok, candidate.issues[:3]
        assert code in {i.code for i in check_revision(first, candidate.value)}


def test_traditional_or_unsupported_statuses_are_never_relabelled():
    traditional = copy.deepcopy(RESULT)
    traditional["measurements"]["SLANT_ANGLE_MEAN"]["evidence_status"] = "TRADITIONAL_GRAPHOLOGY"
    assert "UNSUPPORTED_EVIDENCE_STATUS" in codes(assemble_report(
        report_id="r", analysis=REFERENCE, result=traditional, created_at=T0, locale="en"))


def test_persistence_guard_rejects_reordered_revision_times():
    first = report()
    earlier = copy.deepcopy(revise_report(first, created_at=T0, premium_overlay_id="o").value.to_dict())
    earlier["created_at"] = "2026-09-27T11:00:00Z"
    from princess_contracts import canonical_digest
    earlier["document_digest"] = None
    earlier["document_digest"] = canonical_digest(earlier)
    candidate = compile_document("ReportDocument", earlier).value
    assert "REVISION_BEFORE_PREVIOUS" in {i.code for i in check_revision(first, candidate)}


def test_reports_with_reference_claims_fail_closed_until_the_view_contract_carries_them():
    doc = report().to_dict()
    doc["reference_claims"] = [{"feature_id": "SLANT_ANGLE_MEAN", "cohort_id": "c1", "benchmark_release_id": "b1",
                                "writer_n": 100, "percentile": 50.0, "uncertainty": None, "methodology_key": "m"}]
    doc["analysis"]["versions"]["benchmark_release"] = "b1"
    from princess_contracts import canonical_digest
    doc["document_digest"] = None
    doc["document_digest"] = canonical_digest(doc)
    claimed = compile_document("ReportDocument", doc)
    assert claimed.ok, claimed.issues[:3]
    assert codes(project_report(claimed.value, ProjectionRequest("OWNER", T0))) == {"REFERENCE_PROJECTION_UNSUPPORTED"}
