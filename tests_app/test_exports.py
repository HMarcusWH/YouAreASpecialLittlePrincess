"""T21 exports: authorized projection in, fenced bytes out, live retrieval checks."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from princess_app.adapters.fakes import SequentialIds
from princess_app.adapters.postgres.access import PostgresReportAccess
from princess_app.adapters.postgres.exports import PostgresExportRepository
from princess_app.adapters.postgres.stores import PostgresReportStore
from princess_app.adapters.render import SubprocessRenderer
from princess_app.application.exports import TEMPLATE_VERSION, ExportService, ExportWorker, render_asset_id
from princess_app.application.reports import ReportReader
from princess_app.domain.permissions import Decision, Scope
from princess_app.ports.base import (
    Conflict,
    InvalidInput,
    NotAuthorized,
    NotFound,
    PermanentFailure,
    RateLimited,
    TransientUnavailable,
    Unsupported,
)
from test_intake import NOTICE, Env, erasure
from test_persistence import account, world  # noqa: F401 - fixture re-export


class FakeRenderer:
    """Deterministic stand-in: bytes derived from exactly the projection it got."""

    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.during = None

    def render(self, view, layout, locale, generated_at):
        self.calls.append({"view": view, "layout": layout, "locale": locale, "generated_at": generated_at})
        if self.during:
            self.during()
        if self.fail_with:
            raise self.fail_with
        digest = hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest().encode()
        return (b"%PDF-1.7\n" if layout in ("A4", "LETTER") else b"\x89PNG\r\n\x1a\n") + digest


def test_renderer_template_v2_is_the_cache_authority():
    assert TEMPLATE_VERSION == "render-template/2"


class ExportIds(SequentialIds):
    """Distinct from the intake/analysis generators sharing this database."""

    def new_id(self, prefix: str) -> str:
        return super().new_id(f"{prefix}_ex")


class Exports:
    def __init__(self, app_db, worker_db, world, sharing=True):  # noqa: F811
        self.env = env = Env(app_db, worker_db)
        self.owner = account(world, "sub-e").principal_id
        capture, run_id = env.analysis(self.owner)
        assert env.worker().run_once().outcome == "SUCCEEDED"
        self.capture_id = capture.capture_id
        self.report_id = env.intake.status(self.owner, run_id).report_id
        self.renderer = FakeRenderer()
        self.sharing = sharing

        ids = ExportIds()

        def service(db):
            return ExportService(reports=lambda owner: PostgresReportStore(db, owner),
                                 access=PostgresReportAccess(db), repo=PostgresExportRepository(db),
                                 store=env.store, clock=env.clock, ids=ids,
                                 sharing_enabled=lambda: self.sharing, permissions=env.permissions)

        self.api = service(app_db)
        self.worker = ExportWorker(service=service(worker_db), renderer=self.renderer, worker_id="export-1",
                                   context=env.ctx)

    def owner_view(self):
        reader = ReportReader(PostgresReportStore(self.env.app_db, self.owner), self.env.clock,
                              PostgresReportAccess(self.env.app_db))
        return reader.view(report_id=self.report_id, principal_id=self.owner, projection="OWNER").to_dict()


@pytest.fixture
def ex(app_db, worker_db, world):  # noqa: F811
    return Exports(app_db, worker_db, world)


def test_a_pdf_renders_the_saved_facts_and_is_retrieved_by_its_owner(ex, world):  # noqa: F811
    first = ex.api.request(ex.owner, ex.report_id, "A4")
    assert first.state == "QUEUED" and ex.api.request(ex.owner, ex.report_id, "A4").export_id == first.export_id
    done = ex.worker.run_once()
    assert (done.export_id, done.state) == (first.export_id, "READY")
    [call] = ex.renderer.calls
    rendered = call["view"]
    assert rendered["projection"] == "EXPORT" and rendered["actions"] == [] and rendered["authorized_asset_ids"] == []
    assert rendered["facts"] == ex.owner_view()["facts"]  # the same facts as the web/native projection
    assert "notice.source_image_omitted" in {n["localization_key"] for n in rendered["notices"]}
    data, row = ex.api.download(ex.owner, first.export_id, ex.env.ctx())
    assert data.startswith(b"%PDF-") and row.media_type == "application/pdf" and row.size_bytes == len(data)
    again = ex.api.request(ex.owner, ex.report_id, "A4")
    assert again.export_id == first.export_id and again.state == "READY"  # cached by projection
    assert ex.worker.run_once() is None and len(ex.renderer.calls) == 1
    stranger = account(world, "sub-x").principal_id
    with pytest.raises(NotFound):
        ex.api.status(stranger, first.export_id)
    with pytest.raises(NotFound):
        ex.api.download(stranger, first.export_id, ex.env.ctx())
    with pytest.raises(NotFound):
        ex.api.request(stranger, ex.report_id, "A4")


def share_grant(ex, ref="share_0001", decision=Decision.GRANT):
    ex.env.clock.advance(1)
    ex.env.permissions.record(subject_id=ex.owner, actor_id=ex.owner, purpose_id="ordinary_sharing",
                              scope=Scope("SHARE_GRANT", ref), decision=decision, notice_version=NOTICE)
    return ref


def test_cards_render_only_the_disclosed_sections_and_need_sharing(ex):
    sections = [s for s in ex.owner_view()["sections"] if s["fact_ids"]]
    chosen = sections[0]["section_id"]
    with pytest.raises(InvalidInput):
        ex.api.request(ex.owner, ex.report_id, "CARD_SQUARE", (chosen,))  # no grant named
    with pytest.raises(NotAuthorized):
        ex.api.request(ex.owner, ex.report_id, "CARD_SQUARE", (chosen,), "share_0001")  # none recorded
    grant = share_grant(ex)
    card = ex.api.request(ex.owner, ex.report_id, "CARD_SQUARE", (chosen,), grant)
    assert ex.worker.run_once().state == "READY"
    view = ex.renderer.calls[-1]["view"]
    assert view["projection"] == "SHARE" and [s["section_id"] for s in view["sections"]] == [chosen]
    assert {f["fact_id"] for f in view["facts"]} == set(sections[0]["fact_ids"])
    data, row = ex.api.download(ex.owner, card.export_id, ex.env.ctx())
    assert data.startswith(b"\x89PNG") and row.media_type == "image/png"
    with pytest.raises(InvalidInput):
        ex.api.request(ex.owner, ex.report_id, "CARD_SQUARE", (), grant)
    with pytest.raises(InvalidInput):
        ex.api.request(ex.owner, ex.report_id, "CARD_SQUARE", ("section.invented",), grant)
    with pytest.raises(InvalidInput):
        ex.api.request(ex.owner, ex.report_id, "A4", (chosen,))
    with pytest.raises(InvalidInput):
        ex.api.request(ex.owner, ex.report_id, "POSTER")
    # Withdrawing the sharing grant ends retrieval of the card (and erases it).
    share_grant(ex, grant, Decision.WITHDRAW)
    with pytest.raises(NotFound):
        ex.api.download(ex.owner, card.export_id, ex.env.ctx())
    assert ex.api.status(ex.owner, card.export_id).state == "REVOKED"
    ex.sharing = False
    with pytest.raises(Unsupported):
        ex.api.request(ex.owner, ex.report_id, "CARD_STORY", (chosen,), grant)


def test_a_projection_change_during_rendering_is_not_published(ex):
    requested = ex.api.request(ex.owner, ex.report_id, "LETTER")

    def erase_original():  # the source image is erased while the page renders
        ex.env.repo.request_retention_review(ex.owner, ex.capture_id, ex.env.clock.now())
        assert "ERASED" in {o.action for o in erasure(ex.env).run_once()}

    ex.renderer.during = erase_original
    done = ex.worker.run_once()
    assert (done.state, done.error_code) == ("FAILED", "projection_changed")
    assert ex.api.status(ex.owner, requested.export_id).state == "FAILED"
    # The unpublished bytes were queued for erasure and are gone once it runs.
    assert {o.action for o in erasure(ex.env).run_once()} == {"ERASED"}
    ex.renderer.during = None
    retry = ex.api.request(ex.owner, ex.report_id, "LETTER")  # a new projection, a new export
    assert retry.export_id != requested.export_id and ex.worker.run_once().state == "READY"
    rendered = ex.renderer.calls[-1]["view"]
    assert "notice.source_image_unavailable" in {n["localization_key"] for n in rendered["notices"]}


def test_stale_exports_are_revoked_at_retrieval_and_their_bytes_erased(ex):
    requested = ex.api.request(ex.owner, ex.report_id, "A4")
    assert ex.worker.run_once().state == "READY"
    asset_id = ex.api.status(ex.owner, requested.export_id).asset_id
    ex.env.repo.request_retention_review(ex.owner, ex.capture_id, ex.env.clock.now())
    erasure(ex.env).run_once()  # the original goes, so the authorized projection changes
    with pytest.raises(NotFound):
        ex.api.download(ex.owner, requested.export_id, ex.env.ctx())
    assert ex.api.status(ex.owner, requested.export_id).state == "REVOKED"
    assert {o.action for o in erasure(ex.env).run_once()} == {"ERASED"}
    assert ex.env.store.verify_deletion(asset_id, ex.env.ctx())


def test_deleting_the_capture_revokes_and_erases_its_exports(ex):
    requested = ex.api.request(ex.owner, ex.report_id, "A4")
    queued = ex.api.request(ex.owner, ex.report_id, "LETTER")
    assert ex.worker.run_once().state == "READY"
    asset_id = ex.api.status(ex.owner, requested.export_id).asset_id
    ex.env.intake.delete_capture(ex.owner, ex.capture_id)
    assert ex.api.status(ex.owner, requested.export_id).state == "REVOKED"
    assert ex.api.status(ex.owner, queued.export_id).state == "REVOKED"
    assert ex.worker.run_once() is None and len(ex.renderer.calls) == 1  # the queued one never renders
    with pytest.raises(Conflict):
        ex.api.download(ex.owner, requested.export_id, ex.env.ctx())
    assert "ERASED" in {o.action for o in erasure(ex.env).run_once()}
    assert ex.env.store.verify_deletion(asset_id, ex.env.ctx())


def test_renderer_failures_are_bounded_and_explicit(ex):
    requested = ex.api.request(ex.owner, ex.report_id, "A4")
    ex.renderer.fail_with = TransientUnavailable("render_timeout")
    assert ex.worker.run_once().state == "QUEUED"
    done = ex.worker.run_once()
    assert (done.state, done.error_code) == ("FAILED", "render_timeout")
    ex.renderer.fail_with = PermanentFailure("render_failed")
    assert ex.api.request(ex.owner, ex.report_id, "A4").export_id == requested.export_id  # a FAILED one requeues
    assert ex.worker.run_once().error_code == "render_failed"
    ex.renderer.fail_with = None
    ex.renderer.render = lambda view, layout, locale, generated_at: b"<html>not a pdf</html>"
    ex.api.request(ex.owner, ex.report_id, "A4")
    assert ex.worker.run_once().error_code == "render_output_type"
    with ex.env.app_db.session(ex.owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.asset WHERE kind = 'EXPORT'")).scalar() == 0


def test_the_renderer_child_gets_only_the_projection():
    stub = Path(__file__).with_name("render_stub.py")
    renderer = SubprocessRenderer([sys.executable, str(stub)], timeout_s=10)
    out = json.loads(renderer.render({"projection": "EXPORT"}, "A4", "sv", "2026-09-27T12:00:00Z")[len(b"%PDF-"):])
    assert out["input"] == {"view": {"projection": "EXPORT"}, "layout": "A4", "locale": "sv",
                            "generated_at": "2026-09-27T12:00:00Z"}
    assert set(out["env"]) <= {"PATH", "HOME", "PRINCESS_CHROMIUM", "LC_CTYPE"}  # no database URL, keys or secrets
    for layout, error in (("BAD_INPUT", InvalidInput), ("CRASH", PermanentFailure), ("SLOW", TransientUnavailable)):
        with pytest.raises(error):
            SubprocessRenderer([sys.executable, str(stub)], timeout_s=1).render({}, layout, "en", "x")
    with pytest.raises(TransientUnavailable):
        SubprocessRenderer(["/nonexistent/renderer"]).render({}, "A4", "en", "x")


def test_a_crashed_render_is_found_from_its_fencing_token_and_erased(ex):
    requested = ex.api.request(ex.owner, ex.report_id, "A4")
    queue = PostgresExportRepository(ex.env.worker_db)
    crashed = queue.claim("crashing", 30, ex.env.clock.now())
    # The dead worker wrote bytes but never recorded them.
    ex.env.store.write_derivative(render_asset_id(requested.export_id, crashed.fencing_token), None, b"%PDF-1.7",
                                  "application/pdf", ex.env.ctx())
    ex.env.clock.advance(31)
    assert ex.worker.run_once().state == "READY"  # reclaimed; the orphan's erasure is queued on the way
    assert "ERASED" in {o.action for o in erasure(ex.env).run_once()}
    assert ex.env.store.verify_deletion(render_asset_id(requested.export_id, crashed.fencing_token), ex.env.ctx())


def test_the_daily_export_budget_counts_completed_renders(ex, monkeypatch):
    import princess_app.adapters.postgres.exports as exports_adapter

    monkeypatch.setattr(exports_adapter, "MAX_EXPORTS_PER_DAY", 1)
    ex.api.request(ex.owner, ex.report_id, "A4")
    assert ex.worker.run_once().state == "READY"
    with pytest.raises(RateLimited):
        ex.api.request(ex.owner, ex.report_id, "LETTER")  # nothing pending, but the day's budget is used
