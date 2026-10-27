"""R2-C: saved Free /4 reading is owner-bound, read-only and image-optional.

These are synthetic test documents. In particular, a passing numerical
suitability gate is not evidence of personality, calibration or human value.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

import generate_report_fixtures as fixtures
from princess_app.adapters.fakes import FakeClock
from princess_app.application.reports import InMemoryReportStore, ReportAccess, ReportReader
from princess_app.domain.reports import ProjectionRequest, assemble_report, project_report
from princess_app.domain.reports.story import CHAPTER_ORDER, story_policy_from_reviewed_reading
from princess_app.domain.reports.suitability import ReportSuitability, assess_report_suitability
from princess_app.ports.base import NotFound
from princess_contracts import validate_projection

T0 = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
SOURCE_REF = fixtures.load("analysis-reference.synthetic.json")
SOURCE_RESULT = fixtures.load("engine-result.synthetic.json")
ACTIONS = {"EXPORT": None, "PURCHASE": None, "COMPARE": "comparison_not_available"}


def saved_story(*, locale="en", line_count=3, word_count=3):
    ref = copy.deepcopy(SOURCE_REF)
    ref["versions"]["template"] = "individual-report/4"
    result = copy.deepcopy(SOURCE_RESULT)
    result["measurements"]["PAGE_LINE_COUNT"]["raw_value"] = line_count
    result["measurements"]["PAGE_WORD_COUNT"]["raw_value"] = word_count
    compiled = assemble_report(
        report_id=f"report_story_{locale}_{line_count}_{word_count}",
        analysis=ref, result=result, created_at=T0, locale=locale,
        story_policy=story_policy_from_reviewed_reading(),
    )
    assert compiled.ok, compiled.issues
    return compiled.value


class MutableAccess:
    def __init__(self, source=True):
        self.source = source
        self.calls = []

    def resolve(self, owner_id, report):
        self.calls.append((owner_id, report.digest))
        return ReportAccess(source_image_available=self.source)

    def premium_content(self, owner_id, overlay_id):
        raise AssertionError("Saved Free reads must not fetch Premium content")


def test_story_saved_owner_reads_survive_disabled_writer_and_missing_resolver():
    """The saved source is self-contained; reading never loads current R1."""
    import princess_app.domain.content.reading as source_runtime

    saved = saved_story(locale="sv")
    owner = saved.data["analysis"]["owner_id"]
    store = InMemoryReportStore()
    store.append(owner, saved)
    # The runtime can roll back, disable /4, or lose the active authored pack:
    # a past authorized saved snapshot and its facts must remain readable.
    original_registry = source_runtime._load_reading_registry
    try:
        source_runtime._load_reading_registry = lambda: (_ for _ in ()).throw(AssertionError("No source read on reopen"))
        reader = ReportReader(store, FakeClock(T0))
        view = reader.view(report_id=saved.data["report_id"], principal_id=owner,
                           projection="FREE", actions=ACTIONS)
    finally:
        source_runtime._load_reading_registry = original_registry
    data = view.to_dict()
    assert data["source_revision"] == 1 and data["source_digest"] == saved.data["document_digest"]
    assert data["locale"] == "sv" and len(data["facts"]) == 64
    assert set(CHAPTER_ORDER) <= {section["section_id"] for section in data["sections"]}
    assert data["authorized_asset_ids"] == []
    assert "notice.source_image_unavailable" in [n["localization_key"] for n in data["notices"]]
    assert not any(a["kind"] == "PURCHASE" for a in data["actions"])
    assert next(a for a in data["actions"] if a["kind"] == "EXPORT")["enabled"] is False
    assert validate_projection(saved, view) == ()
    assert store.latest(saved.data["report_id"])[1].digest == saved.digest


def test_story_live_access_is_an_upper_bound_and_does_not_grant_unreleased_actions():
    saved = saved_story()
    owner = saved.data["analysis"]["owner_id"]
    store = InMemoryReportStore()
    store.append(owner, saved)
    rights = MutableAccess(True)
    reader = ReportReader(store, FakeClock(T0), rights)
    view = reader.view(report_id=saved.data["report_id"], principal_id=owner,
                       projection="OWNER", actions=ACTIONS)
    data = view.to_dict()
    assert data["authorized_asset_ids"] == [saved.data["analysis"]["input_asset_id"]]
    assert next(a for a in data["actions"] if a["kind"] == "EXPORT")["reason"] == "report_v4_export_not_released"
    assert next(a for a in data["actions"] if a["kind"] == "PURCHASE")["reason"] == "report_v4_premium_not_released"
    rights.source = False
    withdrawn = reader.view(report_id=saved.data["report_id"], principal_id=owner,
                            projection="FREE", actions=ACTIONS).to_dict()
    assert withdrawn["authorized_asset_ids"] == []
    assert withdrawn["facts"] == data["facts"] and withdrawn["sections"] == data["sections"]
    assert withdrawn["source_digest"] == data["source_digest"]
    assert not any(a["kind"] == "PURCHASE" for a in withdrawn["actions"])
    rights.source = True
    caller_omitted = reader.view(report_id=saved.data["report_id"], principal_id=owner,
                                 projection="OWNER", source_image_available=False)
    assert caller_omitted.data["authorized_asset_ids"] == ()
    before = len(rights.calls)
    with pytest.raises(NotFound):
        reader.view(report_id=saved.data["report_id"], principal_id="different_owner", projection="OWNER")
    assert len(rights.calls) == before  # never reveal source or premium rights to another owner


@pytest.mark.parametrize("locale,line_count,word_count,status", [
    ("en", 3, 3, ReportSuitability.SUPPORTED),
    ("sv", 3, 0, ReportSuitability.PARTIAL),
    ("en", 0, 0, ReportSuitability.UNQUALIFIED),
])
def test_story_partial_and_unqualified_have_no_new_purchase(locale, line_count, word_count, status):
    saved = saved_story(locale=locale, line_count=line_count, word_count=word_count)
    assert assess_report_suitability(saved) is status
    data = project_report(saved, ProjectionRequest(
        "FREE", T0, source_image_available=True, actions=ACTIONS,
    )).value.to_dict()
    assert len(data["facts"]) == 64 and data["locale"] == locale
    if status is not ReportSuitability.SUPPORTED:
        assert not any(a["kind"] == "PURCHASE" for a in data["actions"])
    else:
        assert next(a for a in data["actions"] if a["kind"] == "PURCHASE")["enabled"] is False
    assert next(a for a in data["actions"] if a["kind"] == "EXPORT")["enabled"] is False


def test_historical_report_actions_are_untouched():
    legacy_ref = copy.deepcopy(SOURCE_REF)
    from princess_app.domain.reports.assembly import assemble_report as compile_report
    legacy = compile_report(report_id="report_legacy", analysis=legacy_ref, result=SOURCE_RESULT,
                            created_at=T0, locale="en")
    assert legacy.ok, legacy.issues
    out = project_report(legacy.value, ProjectionRequest("OWNER", T0, actions=ACTIONS)).value.to_dict()
    assert next(a for a in out["actions"] if a["kind"] == "EXPORT")["enabled"] is True
    assert next(a for a in out["actions"] if a["kind"] == "PURCHASE")["enabled"] is True


def test_saved_story_evidence_requires_real_saved_region_lineage():
    from princess_app.domain.evidence import build_evidence_bundle
    from princess_contracts import canonical_digest, compile_document
    from princess_app.ports.base import PermanentFailure

    ref = copy.deepcopy(SOURCE_REF)
    ref["versions"]["template"] = "individual-report/4"
    bundle = build_evidence_bundle(fixtures.load("evidence-payload.synthetic.json"),
                                   ref, "evidence_story_reader")
    assert bundle.ok, bundle.issues
    outcome = assemble_report(
        report_id="report_story_evidence", analysis=ref, result=SOURCE_RESULT,
        created_at=T0, locale="en", evidence=bundle.value,
        story_policy=story_policy_from_reviewed_reading(),
    )
    assert outcome.ok, outcome.issues
    original = outcome.value
    owner = original.data["analysis"]["owner_id"]
    store = InMemoryReportStore()
    store.append(owner, original)
    store.bind_evidence(original.data["report_id"], bundle.value)
    reader = ReportReader(store, FakeClock(T0))
    assert reader.evidence(report_id=original.data["report_id"],
                           principal_id=owner)["bundle_id"] == "evidence_story_reader"
    with pytest.raises(NotFound):
        reader.evidence(report_id=original.data["report_id"], principal_id="stranger")

    forged = original.to_dict()
    fact = next(f for f in forged["facts"] if f["source_region_ids"])
    fact["source_region_ids"] = ["region_missing_from_saved_bundle"]
    forged["document_digest"] = None
    forged["document_digest"] = canonical_digest(forged)
    compiled = compile_document("ReportDocument", forged)
    assert compiled.ok, compiled.issues
    forged_store = InMemoryReportStore()
    forged_store.append(owner, compiled.value)
    forged_store.bind_evidence(original.data["report_id"], bundle.value)
    with pytest.raises(PermanentFailure) as failed:
        ReportReader(forged_store, FakeClock(T0)).evidence(
            report_id=original.data["report_id"], principal_id=owner,
        )
    assert failed.value.code == "story_evidence_region_invalid"
