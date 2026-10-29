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
    NotAuthorized,
    NotFound,
    PermanentFailure,
    PortError,
    RateLimited,
    TransientUnavailable,
    Unsupported,
    require_opaque_id,
)
from ...ports.storage import ObjectStore, StoredObject
from ...domain.permissions import Scope
from ..permissions import PermissionService
from ..reports import ReportAccessResolver, ReportReader, ReportStore, ShareAccess
from ..intake import CaptureRow
from .assets import CleanSourceRaster, compile_free_render_envelope, prepare_authorized_render_assets

TEMPLATE_VERSION = "render-template/2"
V3_TEMPLATE_VERSION = "render-template/3"
V3_FONT_IDENTITY = "dossier-print-fonts/1"
V3_DETAILS = frozenset({"SUMMARY", "FULL"})
DOCUMENT_LAYOUTS = frozenset({"A4", "LETTER"})
CARD_LAYOUTS = frozenset({"CARD_SQUARE", "CARD_STORY"})
MEDIA_TYPES = {"A4": "application/pdf", "LETTER": "application/pdf",
               "CARD_SQUARE": "image/png", "CARD_STORY": "image/png"}
MAGIC = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n"}
MAX_EXPORT_BYTES = 10 * 1024 * 1024
MAX_CARD_SECTIONS = 8
MAX_ATTEMPTS = 2
NOT_RECALLABLE = "downloaded_copies_cannot_be_recalled"
SHARING_PURPOSE = "ordinary_sharing"


@dataclass(frozen=True)
class ExportRequest:
    report_id: str
    layout: str
    sections: tuple[str, ...] = ()  # cards only: the sections the owner chose to disclose
    share_grant_ref: str | None = None  # cards only: the ordinary_sharing grant they fall under
    renderer_version: str = TEMPLATE_VERSION
    detail: str = "FULL"
    include_image: bool = False
    source_report_digest: str | None = None
    raster_sha256: str | None = None
    evidence_digest: str | None = None

    @property
    def projection(self) -> str:
        return "SHARE" if self.layout in CARD_LAYOUTS else "EXPORT"

    def params(self) -> dict[str, Any]:
        result = {"sections": sorted(self.sections), "include_image": False,
                  "share_grant_ref": self.share_grant_ref}
        if self.renderer_version == V3_TEMPLATE_VERSION:
            result.update({
                "include_image": self.include_image, "detail": self.detail,
                "source_report_digest": self.source_report_digest,
                "raster_sha256": self.raster_sha256,
                "evidence_digest": self.evidence_digest,
                "font_identity": V3_FONT_IDENTITY,
                "render_policy_version": "render-policy/3",
            })
        return result


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

    share_grant_ref: str | None = None
    renderer_version: str = TEMPLATE_VERSION
    detail: str = "FULL"
    include_image: bool = False
    source_report_digest: str | None = None
    raster_sha256: str | None = None
    evidence_digest: str | None = None

    def request(self) -> ExportRequest:
        return ExportRequest(self.report_id, self.layout, self.sections, self.share_grant_ref,
                             self.renderer_version, self.detail, self.include_image,
                             self.source_report_digest, self.raster_sha256, self.evidence_digest)


@dataclass(frozen=True)
class ClaimedExport:
    job_id: str
    fencing_token: int
    attempts: int
    row: ExportRow


class Renderer(Protocol):
    def render(self, view: Mapping[str, Any], layout: str, locale: str, generated_at: str) -> bytes:
        """Legacy, stable render-template/2 input."""
        ...

    def render_envelope_v3(self, envelope: ValidatedDocument) -> bytes:
        """Explicit credential-free render-template/3 child, never a model call."""
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
    material = {"view": content, "layout": request.layout, "template": TEMPLATE_VERSION,
                "share_grant_ref": request.share_grant_ref}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def v3_cache_key(envelope: ValidatedDocument) -> str:
    """Hash exact authorized saved content, source/evidence rights and print policy.

    The cleaned raster's *digest* goes into the key, never its private base64.
    Changing revision, evidence, source, disclosure, localization, size,
    template or content changes the identity; generation clock does not.
    """
    if not isinstance(envelope, ValidatedDocument) or envelope.schema_name != "RenderEnvelope":
        raise InvalidInput("render_v3_envelope_required")
    content = envelope.to_dict()
    if content["renderer_version"] != V3_TEMPLATE_VERSION or content["premium"] is not None:
        raise InvalidInput("render_v3_envelope_invalid")
    view = dict(content["view"])
    view.pop("generated_at", None)
    evidence = content["evidence"]
    source = content["source_image"]
    material = {
        "template": V3_TEMPLATE_VERSION, "font_identity": V3_FONT_IDENTITY,
        "policy": content["render_policy_version"],
        "presentation": content["presentation_version"],
        "layout": content["layout"], "detail": content["detail"],
        "locale": content["locale"], "view": view,
        "evidence_digest": hashlib.sha256(canonical_json(evidence).encode()).hexdigest() if evidence else None,
        "raster": None if source is None else {
            key: source[key] for key in ("media_type", "sha256", "width", "height")
        },
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def render_asset_id(export_id: str, fencing_token: int) -> str:
    """The asset an attempt writes, derivable before the write: a crashed
    attempt's bytes can be found and erased from the job's fencing token."""
    return "asset_" + hashlib.sha256(f"{export_id}:{fencing_token}".encode()).hexdigest()[:40]


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
    permissions: PermissionService | None = None
    # Optional trusted internal capture record lookup. The existing /2 export
    # API/worker does not call it; private v3 preview is not a release flag.
    source_capture: Callable[[str, str], CaptureRow | None] | None = None
    source_sanitizer: Callable[[bytes, str], CleanSourceRaster] | None = None
    private_v3_enabled: bool = False

    def private_free_v3_candidate(self, owner_id: str, report_id: str, layout: str, *,
                                  detail: str = "SUMMARY", include_image: bool = False,
                                  ctx: CallContext | None = None) -> ValidatedDocument:
        """Assemble a bounded authorized Free RenderEnvelope, without rendering.

        The HTTP export route still uses render-template/2. R5-F2/F3 must
        explicitly route/persist this new envelope, bind cache disclosure
        identities, and recheck access at publication and download.
        """
        if type(include_image) is not bool:
            raise InvalidInput("render_v3_image_flag_invalid")
        if layout not in DOCUMENT_LAYOUTS or detail not in ("SUMMARY", "FULL"):
            raise InvalidInput("render_v3_document_options_invalid")
        current_store = self.reports(owner_id)
        saved = current_store.latest(report_id)
        if saved is None or saved[0] != owner_id:
            raise NotFound("report_not_found")
        report = saved[1]
        reader = ReportReader(current_store, self.clock, self.access)
        view = reader.view(report_id=report_id, principal_id=owner_id,
                           projection="EXPORT", include_source_image=include_image)
        proof = None
        if report.data["evidence_bundle_id"] is not None:
            # The reader checks the exact saved source/region lineage before
            # the independent source raster may be disclosed.
            reader.evidence(report_id=report_id, principal_id=owner_id)
            proof = current_store.evidence(report_id)
        prepared = None
        if include_image:
            if (ctx is None or self.source_capture is None or self.access is None
                    or self.source_sanitizer is None):
                raise Unsupported("render_v3_source_adapter_not_configured")
            if proof is None:
                raise NotFound("source_image_not_available")
            input_asset = report.data["analysis"]["input_asset_id"]
            capture = self.source_capture(owner_id, input_asset)
            if capture is None or capture.deleted or capture.original_erased:
                raise NotFound("source_image_not_available")
            prepared = prepare_authorized_render_assets(
                owner_id=owner_id, report_owner_id=saved[0], report=report,
                view=view, evidence=proof, source=capture.stored_object(),
                store=self.store, access=self.access, ctx=ctx,
                sanitize=self.source_sanitizer,
            )
        return compile_free_render_envelope(
            report=report, view=view, layout=layout, detail=detail,
            evidence=proof, source_image=prepared,
        )

    def _v3_envelope(self, owner_id: str, request: ExportRequest,
                     ctx: CallContext | None) -> ValidatedDocument:
        if not self.private_v3_enabled:
            raise Unsupported("render_v3_disabled")
        if request.renderer_version != V3_TEMPLATE_VERSION or request.projection != "EXPORT":
            raise InvalidInput("render_v3_document_options_invalid")
        if request.detail not in V3_DETAILS or type(request.include_image) is not bool:
            raise InvalidInput("render_v3_document_options_invalid")
        if request.source_report_digest is None:
            raise InvalidInput("render_v3_source_pin_missing")
        envelope = self.private_free_v3_candidate(
            owner_id, request.report_id, request.layout,
            detail=request.detail, include_image=request.include_image, ctx=ctx,
        )
        data = envelope.data
        image = data["source_image"]
        actual_evidence = (
            hashlib.sha256(canonical_json(envelope.to_dict()["evidence"]).encode()).hexdigest()
            if data["evidence"] is not None else None
        )
        if (data["view"]["source_digest"] != request.source_report_digest
                or (image["sha256"] if image else None) != request.raster_sha256
                or actual_evidence != request.evidence_digest):
            raise Conflict("render_v3_pinned_source_changed")
        return envelope

    def projection(self, owner_id: str, request: ExportRequest) -> ValidatedDocument:
        """The authorized projection an export may show, derived now."""
        reader = ReportReader(self.reports(owner_id), self.clock, self.access)
        if request.projection == "EXPORT":
            return reader.view(report_id=request.report_id, principal_id=owner_id, projection="EXPORT",
                               include_source_image=False)
        # A card is a share artifact: it needs a current ordinary_sharing grant,
        # checked on every derivation (request, publication, retrieval).
        grant = request.share_grant_ref
        if self.permissions is None or grant is None or not self.permissions.check(
                owner_id, SHARING_PURPOSE, Scope("SHARE_GRANT", grant)).allowed:
            raise NotAuthorized("sharing_not_granted")
        # Ownership is checked by an owner read before the SHARE projection is
        # compiled for the owner's chosen scope.
        owned = reader.view(report_id=request.report_id, principal_id=owner_id, projection="OWNER")
        known = {s["section_id"] for s in owned.data["sections"]}
        if not set(request.sections) <= known:
            raise InvalidInput("unknown_section")
        return reader.view(report_id=request.report_id, principal_id=None, projection="SHARE",
                           share=ShareAccess(request.report_id, frozenset(request.sections)))

    def request(self, owner_id: str, report_id: str, layout: str, sections: tuple[str, ...] = (),
                share_grant_ref: str | None = None, *, detail: str | None = None,
                include_image: bool | None = None, ctx: CallContext | None = None) -> ExportRow:
        if layout not in MEDIA_TYPES:
            raise InvalidInput("unknown_layout")
        # Old clients omit BOTH fields: same FULL/no-image v2 behavior, keys,
        # stored rows and renderer. Explicit fields select the private v3 path.
        versioned = detail is not None or include_image is not None
        if versioned:
            if not self.private_v3_enabled:
                raise Unsupported("render_v3_disabled")
            if layout not in DOCUMENT_LAYOUTS or sections or share_grant_ref is not None:
                raise InvalidInput("render_v3_document_options_invalid")
            chosen = "SUMMARY" if detail is None else detail
            embed = False if include_image is None else include_image
            if chosen not in V3_DETAILS or type(embed) is not bool:
                raise InvalidInput("render_v3_document_options_invalid")
            envelope = self.private_free_v3_candidate(
                owner_id, report_id, layout, detail=chosen, include_image=embed, ctx=ctx,
            )
            data = envelope.data
            source = data["source_image"]
            evidence = data["evidence"]
            evidence_digest = (hashlib.sha256(canonical_json(envelope.to_dict()["evidence"]).encode()).hexdigest()
                               if evidence is not None else None)
            row = ExportRow(
                export_id=self.ids.new_id("export"), owner_id=owner_id, report_id=report_id,
                revision=data["view"]["source_revision"], layout=layout, sections=(),
                cache_key=v3_cache_key(envelope), state="QUEUED", created_at=self.clock.now(),
                renderer_version=V3_TEMPLATE_VERSION, detail=chosen, include_image=embed,
                source_report_digest=data["view"]["source_digest"],
                raster_sha256=source["sha256"] if source else None,
                evidence_digest=evidence_digest,
            )
            return self.repo.request(row, self.ids.new_id("job"))
        if layout in CARD_LAYOUTS:
            if not self.sharing_enabled():
                raise Unsupported("sharing_disabled")
            if not sections or len(sections) > MAX_CARD_SECTIONS or len(set(sections)) != len(sections):
                raise InvalidInput("card_sections_required")
            if share_grant_ref is None:
                raise InvalidInput("share_grant_required")
            require_opaque_id(share_grant_ref, "share_grant_ref")
        elif sections or share_grant_ref is not None:
            raise InvalidInput("sections_apply_to_cards_only")
        request = ExportRequest(report_id, layout, tuple(sorted(sections)), share_grant_ref)
        view = self.projection(owner_id, request)
        row = ExportRow(export_id=self.ids.new_id("export"), owner_id=owner_id, report_id=report_id,
                        revision=view.data["source_revision"], layout=layout, sections=request.sections,
                        share_grant_ref=share_grant_ref,
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
        def authorized() -> bool:
            try:
                if row.renderer_version == V3_TEMPLATE_VERSION:
                    envelope = self._v3_envelope(owner_id, row.request(), ctx)
                    return (v3_cache_key(envelope) == row.cache_key
                            and envelope.data["view"]["source_revision"] == row.revision)
                return cache_key(self.projection(owner_id, row.request()), row.request()) == row.cache_key
            except (NotFound, InvalidInput, NotAuthorized, Conflict, PermanentFailure, Unsupported):
                return False

        if not authorized():
            self.repo.revoke(owner_id, export_id, "export_stale", self.clock.now())
            raise NotFound("export_stale")
        stored = StoredObject(row.asset_id, row.version_ref, row.sha256, row.size_bytes, row.media_type)
        data = self.store.read_object(stored, ctx)
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise PermanentFailure("export_digest_mismatch")
        if row.renderer_version == V3_TEMPLATE_VERSION and not authorized():
            # A source can be withdrawn while its exported bytes are loading.
            self.repo.revoke(owner_id, export_id, "export_stale", self.clock.now())
            raise NotFound("export_stale")
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

        ctx = self._context()
        media_type = MEDIA_TYPES[row.layout]
        versioned = row.renderer_version == V3_TEMPLATE_VERSION
        try:
            if versioned:
                envelope = svc._v3_envelope(row.owner_id, request, ctx)
                if v3_cache_key(envelope) != row.cache_key or envelope.data["view"]["source_revision"] != row.revision:
                    return fail("projection_changed")
                data = self._renderer.render_envelope_v3(envelope)
            else:
                view = svc.projection(row.owner_id, request)
                if cache_key(view, request) != row.cache_key:
                    return fail("projection_changed")
                data = self._renderer.render(view.to_dict(), row.layout, view.data["locale"], view.data["generated_at"])
            check_rendered(data, media_type)
        except (TransientUnavailable, DeadlineExceeded, RateLimited) as exc:
            return fail(exc.code, retry=True)
        except PortError as exc:
            return fail(exc.code)
        asset_id = render_asset_id(row.export_id, claim.fencing_token)
        try:
            stored = svc.store.write_derivative(asset_id, None, data, media_type, ctx)
        except PortError as exc:
            return fail(exc.code, retry=True, orphan=asset_id)
        try:
            if versioned:
                current = svc._v3_envelope(row.owner_id, request, ctx)
                unchanged = (v3_cache_key(current) == row.cache_key
                             and current.data["view"]["source_revision"] == row.revision)
            else:
                unchanged = cache_key(svc.projection(row.owner_id, request), request) == row.cache_key
        except (NotFound, InvalidInput, NotAuthorized, Conflict, PermanentFailure, Unsupported):
            unchanged = False
        if unchanged and svc.repo.publish(claim, stored, svc.clock.now()):
            return ExportOutcome(row.export_id, "READY")
        return fail("fenced" if unchanged else "projection_changed", orphan=asset_id)


__all__ = ["CARD_LAYOUTS", "ClaimedExport", "DOCUMENT_LAYOUTS", "ExportOutcome", "ExportRepository", "ExportRequest",
           "ExportRow", "ExportService", "ExportWorker", "MAX_EXPORT_BYTES", "MEDIA_TYPES", "NOT_RECALLABLE",
           "Renderer", "SHARING_PURPOSE", "TEMPLATE_VERSION", "V3_TEMPLATE_VERSION", "v3_cache_key",
           "cache_key", "check_rendered", "render_asset_id"]
