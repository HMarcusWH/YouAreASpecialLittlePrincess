"""Report exports: PDF documents and share cards (T21).

One saved report revision, one authorized projection, many layouts:

* Documents (A4, Letter) render the ``EXPORT`` projection; cards (square,
  story) render a ``SHARE`` projection limited to the sections the owner
  chose. The renderer receives only that projection — no database, storage
  credential, model key or network — and draws facts it is given; it has no
  measurement, scoring or model code (``apps/render``).
* The cache key is the digest of the authorized projection without its
  generation time, plus layout and template. A revoked image, an erased
  Premium payload or a new revision changes the projection and so the key.
* The worker re-derives the projection before and after rendering and
  refuses to publish if it changed. Retrieval re-derives it again: a stale
  export is revoked and its bytes are queued for erasure. Copies already
  downloaded cannot be recalled, and the API says so.

The source image is not embedded yet; every export carries the "source image
omitted" notice rather than silently dropping it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from princess_contracts import ValidatedDocument, canonical_json

from ...ports.base import (
    CallContext,
    Clock,
    Conflict,
    DeadlineExceeded,
    IdGenerator,
    InvalidInput,
    NotFound,
    PermanentFailure,
    PortError,
    RateLimited,
    TransientUnavailable,
    Unsupported,
)
from ...ports.storage import ObjectStore, StoredObject
from ..reports import ReportAccessResolver, ReportReader, ReportStore, ShareAccess

TEMPLATE_VERSION = "render-template/1"
DOCUMENT_LAYOUTS = frozenset({"A4", "LETTER"})
CARD_LAYOUTS = frozenset({"CARD_SQUARE", "CARD_STORY"})
MEDIA_TYPES = {"A4": "application/pdf", "LETTER": "application/pdf",
               "CARD_SQUARE": "image/png", "CARD_STORY": "image/png"}
MAGIC = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n"}
MAX_EXPORT_BYTES = 10 * 1024 * 1024
MAX_CARD_SECTIONS = 8
MAX_ATTEMPTS = 2
NOT_RECALLABLE = "downloaded_copies_cannot_be_recalled"


@dataclass(frozen=True)
class ExportRequest:
    report_id: str
    layout: str
    sections: tuple[str, ...] = ()  # cards only: the sections the owner chose to disclose

    @property
    def projection(self) -> str:
        return "SHARE" if self.layout in CARD_LAYOUTS else "EXPORT"

    def params(self) -> dict[str, Any]:
        return {"sections": sorted(self.sections), "include_image": False}


@dataclass(frozen=True)
class ExportRow:
    export_id: str
    owner_id: str
    report_id: str
    revision: int
    layout: str
    sections: tuple[str, ...]
    cache_key: str
    state: str  # QUEUED | READY | FAILED | REVOKED
    created_at: datetime
    asset_id: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    version_ref: str | None = None
    error_code: str | None = None
    completed_at: datetime | None = None

    def request(self) -> ExportRequest:
        return ExportRequest(self.report_id, self.layout, self.sections)


@dataclass(frozen=True)
class ClaimedExport:
    job_id: str
    fencing_token: int
    attempts: int
    row: ExportRow


class Renderer(Protocol):
    def render(self, view: Mapping[str, Any], layout: str, locale: str, generated_at: str) -> bytes:
        """Render trusted templates over one authorized projection. Raises
        ``InvalidInput``/``PermanentFailure`` for input it refuses and
        ``TransientUnavailable`` when it could not run."""
        ...


class ExportRepository(Protocol):
    def request(self, row: ExportRow, job_id: str) -> ExportRow:
        """Create the export and its job, or return the export for the same
        ``(owner, cache_key)``; a FAILED or REVOKED one is queued again."""
        ...

    def get(self, owner_id: str, export_id: str) -> ExportRow | None: ...

    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> ClaimedExport | None: ...

    def publish(self, claim: ClaimedExport, stored: StoredObject, now: datetime) -> bool:
        """Fenced on the job lease, a live owner and report and a QUEUED export:
        record the asset and mark the export READY. False when fenced."""
        ...

    def fail(self, claim: ClaimedExport, code: str, now: datetime, *, retry: bool,
             orphan_asset_id: str | None = None) -> str:
        """Requeue (bounded) or fail the export. ``orphan_asset_id`` names bytes
        that were stored but never published; their erasure is queued in the
        same transaction."""
        ...

    def revoke(self, owner_id: str, export_id: str, reason: str, at: datetime) -> None:
        """Mark REVOKED and queue durable erasure of its bytes, atomically."""
        ...


def cache_key(view: ValidatedDocument, request: ExportRequest) -> str:
    content = {k: v for k, v in view.to_dict().items() if k != "generated_at"}
    material = {"view": content, "layout": request.layout, "template": TEMPLATE_VERSION}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def check_rendered(data: bytes, media_type: str) -> None:
    if not data or len(data) > MAX_EXPORT_BYTES:
        raise PermanentFailure("render_output_size")
    if not data.startswith(MAGIC[media_type]):
        raise PermanentFailure("render_output_type")


@dataclass
class ExportService:
    reports: Callable[[str], ReportStore]
    access: ReportAccessResolver | None
    repo: ExportRepository
    store: ObjectStore
    clock: Clock
    ids: IdGenerator
    sharing_enabled: Callable[[], bool] = field(default=lambda: False)

    def projection(self, owner_id: str, request: ExportRequest) -> ValidatedDocument:
        """The authorized projection an export may show, derived now."""
        reader = ReportReader(self.reports(owner_id), self.clock, self.access)
        if request.projection == "EXPORT":
            return reader.view(report_id=request.report_id, principal_id=owner_id, projection="EXPORT",
                               include_source_image=False)
        # A card is the owner's own share preview: ownership is checked by an
        # owner read before the SHARE projection is compiled for their scope.
        owned = reader.view(report_id=request.report_id, principal_id=owner_id, projection="OWNER")
        known = {s["section_id"] for s in owned.data["sections"]}
        if not set(request.sections) <= known:
            raise InvalidInput("unknown_section")
        return reader.view(report_id=request.report_id, principal_id=None, projection="SHARE",
                           share=ShareAccess(request.report_id, frozenset(request.sections)))

    def request(self, owner_id: str, report_id: str, layout: str, sections: tuple[str, ...] = ()) -> ExportRow:
        if layout not in MEDIA_TYPES:
            raise InvalidInput("unknown_layout")
        if layout in CARD_LAYOUTS:
            if not self.sharing_enabled():
                raise Unsupported("sharing_disabled")
            if not sections or len(sections) > MAX_CARD_SECTIONS or len(set(sections)) != len(sections):
                raise InvalidInput("card_sections_required")
        elif sections:
            raise InvalidInput("sections_apply_to_cards_only")
        request = ExportRequest(report_id, layout, tuple(sorted(sections)))
        view = self.projection(owner_id, request)
        row = ExportRow(export_id=self.ids.new_id("export"), owner_id=owner_id, report_id=report_id,
                        revision=view.data["source_revision"], layout=layout, sections=request.sections,
                        cache_key=cache_key(view, request), state="QUEUED", created_at=self.clock.now())
        return self.repo.request(row, self.ids.new_id("job"))

    def status(self, owner_id: str, export_id: str) -> ExportRow:
        row = self.repo.get(owner_id, export_id)
        if row is None:
            raise NotFound("export_not_found")
        return row

    def download(self, owner_id: str, export_id: str, ctx: CallContext) -> tuple[bytes, ExportRow]:
        """Protected retrieval re-authorizes against the live projection."""
        row = self.status(owner_id, export_id)
        if row.state != "READY":
            raise Conflict("export_not_ready", detail=row.state)
        try:
            current = cache_key(self.projection(owner_id, row.request()), row.request())
        except (NotFound, InvalidInput):
            current = None  # the report or a disclosed section is gone
        if current != row.cache_key:
            self.repo.revoke(owner_id, export_id, "export_stale", self.clock.now())
            raise NotFound("export_stale")
        stored = StoredObject(row.asset_id, row.version_ref, row.sha256, row.size_bytes, row.media_type)
        data = self.store.read_object(stored, ctx)
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise PermanentFailure("export_digest_mismatch")
        return data, row


@dataclass(frozen=True)
class ExportOutcome:
    export_id: str
    state: str
    error_code: str | None = None


class ExportWorker:
    """Claims export jobs, renders through the sandboxed renderer and stores
    the bytes. Holds database access; the renderer does not."""

    def __init__(self, *, service: ExportService, renderer: Renderer, worker_id: str,
                 context: Callable[[], CallContext], lease_seconds: int = 120) -> None:
        self._service = service
        self._renderer = renderer
        self._worker_id = worker_id
        self._context = context
        self._lease = lease_seconds

    def run_once(self) -> ExportOutcome | None:
        svc = self._service
        claim = svc.repo.claim(self._worker_id, self._lease, svc.clock.now())
        if claim is None:
            return None
        row = claim.row
        request = row.request()

        def fail(code: str, *, retry: bool = False, orphan: str | None = None) -> ExportOutcome:
            state = svc.repo.fail(claim, code, svc.clock.now(), retry=retry and claim.attempts < MAX_ATTEMPTS,
                                  orphan_asset_id=orphan)
            return ExportOutcome(row.export_id, state, code)

        try:
            view = svc.projection(row.owner_id, request)
        except (NotFound, InvalidInput) as exc:
            return fail(exc.code)
        if cache_key(view, request) != row.cache_key:
            return fail("projection_changed")  # e.g. image or Premium revoked since the request
        media_type = MEDIA_TYPES[row.layout]
        try:
            data = self._renderer.render(view.to_dict(), row.layout, view.data["locale"], view.data["generated_at"])
            check_rendered(data, media_type)
        except (TransientUnavailable, DeadlineExceeded, RateLimited) as exc:
            return fail(exc.code, retry=True)
        except PortError as exc:
            return fail(exc.code)
        ctx = self._context()
        asset_id = svc.ids.new_id("asset")
        try:
            stored = svc.store.write_derivative(asset_id, None, data, media_type, ctx)
        except PortError as exc:
            return fail(exc.code, retry=True, orphan=asset_id)  # a partial write may exist
        try:
            unchanged = cache_key(svc.projection(row.owner_id, request), request) == row.cache_key
        except (NotFound, InvalidInput):
            unchanged = False
        if unchanged and svc.repo.publish(claim, stored, svc.clock.now()):
            return ExportOutcome(row.export_id, "READY")
        # Never published, so never retrievable; the queued erasure removes the bytes.
        return fail("fenced" if unchanged else "projection_changed", orphan=asset_id)


__all__ = ["CARD_LAYOUTS", "ClaimedExport", "DOCUMENT_LAYOUTS", "ExportOutcome", "ExportRepository", "ExportRequest",
           "ExportRow", "ExportService", "ExportWorker", "MAX_EXPORT_BYTES", "MEDIA_TYPES", "NOT_RECALLABLE",
           "Renderer", "TEMPLATE_VERSION", "cache_key", "check_rendered"]
