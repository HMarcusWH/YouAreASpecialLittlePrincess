"""R5-F1 export authority: generated inputs only, no user handwriting.

These tests exercise the real deterministic engine + saved ReportDocument /
EvidenceBundle + server projection rather than inventing region coordinates.
"""
from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from PIL import Image

from princess_app.adapters.imaging import decode_image
from princess_app.adapters.render.assets import clean_source_raster
from princess_app.application.exports.assets import (
    CHUNK_SIZE, MAX_CHUNKS, MAX_ENVELOPE_BYTES, MAX_RASTER_BYTES,
    compile_free_render_envelope, prepare_authorized_render_assets,
)
from princess_app.application.reports import ReportAccess
from princess_app.domain.analysis import analysis_reference
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.reports import ProjectionRequest, assemble_report, project_report
from princess_app.ports.base import CallContext, Environment, InvalidInput, NotFound, PermanentFailure
from princess_app.ports.storage import StoredObject
from princess_graphology import GraphologyEngine

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
CTX = CallContext("corr_synthetic_render", Environment.TEST, NOW + timedelta(minutes=1))


class SourceStore:
    def __init__(self, blob):
        self.blob = blob
        self.reads = 0

    def read_object(self, stored, context):
        assert stored.asset_id == "asset_render_synthetic"
        self.reads += 1
        return self.blob


class CurrentAccess:
    def __init__(self, allowed=True, revoke_after_first=False):
        self.allowed = allowed
        self.revoke_after_first = revoke_after_first
        self.calls = 0

    def resolve(self, owner_id, report):
        assert owner_id == "owner_render_synthetic"
        self.calls += 1
        available = self.allowed and not (self.revoke_after_first and self.calls > 1)
        return ReportAccess(source_image_available=available)


def sample_source(*, orientation=1, jpeg=False, add_metadata=False):
    image = Image.new("RGB", (420, 260), (248, 247, 244))
    pixels = np.asarray(image).copy()
    cv2.putText(pixels, "INK TEST", (30, 110), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, (16, 19, 25), 2, cv2.LINE_AA)
    image = Image.fromarray(pixels, "RGB")
    raw = io.BytesIO()
    if jpeg:
        exif = Image.Exif()
        exif[0x0112] = orientation
        if add_metadata:
            exif[0x010E] = "SYNTHETIC PRIVATE-LIKE DESCRIPTION MUST NOT LEAK"
        image.save(raw, "JPEG", exif=exif.tobytes())
        return raw.getvalue(), "image/jpeg"
    image.save(raw, "PNG")
    return raw.getvalue(), "image/png"


def saved_sample(blob, media_type):
    decoded = decode_image(blob, media_type)
    result, payload = GraphologyEngine(deskew_enabled=False).analyze_with_evidence(
        decoded.pixels, source="synthetic-r5-f1",
    )
    original_hash = hashlib.sha256(blob).hexdigest()
    ref = analysis_reference(
        analysis_id="analysis_render_synthetic",
        run_id="run_render_synthetic",
        owner_id="owner_render_synthetic",
        input_asset_id="asset_render_synthetic",
        input_sha256=original_hash,
        processed_sha256=result.metadata["input_pixels_sha256"],
        created_at=NOW, engine_version="0.1.0",
        analysis_config_sha256="f" * 64,
        template="individual-report/2",
    )
    bundle = build_evidence_bundle(payload, ref, "evidence_render_synthetic")
    assert bundle.ok, bundle.issues
    made = assemble_report(
        report_id="report_render_synthetic", analysis=ref, result=result.to_dict(),
        created_at=NOW, locale="en", evidence=bundle.value,
    )
    assert made.ok, made.issues
    view = project_report(made.value, ProjectionRequest(
        projection="EXPORT", generated_at=NOW, source_image_available=True,
        include_source_image=True,
    ))
    assert view.ok, view.issues
    source = StoredObject("asset_render_synthetic", "v1", original_hash, len(blob), media_type)
    return made.value, view.value, bundle.value, source


@pytest.fixture(scope="module")
def fixture():
    blob, mime = sample_source()
    return blob, mime, *saved_sample(blob, mime)


def test_source_raster_is_oriented_clean_bounded_and_exactly_reversible(fixture):
    blob, _mime, report, view, evidence, source = fixture
    store, access = SourceStore(blob), CurrentAccess()
    prepared = prepare_authorized_render_assets(
        owner_id="owner_render_synthetic", report_owner_id="owner_render_synthetic",
        report=report, view=view, evidence=evidence, source=source,
        store=store, access=access, ctx=CTX, sanitize=clean_source_raster,
    )
    assert store.reads == 1 and access.calls == 2
    assert prepared.width == 420 and prepared.height == 260
    assert prepared.media_type in ("image/png", "image/jpeg")
    assert 1 <= len(prepared.data_base64_chunks) <= MAX_CHUNKS
    assert all(0 < len(chunk) <= CHUNK_SIZE for chunk in prepared.data_base64_chunks)
    encoded = "".join(prepared.data_base64_chunks)
    payload = base64.b64decode(encoded, validate=True)
    assert len(payload) <= MAX_RASTER_BYTES
    assert hashlib.sha256(payload).hexdigest() == prepared.sha256
    with Image.open(io.BytesIO(payload)) as render_image:
        assert render_image.getexif().get(0x0112) in (None, 1)
        assert render_image.size == (420, 260)
        assert render_image.info.get("exif") is None

    candidate = compile_free_render_envelope(
        report=report, view=view, evidence=evidence,
        source_image=prepared, layout="A4", detail="SUMMARY",
    )
    assert candidate.schema_name == "RenderEnvelope"
    assert candidate.data["renderer_version"] == "render-template/3"
    assert candidate.data["render_policy_version"] == "render-policy/3"
    assert candidate.data["source_image"]["sha256"] == prepared.sha256
    assert candidate.data["premium"] is None
    assert candidate.data["view"]["source_digest"] == report.data["document_digest"]
    assert len(candidate.to_dict()["source_image"]["data_base64_chunks"]) >= 1
    assert len(str(candidate.to_dict()).encode("utf-8")) < MAX_ENVELOPE_BYTES
    assert fixture[0] == blob  # no mutation of the verified input bytes


def test_exif_orientation_and_synthetic_metadata_are_removed():
    raw, mime = sample_source(orientation=6, jpeg=True, add_metadata=True)
    report, view, evidence, source = saved_sample(raw, mime)
    prepared = prepare_authorized_render_assets(
        owner_id="owner_render_synthetic", report_owner_id="owner_render_synthetic",
        report=report, view=view, evidence=evidence, source=source,
        store=SourceStore(raw), access=CurrentAccess(), ctx=CTX, sanitize=clean_source_raster,
    )
    assert (prepared.width, prepared.height) == (260, 420)
    decoded = base64.b64decode("".join(prepared.data_base64_chunks))
    assert b"SYNTHETIC PRIVATE-LIKE" not in decoded
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.size == (260, 420)
        assert image.getexif().get(0x0112) in (None, 1)
        assert image.info.get("exif") is None


def test_absent_image_is_authoritative_and_does_not_make_up_a_picture(fixture):
    _blob, _mime, report, view, evidence, _source = fixture
    unpictured = project_report(report, ProjectionRequest(
        projection="EXPORT", generated_at=NOW,
        source_image_available=False, include_source_image=False,
    )).value
    envelope = compile_free_render_envelope(
        report=report, view=unpictured, evidence=evidence,
        layout="LETTER", detail="FULL",
    )
    assert envelope.data["source_image"] is None
    assert envelope.data["view"]["facts"] == unpictured.data["facts"]
    assert not envelope.data["view"]["authorized_asset_ids"]
    assert envelope.data["premium"] is None


@pytest.mark.parametrize("scenario", [
    "wrong_owner", "no_live_right", "revoked_during_read", "wrong_asset",
    "wrong_asset_digest", "corrupted_bytes",
])
def test_source_authority_refuses_cross_owner_or_stale_bytes(fixture, scenario):
    blob, _mime, report, view, evidence, source = fixture
    store = SourceStore(blob + b"tamper") if scenario == "corrupted_bytes" else SourceStore(blob)
    access = CurrentAccess(allowed=scenario != "no_live_right",
                           revoke_after_first=scenario == "revoked_during_read")
    if scenario == "wrong_asset":
        source = replace(source, asset_id="asset_different")
    if scenario == "wrong_asset_digest":
        source = replace(source, sha256="0" * 64)
    with pytest.raises((NotFound, PermanentFailure)):
        prepare_authorized_render_assets(
            owner_id="owner_render_synthetic",
            report_owner_id=("other_owner" if scenario == "wrong_owner"
                             else "owner_render_synthetic"),
            report=report, view=view, evidence=evidence, source=source,
            store=store, access=access, ctx=CTX, sanitize=clean_source_raster,
        )
    if scenario in ("wrong_owner", "no_live_right", "wrong_asset", "wrong_asset_digest"):
        assert store.reads == 0


def test_missing_or_wrong_evidence_fails_before_source_read(fixture):
    blob, _mime, report, view, evidence, source = fixture
    store, access = SourceStore(blob), CurrentAccess()
    with pytest.raises(InvalidInput, match="render_evidence"):
        prepare_authorized_render_assets(
            owner_id="owner_render_synthetic", report_owner_id="owner_render_synthetic",
            report=report, view=view, evidence=None, source=source,
            store=store, access=access, ctx=CTX, sanitize=clean_source_raster,
        )
    assert store.reads == 0
    # No cleaned raster may be attached if the caller requested an image-free
    # projection, even though the underlying report has a retained original.
    unpictured = project_report(report, ProjectionRequest(
        projection="EXPORT", generated_at=NOW,
        source_image_available=True, include_source_image=False,
    )).value
    with pytest.raises((InvalidInput, NotFound)):
        prepare_authorized_render_assets(
            owner_id="owner_render_synthetic", report_owner_id="owner_render_synthetic",
            report=report, view=unpictured, evidence=evidence, source=source,
            store=store, access=access, ctx=CTX, sanitize=clean_source_raster,
        )
    assert store.reads == 0


def test_canonical_chunks_refuse_tampering_and_source_disclosure_without_rights(fixture):
    blob, _mime, report, view, evidence, source = fixture
    image = prepare_authorized_render_assets(
        owner_id="owner_render_synthetic", report_owner_id="owner_render_synthetic",
        report=report, view=view, evidence=evidence, source=source,
        store=SourceStore(blob), access=CurrentAccess(), ctx=CTX, sanitize=clean_source_raster,
    )
    chunks = image.data_base64_chunks
    with pytest.raises(InvalidInput, match="render_raster"):
        replace(image, data_base64_chunks=chunks + ("###",))
    with pytest.raises(InvalidInput, match="render_raster"):
        replace(image, sha256="0" * 64)
    with pytest.raises(InvalidInput, match="render_raster"):
        replace(image, width=1601)
    without_image = project_report(report, ProjectionRequest(
        projection="EXPORT", generated_at=NOW,
        source_image_available=False, include_source_image=False,
    )).value
    with pytest.raises(InvalidInput, match="render_image_not_authorized"):
        compile_free_render_envelope(
            report=report, view=without_image, evidence=evidence,
            layout="A4", detail="SUMMARY", source_image=image,
        )
    with pytest.raises(InvalidInput, match="render_source_evidence_required"):
        compile_free_render_envelope(
            report=report, view=view, evidence=None,
            layout="A4", detail="SUMMARY", source_image=image,
        )
    # A cleaned and valid image from a different source/revision/evidence
    # cannot be reattached merely because its own SHA-256 still verifies.
    for wrong in (
        {"source_input_sha256": "1" * 64},
        {"source_asset_id": "another_source"},
        {"report_digest": "1" * 64},
        {"report_revision": image.report_revision + 1},
        {"evidence_digest": "1" * 64},
    ):
        with pytest.raises(InvalidInput, match="render_image_source_mismatch"):
            compile_free_render_envelope(
                report=report, view=view, evidence=evidence,
                layout="A4", detail="SUMMARY",
                source_image=replace(image, **wrong),
            )


def test_new_envelope_is_separate_from_existing_legacy_export_identity(fixture):
    _blob, _mime, report, view, evidence, _source = fixture
    from princess_app.application.exports import TEMPLATE_VERSION
    assert TEMPLATE_VERSION == "render-template/2"
    for detail in ("SUMMARY", "FULL"):
        compiled = compile_free_render_envelope(
            report=report, view=view, evidence=evidence,
            layout="A4", detail=detail,
        )
        assert compiled.data["detail"] == detail
        assert compiled.data["source_image"] is None
    for value in ("", "summary", "TYPO"):
        with pytest.raises(InvalidInput, match="render_detail_invalid"):
            compile_free_render_envelope(
                report=report, view=view, layout="A4", detail=value,
            )


def test_private_v3_service_resolves_exact_owner_and_saved_evidence(fixture):
    """The private assembly seam can use real report and capture ports."""
    from princess_app.adapters.fakes import FakeClock, SequentialIds
    from princess_app.application.exports import ExportService
    from princess_app.application.intake import CaptureRow
    from princess_app.application.reports import InMemoryReportStore

    blob, mime, report, _view, evidence, source = fixture
    reports = InMemoryReportStore()
    reports.append("owner_render_synthetic", report)
    reports.bind_evidence(report.data["report_id"], evidence)
    capture = CaptureRow(
        capture_id="capture_render_synthetic",
        owner_id="owner_render_synthetic",
        upload_id="upload_render_synthetic",
        asset_id=source.asset_id,
        media_type=mime,
        width=420,
        height=260,
        exif_orientation=1,
        sha256=source.sha256,
        version_ref=source.version_ref,
        size_bytes=source.size_bytes,
    )
    store = SourceStore(blob)
    lookups = []

    def authorized_capture(owner, asset_id):
        lookups.append((owner, asset_id))
        return capture

    service = ExportService(
        reports=lambda _owner: reports, access=CurrentAccess(), repo=None,
        store=store, clock=FakeClock(NOW), ids=SequentialIds(),
        source_capture=authorized_capture, source_sanitizer=clean_source_raster,
    )
    no_image = service.private_free_v3_candidate(
        "owner_render_synthetic", report.data["report_id"], "A4",
        detail="SUMMARY", include_image=False,
    )
    assert no_image.data["source_image"] is None
    assert len(no_image.data["view"]["facts"]) == 64
    assert not lookups and store.reads == 0
    with_image = service.private_free_v3_candidate(
        "owner_render_synthetic", report.data["report_id"], "LETTER",
        detail="FULL", include_image=True, ctx=CTX,
    )
    assert with_image.data["source_image"] is not None
    assert with_image.data["evidence"]["bundle_id"] == report.data["evidence_bundle_id"]
    assert with_image.data["view"]["source_digest"] == report.data["document_digest"]
    assert lookups == [("owner_render_synthetic", source.asset_id)]
    assert store.reads == 1
    with pytest.raises(NotFound, match="report_not_found"):
        service.private_free_v3_candidate(
            "another_owner", report.data["report_id"], "A4",
        )
    assert store.reads == 1


def test_private_v3_source_failure_does_not_affect_legacy_export(fixture):
    from princess_app.adapters.fakes import FakeClock, SequentialIds
    from princess_app.application.exports import ExportRequest, ExportService, TEMPLATE_VERSION
    from princess_app.application.reports import InMemoryReportStore

    blob, _mime, report, _view, evidence, _source = fixture
    reports = InMemoryReportStore()
    reports.append("owner_render_synthetic", report)
    reports.bind_evidence(report.data["report_id"], evidence)
    service = ExportService(
        reports=lambda _owner: reports, access=CurrentAccess(),
        repo=None, store=SourceStore(blob),
        clock=FakeClock(NOW), ids=SequentialIds(),
    )
    with pytest.raises(Exception) as exc:
        service.private_free_v3_candidate(
            "owner_render_synthetic", report.data["report_id"], "A4",
            detail="FULL", include_image=True, ctx=CTX,
        )
    assert getattr(exc.value, "code", None) == "render_v3_source_adapter_not_configured"
    assert TEMPLATE_VERSION == "render-template/2"
    legacy = service.projection(
        "owner_render_synthetic", ExportRequest(report.data["report_id"], "A4"),
    )
    assert legacy.data["projection"] == "EXPORT"
    assert legacy.data["authorized_asset_ids"] == ()


def test_raw_source_sha_is_not_enough_if_decoded_analyzed_pixels_mismatch(fixture, monkeypatch):
    from princess_app.adapters.render import assets

    blob, _mime, report, view, evidence, source = fixture
    # Deliberately change the independent decoded-pixel identity without
    # changing the signed stored source bytes: stale/different analysis fails.
    monkeypatch.setattr(assets, "input_pixels_sha256", lambda _pixels: "0" * 64)
    with pytest.raises(PermanentFailure, match="render_processed_pixels_mismatch"):
        prepare_authorized_render_assets(
            owner_id="owner_render_synthetic",
            report_owner_id="owner_render_synthetic",
            report=report, view=view, evidence=evidence, source=source,
            store=SourceStore(blob), access=CurrentAccess(), ctx=CTX, sanitize=clean_source_raster,
        )


def test_free_envelope_rejects_saved_paid_projection_instead_of_laundering_content():
    import json
    from pathlib import Path
    from princess_contracts import compile_document
    from princess_app.domain.reports import (
        PremiumAccess, PremiumAuthorization, revise_report,
    )

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures/reports/report-document.v2.json"
    base = compile_document("ReportDocument", json.loads(fixture_path.read_text(encoding="utf-8")))
    assert base.ok, base.issues
    revised = revise_report(
        base.value, created_at=NOW + timedelta(minutes=1),
        premium_overlay_id="overlay_synthetic_paid",
    )
    assert revised.ok, revised.issues
    paid = revised.value
    authority = PremiumAuthorization(
        report_id=paid.data["report_id"],
        overlay_id="overlay_synthetic_paid",
        state=PremiumAccess.UNLOCKED,
    )
    projection = project_report(paid, ProjectionRequest(
        projection="EXPORT", generated_at=NOW, premium=authority,
        include_source_image=False,
    ))
    assert projection.ok, projection.issues
    assert any(s["premium_section_id"] is not None for s in projection.value.data["sections"])
    with pytest.raises(InvalidInput, match="render_free_premium_scope_invalid"):
        compile_free_render_envelope(
            report=paid, view=projection.value, layout="A4", detail="FULL",
        )


def test_private_v3_candidate_rejects_nonboolean_image_selection(fixture):
    from princess_app.adapters.fakes import FakeClock, SequentialIds
    from princess_app.application.exports import ExportService
    from princess_app.application.reports import InMemoryReportStore

    _blob, _mime, report, _view, evidence, _source = fixture
    reports = InMemoryReportStore()
    reports.append("owner_render_synthetic", report)
    reports.bind_evidence(report.data["report_id"], evidence)
    service = ExportService(
        reports=lambda _owner: reports, access=CurrentAccess(),
        repo=None, store=None, clock=FakeClock(NOW), ids=SequentialIds(),
    )
    with pytest.raises(InvalidInput, match="render_v3_image_flag_invalid"):
        service.private_free_v3_candidate(
            "owner_render_synthetic", report.data["report_id"], "A4",
            include_image="true",
        )
