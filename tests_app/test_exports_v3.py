"""R5-F3: durable private v3 export identity, custody and revocation tests.

Only synthetic generated samples; no live model, real images or public flags.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import text

from princess_app.adapters.fakes import SequentialIds
from princess_app.adapters.postgres.access import PostgresReportAccess
from princess_app.adapters.postgres.exports import PostgresExportRepository
from princess_app.adapters.postgres.intake import PostgresIntakeRepository
from princess_app.adapters.postgres.stores import PostgresReportStore
from princess_app.adapters.render.assets import clean_source_raster
from princess_app.application.exports import (
    TEMPLATE_VERSION, V3_TEMPLATE_VERSION, ExportService, ExportWorker,
)
from princess_app.domain.permissions import Decision, Scope
from princess_app.ports.base import InvalidInput, NotFound, Unsupported
from test_intake import Env, NOTICE, erasure
from test_persistence import account, world  # noqa: F401 - fixture re-export
from princess_graphology import __version__ as ENGINE_VERSION


class V3ExportIds(SequentialIds):
    """Export queue IDs cannot alias the analysis fixture's job namespace."""

    def new_id(self, prefix: str) -> str:
        return super().new_id(f"{prefix}_v3export")


class V3Renderer:
    def __init__(self):
        self.v3 = []
        self.v2 = []
        self.during = None

    def render_envelope_v3(self, envelope):
        assert envelope.schema_name == "RenderEnvelope"
        assert envelope.data["renderer_version"] == V3_TEMPLATE_VERSION
        self.v3.append(envelope)
        if self.during:
            self.during()
        return b"%PDF-1.7\n" + hashlib.sha256(envelope.digest.encode()).hexdigest().encode()

    def render(self, view, layout, locale, generated_at):
        self.v2.append((view, layout, locale))
        return b"%PDF-1.7\nlegacy"


class Harness:
    def __init__(self, app_db, worker_db, world):  # noqa: F811
        self.env = env = Env(app_db, worker_db)
        self.owner = account(world, "sub-r5f3").principal_id
        capture, run = env.analysis(self.owner)
        self.capture = capture
        assert env.worker().run_once().outcome == "SUCCEEDED"
        self.report_id = env.intake.status(self.owner, run).report_id
        self.renderer = V3Renderer()
        self.ids = V3ExportIds()

        def build(db, enabled=True):
            return ExportService(
                reports=lambda owner: PostgresReportStore(db, owner),
                access=PostgresReportAccess(db), repo=PostgresExportRepository(db),
                store=env.store, clock=env.clock, ids=self.ids, permissions=env.permissions,
                source_capture=PostgresIntakeRepository(db, engine_version=ENGINE_VERSION).capture_for_asset,
                source_sanitizer=clean_source_raster, private_v3_enabled=enabled,
            )

        self.api = build(app_db)
        self.worker_service = build(worker_db)
        self.worker = ExportWorker(
            service=self.worker_service, renderer=self.renderer,
            worker_id="export_v3_1", context=env.ctx,
        )
        self.disabled = build(app_db, enabled=False)

    def grant_image(self, decision=Decision.GRANT):
        self.env.clock.advance(1)
        self.env.permissions.record(
            subject_id=self.owner, actor_id=self.owner, purpose_id="image_retention",
            scope=Scope("SPECIMEN", self.capture.capture_id),
            decision=decision, notice_version=NOTICE,
        )


@pytest.fixture
def v3(app_db, worker_db, world):  # noqa: F811
    return Harness(app_db, worker_db, world)


def request(v3, *, detail="SUMMARY", image=False):
    return v3.api.request(
        v3.owner, v3.report_id, "A4",
        detail=detail, include_image=image, ctx=v3.env.ctx(),
    )


def test_disabled_v3_is_refused_without_affecting_v2_or_exported_records(v3):
    with pytest.raises(Unsupported, match="render_v3_disabled"):
        v3.disabled.request(v3.owner, v3.report_id, "A4", detail="SUMMARY")
    first = v3.api.request(v3.owner, v3.report_id, "A4")
    assert first.renderer_version == TEMPLATE_VERSION
    assert first.detail == "FULL" and first.include_image is False
    assert v3.worker.run_once().state == "READY"
    assert len(v3.renderer.v2) == 1 and not v3.renderer.v3
    with v3.env.app_db.session(v3.owner) as conn:
        row = conn.execute(text("SELECT template_version, params FROM app.report_export WHERE export_id = :e"),
                           {"e": first.export_id}).first()
    assert row[0] == TEMPLATE_VERSION
    assert row[1] == {"sections": [], "include_image": False, "share_grant_ref": None}


def test_v3_summary_full_persist_and_dedupe_independently_of_v2(v3):
    old = v3.api.request(v3.owner, v3.report_id, "A4")
    summary = request(v3)
    assert summary.renderer_version == V3_TEMPLATE_VERSION
    assert summary.detail == "SUMMARY" and summary.include_image is False
    assert summary.cache_key != old.cache_key
    assert request(v3).export_id == summary.export_id
    full = request(v3, detail="FULL")
    assert full.export_id != summary.export_id
    assert full.cache_key != summary.cache_key
    with v3.env.app_db.session(v3.owner) as conn:
        row = conn.execute(text("SELECT params, template_version FROM app.report_export WHERE export_id = :e"),
                           {"e": summary.export_id}).first()
    assert row[1] == V3_TEMPLATE_VERSION
    assert row[0]["detail"] == "SUMMARY" and row[0]["include_image"] is False
    assert row[0]["render_policy_version"] == "render-policy/3"
    assert row[0]["source_report_digest"] == summary.source_report_digest
    assert row[0]["raster_sha256"] is None
    assert v3.worker.run_once().state == "READY"  # first legacy queued
    assert v3.worker.run_once().state == "READY"
    assert v3.worker.run_once().state == "READY"
    assert len(v3.renderer.v3) == 2
    assert v3.renderer.v3[0].data["detail"] == "SUMMARY"
    payload, ready = v3.api.download(v3.owner, summary.export_id, v3.env.ctx())
    assert ready.renderer_version == V3_TEMPLATE_VERSION and payload.startswith(b"%PDF-")
    assert request(v3).state == "READY"  # never spent a second render
    assert len(v3.renderer.v3) == 2


def test_source_image_requires_current_explicit_specimen_retention_grant(v3):
    with pytest.raises(NotFound, match="source_image_not_available"):
        request(v3, image=True)
    v3.grant_image()
    image = request(v3, image=True)
    noimage = request(v3, image=False)
    assert image.cache_key != noimage.cache_key
    assert image.raster_sha256 is not None
    assert image.evidence_digest is not None
    assert image.renderer_version == V3_TEMPLATE_VERSION
    assert type(image.image_retention_epoch) is int
    assert noimage.image_retention_epoch is None
    assert v3.worker.run_once().state == "READY"
    assert v3.worker.run_once().state == "READY"
    supplied = next(row for row in v3.renderer.v3 if row.data["source_image"] is not None)
    assert supplied.data["view"]["authorized_asset_ids"] == [v3.capture.asset_id]
    assert supplied.data["source_image"]["sha256"] == image.raster_sha256
    v3.grant_image(Decision.WITHDRAW)
    with pytest.raises(NotFound, match="export_stale"):
        v3.api.download(v3.owner, image.export_id, v3.env.ctx())
    assert v3.api.status(v3.owner, image.export_id).state == "REVOKED"
    assert v3.api.download(v3.owner, noimage.export_id, v3.env.ctx())[0].startswith(b"%PDF-")
    assert "ERASED" in {o.action for o in erasure(v3.env).run_once()}


def test_withdrawal_mid_render_fences_publication_and_queues_orphan(v3):
    v3.grant_image()
    row = request(v3, image=True)
    v3.renderer.during = lambda: v3.grant_image(Decision.WITHDRAW)
    result = v3.worker.run_once()
    assert (result.state, result.error_code) == ("FAILED", "projection_changed")
    assert v3.api.status(v3.owner, row.export_id).state == "FAILED"
    assert {out.action for out in erasure(v3.env).run_once()} == {"ERASED"}
    with v3.env.app_db.session(v3.owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.asset WHERE kind='EXPORT'")).scalar() == 0


def test_download_checks_source_rights_again_after_export_bytes_are_read(v3, monkeypatch):
    v3.grant_image()
    row = request(v3, image=True)
    assert v3.worker.run_once().state == "READY"
    original = v3.env.store.read_object
    saved = v3.api.status(v3.owner, row.export_id)
    mutated = False

    def concurrent_withdrawal(stored, ctx):
        nonlocal mutated
        data = original(stored, ctx)
        if stored.asset_id == saved.asset_id and not mutated:
            mutated = True
            v3.grant_image(Decision.WITHDRAW)
        return data

    monkeypatch.setattr(v3.env.store, "read_object", concurrent_withdrawal)
    with pytest.raises(NotFound, match="export_stale"):
        v3.api.download(v3.owner, row.export_id, v3.env.ctx())
    assert mutated
    assert v3.api.status(v3.owner, row.export_id).state == "REVOKED"


def test_v3_publish_fence_refuses_report_revision_changed_during_render(v3):
    row = request(v3)
    claim = v3.worker_service.repo.claim("manual-v3", 120, v3.env.clock.now())
    assert claim.row.export_id == row.export_id
    # An independently valid newer immutable revision must prevent an old
    # in-flight export from becoming READY; no destructive row mutation.
    from princess_app.domain.reports import revise_report
    saved = PostgresReportStore(v3.env.app_db, v3.owner)
    previous = saved.latest(v3.report_id)[1]
    revised = revise_report(previous, created_at=v3.env.clock.now() + timedelta(seconds=1),
                            premium_overlay_id=None)
    assert revised.ok, revised.issues
    saved.append(v3.owner, revised.value)
    stored = v3.env.store.write_derivative(
        "asset_export_test_v3", None, b"%PDF-1.7\nsynthetic", "application/pdf", v3.env.ctx())
    assert v3.worker_service.repo.publish(claim, stored, v3.env.clock.now()) is False


def test_v3_refuses_invalid_persisted_template_and_options(v3):
    row = request(v3)
    with v3.env.app_db.session(v3.owner) as conn:
        conn.execute(text("UPDATE app.report_export SET template_version = 'render-template/unknown' "
                          "WHERE export_id = :e"), {"e": row.export_id})
    with pytest.raises(InvalidInput, match="export_stored_template_invalid"):
        v3.api.status(v3.owner, row.export_id)


@pytest.mark.parametrize("kwargs", [
    {"detail": "summary", "include_image": False},
    {"detail": "FULL", "include_image": "true"},
    {"detail": "SUMMARY", "include_image": True, "layout": "CARD_STORY"},
])
def test_invalid_private_v3_options_never_silently_fall_back_to_legacy(v3, kwargs):
    layout = kwargs.get("layout", "A4")
    with pytest.raises(InvalidInput):
        v3.api.request(v3.owner, v3.report_id, layout,
                       detail=kwargs["detail"], include_image=kwargs["include_image"],
                       ctx=v3.env.ctx())


def test_withdrawal_then_regrant_does_not_resurrect_old_image_cache(v3):
    v3.grant_image()
    old = request(v3, image=True)
    assert v3.worker.run_once().state == "READY"
    old_epoch = old.image_retention_epoch
    v3.grant_image(Decision.WITHDRAW)
    v3.grant_image(Decision.GRANT)
    new = request(v3, image=True)
    assert new.image_retention_epoch > old_epoch
    assert new.cache_key != old.cache_key
    assert new.export_id != old.export_id
    with pytest.raises(NotFound, match="export_stale"):
        v3.api.download(v3.owner, old.export_id, v3.env.ctx())
    assert v3.api.status(v3.owner, old.export_id).state == "REVOKED"
    assert v3.worker.run_once().state == "READY"
    assert v3.api.download(v3.owner, new.export_id, v3.env.ctx())[0].startswith(b"%PDF-")


def test_transactional_publication_refuses_changed_image_permission_epoch(v3):
    v3.grant_image()
    row = request(v3, image=True)
    claim = v3.worker_service.repo.claim("manual-epoch", 120, v3.env.clock.now())
    assert claim.row.image_retention_epoch == row.image_retention_epoch
    v3.grant_image(Decision.WITHDRAW)
    # Even a previously rendered and digested PDF may not be published after
    # revocation. This cannot be repaired by an outside-transaction precheck.
    stored = v3.env.store.write_derivative(
        "asset_epoch_export_v3", None, b"%PDF-1.7\\nsynthetic", "application/pdf", v3.env.ctx())
    assert v3.worker_service.repo.publish(claim, stored, v3.env.clock.now()) is False
