"""FastAPI composition for the product API (T02 slice).

HTTP is a thin boundary: requests authenticate through ``IdentityService``,
use cases run in ``princess_app.application`` and responses are validated
product contracts. Provider SDKs, SQL and entitlement logic stay outside the
route handlers.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from princess_app.adapters.fakes import FakeIdentityProvider
from princess_app.application.commerce import CommerceService
from princess_app.application.comparison import ComparisonService
from princess_app.application.exports import NOT_RECALLABLE, ExportRow, ExportService
from princess_app.application.feedback import FeedbackService
from princess_app.application.identity import IdentityService, Principal
from princess_app.application.intake import ChallengeProof, IntakeService
from princess_app.application.notices import NoticeCatalog
from princess_app.application.notifications import NotificationService
from princess_app.application.permissions import PermissionService
from princess_app.application.reports import ReportAccessResolver, ReportReader, ReportStore
from princess_app.application.tombstones import (
    ACCOUNT_DELETED,
    CAPTURE_DELETED,
    DEVICE_UNREGISTERED,
    FEEDBACK_WITHDRAWN,
    PERMISSION_WITHDRAWN,
    SESSIONS_REVOKED,
    Tombstone,
    TombstoneLog,
)
from princess_app.domain.analysis import rfc3339
from princess_app.domain.commerce import Platform
from princess_app.domain.feedback import FeedbackSubmission
from princess_app.domain.intake import MAX_UPLOAD_BYTES
from princess_app.domain.permissions import Decision, Scope
from princess_app.ports.base import (
    AmbiguousOutcome,
    CallContext,
    Clock,
    Conflict,
    DeadlineExceeded,
    Environment,
    InvalidInput,
    NotAuthorized,
    NotFound,
    PermanentFailure,
    PortError,
    RateLimited,
    TransientUnavailable,
    Unauthenticated,
    Unsupported,
)
from princess_app.ports.payments import PaymentRail
from princess_contracts import compile_document
from princess_contracts import generated as g

REQUEST_DEADLINE = timedelta(seconds=10)
_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
MAX_EVENT_BYTES = 256 * 1024


class PayloadTooLarge(InvalidInput):
    pass


STATUS = [(PayloadTooLarge, 413), (RateLimited, 429), (DeadlineExceeded, 504), (TransientUnavailable, 503), (Unauthenticated, 401),
          (NotAuthorized, 403), (NotFound, 404), (Conflict, 409), (InvalidInput, 422), (Unsupported, 501),
          (AmbiguousOutcome, 502), (PermanentFailure, 502)]
DECISION_STATUS = {Decision.GRANT: "GRANTED", Decision.DENY: "DENIED", Decision.WITHDRAW: "WITHDRAWN"}


@dataclass
class Services:
    environment: Environment
    clock: Clock
    identity: IdentityService
    permissions: PermissionService
    report_store_for: Callable[[str], ReportStore]
    kill_switches: dict[str, bool] = field(default_factory=dict)
    # Present only when the identity provider is a fake (never in production).
    dev_identity: FakeIdentityProvider | None = None
    intake: IntakeService | None = None
    # Local/test only: a fake/filesystem store exposing ``accept_signed_put``
    # in place of a provider's presigned PUT endpoint.
    dev_store: Any = None
    commerce: CommerceService | None = None
    # Live source-image and Premium overlay state for saved snapshots.
    report_access: ReportAccessResolver | None = None
    exports: ExportService | None = None
    feedback: FeedbackService | None = None
    # Deletions recorded outside the database, replayed after a restore.
    tombstones: TombstoneLog | None = None
    notifications: NotificationService | None = None
    # Operational readiness is injected by composition and must remain provider-free.
    readiness: Callable[[], None] | None = None
    # The reviewed consent notice registry served to clients (read-only).
    notices: NoticeCatalog | None = None
    # Same-owner, unsaved comparisons over the T18 builder; partner inputs need T22.
    comparisons_enabled: bool = False
    # Test-only public preview: no account credentials or development token-minting route.
    guest_only: bool = False


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=512)


class GuestTransferBody(_Strict):
    guest_token: str = Field(min_length=10)


class PermissionBody(_Strict):
    purpose_id: str
    scope_kind: str
    scope_ref: str | None = None
    decision: Literal["GRANT", "DENY", "WITHDRAW"]
    notice_version: str
    # Client-generated per decision; a replayed request returns the recorded
    # event instead of appending a later duplicate that could reverse a newer choice.
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class DevTokenBody(_Strict):
    subject: str = Field(min_length=1, max_length=128)


class ChallengeBody(_Strict):
    token: str = Field(min_length=1)


class UploadBody(_Strict):
    media_type: Literal["image/jpeg", "image/png"]
    challenge: ChallengeBody | None = None


class CompleteBody(_Strict):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnalysisBody(_Strict):
    capture_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CheckoutBody(_Strict):
    product_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    intent_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class ClaimBody(_Strict):
    rail: Literal["apple_app_store", "google_play"]
    proof: str = Field(min_length=1, max_length=8192)


class PremiumBody(_Strict):
    platform: Literal["web", "ios", "android"]


class ExportBody(_Strict):
    report_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    layout: Literal["A4", "LETTER", "CARD_SQUARE", "CARD_STORY"]
    sections: list[str] = Field(default_factory=list, max_length=8)
    # Cards: the ordinary_sharing grant (scope SHARE_GRANT) the card falls under.
    share_grant_ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ComparisonBody(_Strict):
    kind: Literal["PAIR", "HISTORY"]
    report_ids: list[str] = Field(min_length=2, max_length=16)


class FeedbackBody(_Strict):
    category: Literal["MEASUREMENT_LOOKS_WRONG", "HARD_TO_UNDERSTAND", "HARMFUL_OR_OFFENSIVE",
                      "PREMIUM_TEXT_ISSUE", "OTHER"]
    target_kind: Literal["REPORT", "SECTION", "FACT", "PREMIUM"]
    target_ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    comment: str | None = Field(default=None, max_length=500)
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class PushInstallationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=4096)
    device_token: str = Field(min_length=8, max_length=4096)
    platform: Literal["apns", "fcm"]
    # The backend environment the build targets; a mismatch is refused.
    app_environment: str = Field(max_length=16)
    locale: str = Field(default="en", max_length=5)


class NotificationPreferencesBody(_Strict):
    mail_report_ready: bool
    locale: str = Field(default="en", max_length=5)


def export_status(row: ExportRow) -> dict:
    return {"export_id": row.export_id, "report_id": row.report_id, "revision": row.revision,
            "layout": row.layout, "sections": list(row.sections), "state": row.state,
            "media_type": row.media_type, "size_bytes": row.size_bytes, "error_code": row.error_code,
            "created_at": rfc3339(row.created_at),
            "completed_at": rfc3339(row.completed_at) if row.completed_at else None,
            # Revocation stops our copy being served; a file already saved elsewhere cannot be recalled.
            "downloaded_copies": NOT_RECALLABLE}


async def read_bounded(request: Request, limit: int) -> bytes:
    """Read a raw body without buffering more than ``limit`` bytes: a larger
    declared length is refused up front, and the stream is cut off as soon as
    it passes the limit (chunked or lying clients)."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise PayloadTooLarge("body_too_large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise PayloadTooLarge("body_too_large")
    return bytes(body)


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="Princess product API", version="0.1.0", docs_url=None, redoc_url=None)

    @app.exception_handler(PortError)
    async def port_error(_: Request, exc: PortError) -> JSONResponse:
        status = next((code for kind, code in STATUS if isinstance(exc, kind)), 500)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
        if isinstance(exc, RateLimited) and exc.retry_after_s is not None:
            headers["Retry-After"] = str(int(exc.retry_after_s))
        return JSONResponse({"error": exc.code}, status_code=status, headers=headers)

    @app.get("/health/live", include_in_schema=False)
    def health_live() -> dict[str, str]:
        """Process liveness only: no database or provider I/O."""
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def health_ready() -> JSONResponse:
        """Readiness is intentionally limited to the application database."""
        if services.readiness is None:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        try:
            services.readiness()
        except PortError:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ok"})

    def call_context(request: Request) -> CallContext:
        supplied = request.headers.get("x-correlation-id", "")
        correlation = supplied if _CORRELATION.match(supplied) else uuid.uuid4().hex
        return CallContext(correlation, services.environment, services.clock.now() + REQUEST_DEADLINE)

    def principal(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 8192:
            raise Unauthenticated("missing_credential")
        credential = header[len("Bearer "):]
        if services.guest_only and not credential.startswith("guest_"):
            raise Unauthenticated("guest_only_test_endpoint")
        return services.identity.authenticate(credential, call_context(request))

    @app.post("/v1/guest-sessions", status_code=201)
    def create_guest() -> dict:
        guest, token = services.identity.create_guest()
        return {"principal_id": guest.principal_id, "guest_token": token,
                "expires_at": rfc3339(guest.guest_expires_at) if guest.guest_expires_at else None}

    @app.get("/v1/me")
    def me(who: Principal = Depends(principal)) -> dict:
        return {"principal_id": who.principal_id, "kind": who.kind}

    @app.post("/v1/me/guest-transfer")
    def guest_transfer(body: GuestTransferBody, who: Principal = Depends(principal)) -> dict:
        return {"transferred_principal_id": services.identity.transfer_guest(who, body.guest_token)}

    @app.post("/v1/me/logout-everywhere", status_code=204)
    def logout_everywhere(request: Request, who: Principal = Depends(principal)) -> Response:
        services.identity.logout_everywhere(who, call_context(request))
        tombstone(SESSIONS_REVOKED, who.principal_id, who.principal_id)
        forget_devices(who.principal_id)
        return Response(status_code=204)

    def forget_devices(owner_id: str) -> None:
        if services.notifications is not None:
            services.notifications.forget_devices(owner_id)

    def tombstone(kind: str, owner_id: str, ref: str, **fields: Any) -> None:
        """Fast path after the commit. Best effort: the erasure worker writes
        the same tombstone before it processes the change's outbox event."""
        if services.tombstones is not None:
            at = fields.pop("at", None) or services.clock.now()
            try:
                services.tombstones.append(Tombstone(kind, owner_id, ref, at, **fields))
            except OSError:
                pass

    @app.delete("/v1/me", status_code=202)
    def delete_me(request: Request, who: Principal = Depends(principal)) -> dict:
        services.identity.delete_account(who, call_context(request))
        forget_devices(who.principal_id)
        tombstone(ACCOUNT_DELETED, who.principal_id, who.principal_id)
        return {"state": "DELETION_REQUESTED"}

    @app.post("/v1/me/permissions", status_code=201)
    def record_permission(body: PermissionBody, who: Principal = Depends(principal)) -> dict:
        scope = Scope(body.scope_kind, body.scope_ref)
        event = services.permissions.record(
            subject_id=who.principal_id, actor_id=who.principal_id, purpose_id=body.purpose_id,
            scope=scope, decision=Decision(body.decision), notice_version=body.notice_version,
            request_id=body.request_id)
        if event.decision is not Decision.GRANT:
            tombstone(PERMISSION_WITHDRAWN, event.subject_id, event.event_id, at=event.recorded_at,
                      purpose_id=event.purpose_id, scope_kind=event.scope.kind, scope_ref=event.scope.ref,
                      notice_version=event.notice_version)
        if services.intake is not None:
            # T03 withdrawal propagation to intake-owned retention classes.
            services.intake.apply_permission_change(who.principal_id, event.purpose_id, event.scope, event.decision)
        snapshot = compile_document("GrantSnapshot", {
            "contract_version": g.CONTRACT_VERSION, "grant_id": event.event_id, "owner_id": event.subject_id,
            "purpose_id": event.purpose_id, "purpose_version": event.purpose_version,
            "status": DECISION_STATUS[event.decision],
            "scope": event.scope.kind if event.scope.ref is None else f"{event.scope.kind}:{event.scope.ref}",
            "recorded_at": rfc3339(event.recorded_at), "effective_at": rfc3339(event.effective_at),
            "policy_sha256": g.PURPOSE_AUTHORITY["sha256"]})
        if snapshot.value is None:
            raise PermanentFailure("grant_snapshot_invalid")
        return snapshot.value.to_dict()

    @app.get("/v1/me/permissions/{purpose_id}")
    def check_permission(purpose_id: str, scope_kind: str = "SUBJECT_WIDE", scope_ref: str | None = None,
                         who: Principal = Depends(principal)) -> dict:
        check = services.permissions.check(who.principal_id, purpose_id, Scope(scope_kind, scope_ref))
        return {"purpose_id": purpose_id, "allowed": check.allowed, "reason": check.reason}

    @app.get("/v1/consent-notices")
    def consent_notices(locale: str = Query("en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")) -> dict:
        """The notice text and versions a grant may cite here. Public: no permission is implied."""
        if services.notices is None:
            raise Unsupported("notices_not_configured")
        return {"notices": services.notices.describe(locale)}

    def reader_for(who: Principal) -> ReportReader:
        return ReportReader(services.report_store_for(who.principal_id), services.clock, services.report_access)

    @app.get("/v1/reports")
    def list_reports(limit: int = Query(20, ge=1, le=50),
                     cursor: str | None = Query(default=None, max_length=512),
                     who: Principal = Depends(principal)) -> dict:
        return reader_for(who).history(principal_id=who.principal_id, limit=limit, cursor=cursor)

    @app.get("/v1/reports/{report_id}/evidence")
    def read_report_evidence(report_id: str, who: Principal = Depends(principal)) -> dict:
        return reader_for(who).evidence(report_id=report_id, principal_id=who.principal_id)

    @app.get("/v1/reports/{report_id}")
    def read_report(report_id: str, projection: Literal["FREE", "OWNER", "PREMIUM", "EXPORT"] = "OWNER",
                    who: Principal = Depends(principal)) -> dict:
        reader = reader_for(who)
        commerce = services.kill_switches.get("commerce", False)
        # Only flows that exist are enabled; the rest say why they are not.
        actions = {"EXPORT": None if services.exports is not None else "export_not_available",
                   "SAVE": "save_not_available", "DELETE": "delete_from_settings",
                   "SHARE": "sharing_not_available" if services.kill_switches.get("sharing", False)
                   else "sharing_disabled",
                   "COMPARE": "comparison_not_available",
                   "PURCHASE": None if commerce else "commerce_disabled"}
        view = reader.view(report_id=report_id, principal_id=who.principal_id, projection=projection,
                           actions=actions)
        return view.to_dict()

    def intake() -> IntakeService:
        if services.intake is None:
            raise Unsupported("uploads_not_configured")
        return services.intake

    @app.delete("/v1/reports/{report_id}", status_code=202)
    def delete_report(report_id: str, who: Principal = Depends(principal)) -> dict:
        """Delete the specimen behind a report (and so the report), without the
        client having to remember a capture ID from the device that made it."""
        capture_id = intake().delete_report_source(who.principal_id, report_id)
        tombstone(CAPTURE_DELETED, who.principal_id, capture_id)
        return {"state": "DELETION_REQUESTED"}

    @app.get("/v1/reports/{report_id}/source-image")
    def report_source_image(report_id: str, request: Request, who: Principal = Depends(principal)) -> Response:
        """The retained input image of the owner's report. Authorized through the
        live OWNER projection: an erased, revoked or withdrawn image is not served."""
        view = reader_for(who).view(report_id=report_id, principal_id=who.principal_id, projection="OWNER").data
        entry = services.report_store_for(who.principal_id).latest(report_id)
        asset_id = entry[1].data["analysis"]["input_asset_id"] if entry else None
        if asset_id is None or asset_id not in view["authorized_asset_ids"]:
            raise NotFound("source_image_not_available")
        data, media_type = intake().read_source_image(who.principal_id, asset_id, call_context(request))
        return Response(content=data, media_type=media_type, headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/v1/comparisons")
    def create_comparison(body: ComparisonBody, who: Principal = Depends(principal)) -> dict:
        """Deterministic same-owner comparison of saved reports. Computed from the
        latest saved revisions and returned, not stored; never calls a model."""
        if not services.comparisons_enabled:
            raise Unsupported("comparisons_not_configured")
        comparison = ComparisonService(services.report_store_for(who.principal_id), services.clock).create(
            comparison_id=f"comparison_{uuid.uuid4().hex}", principal_id=who.principal_id,
            report_ids=body.report_ids, kind=body.kind)
        return comparison.to_dict()

    @app.post("/v1/uploads", status_code=201)
    def reserve_upload(body: UploadBody, request: Request, who: Principal = Depends(principal)) -> dict:
        proof = ChallengeProof(body.challenge.token) if body.challenge else None
        ticket = intake().reserve_upload(who.principal_id, body.media_type, proof, call_context(request))
        return {"upload_id": ticket.upload_id, "method": ticket.method, "url": ticket.url,
                "expires_at": rfc3339(ticket.expires_at), "max_bytes": ticket.max_bytes}

    @app.post("/v1/uploads/{upload_id}/complete")
    def complete_upload(upload_id: str, body: CompleteBody, request: Request,
                        who: Principal = Depends(principal)) -> dict:
        capture = intake().complete_upload(who.principal_id, upload_id, body.sha256, call_context(request))
        return {"capture_id": capture.capture_id, "width": capture.width, "height": capture.height,
                "media_type": capture.media_type}

    @app.post("/v1/analyses", status_code=202)
    def start_analysis(body: AnalysisBody, who: Principal = Depends(principal)) -> dict:
        run_id = intake().start_analysis(who.principal_id, body.capture_id)
        status = intake().status(who.principal_id, run_id)
        return {"run_id": run_id, "state": status.state}

    @app.get("/v1/analyses")
    def list_analyses(limit: int = Query(20, ge=1, le=50), who: Principal = Depends(principal)) -> dict:
        """The principal's newest runs: lets a reinstalled app or another device
        find unfinished work instead of starting it again."""
        return {"items": [{"run_id": run.run_id, "state": run.state, "report_id": run.report_id,
                           "error_code": run.error_code, "created_at": rfc3339(run.created_at)}
                          for run in intake().recent_runs(who.principal_id, limit)]}

    @app.get("/v1/analyses/{run_id}")
    def analysis_status(run_id: str, who: Principal = Depends(principal)) -> dict:
        status = intake().status(who.principal_id, run_id)
        return {"run_id": status.run_id, "state": status.state, "report_id": status.report_id,
                "error_code": status.error_code}

    @app.post("/v1/analyses/{run_id}/cancel")
    def cancel_analysis(run_id: str, who: Principal = Depends(principal)) -> dict:
        status = intake().cancel(who.principal_id, run_id)
        return {"run_id": status.run_id, "state": status.state}

    @app.delete("/v1/captures/{capture_id}", status_code=202)
    def delete_capture(capture_id: str, who: Principal = Depends(principal)) -> dict:
        intake().delete_capture(who.principal_id, capture_id)
        tombstone(CAPTURE_DELETED, who.principal_id, capture_id)
        return {"state": "DELETION_REQUESTED"}

    # The filesystem store's HMAC-signed PUT stands in for a provider's presigned
    # URL wherever that fake store is composed (never staging or production).
    def commerce() -> CommerceService:
        if services.commerce is None:
            raise Unsupported("commerce_not_configured")
        return services.commerce

    def account_only(who: Principal) -> Principal:
        if who.kind != "ACCOUNT":
            raise NotAuthorized("account_required")  # purchases need an authenticated account
        return who

    def selling() -> None:
        if not services.kill_switches.get("commerce", False):
            raise Unsupported("commerce_disabled")

    @app.get("/v1/catalog")
    def catalog() -> dict:
        return {"products": commerce().catalog()}

    @app.get("/v1/me/payment-account")
    def payment_account(who: Principal = Depends(principal)) -> dict:
        return {"account_ref": commerce().payment_account(account_only(who).principal_id)}

    @app.get("/v1/me/credits")
    def credits(platform: Literal["web", "ios", "android"], who: Principal = Depends(principal)) -> dict:
        balance = commerce().balance(who.principal_id, Platform(platform))
        return {"platform": platform, "available": balance.available, "reserved": balance.reserved}

    @app.post("/v1/checkout/web", status_code=201)
    def web_checkout(body: CheckoutBody, request: Request, who: Principal = Depends(principal)) -> dict:
        selling()
        session = commerce().start_web_checkout(account_only(who).principal_id, body.product_id, body.intent_ref,
                                                call_context(request))
        return {"redirect_url": session.redirect_url, "expires_at": rfc3339(session.expires_at)}

    @app.post("/v1/payments/{rail}/events")
    async def payment_events(rail: Literal["stripe", "apple_app_store", "google_play"], request: Request) -> dict:
        """Signed provider notifications. Always accepted, even with sales
        disabled, so refunds and reconciliation keep flowing."""
        raw = await read_bounded(request, MAX_EVENT_BYTES)
        outcomes = commerce().ingest_event(PaymentRail(rail), raw, dict(request.headers),
                                           hashlib.sha256(raw).hexdigest(), call_context(request))
        return {"received": True, "transactions": len(outcomes)}

    @app.post("/v1/purchases/claims")
    def claim_purchase(body: ClaimBody, request: Request, who: Principal = Depends(principal)) -> dict:
        result = commerce().claim_store_purchase(account_only(who).principal_id, PaymentRail(body.rail), body.proof,
                                                 call_context(request))
        return {"outcome": result.outcome, "finish_transaction": result.finish_on_client}

    @app.post("/v1/reports/{report_id}/premium", status_code=202)
    def request_premium(report_id: str, body: PremiumBody, who: Principal = Depends(principal)) -> dict:
        selling()
        if not services.kill_switches.get("premium_generation", False):
            raise Unsupported("premium_generation_disabled")
        requested = commerce().request_premium(account_only(who).principal_id, report_id, Platform(body.platform))
        return {"job_id": requested.job_id, "created": requested.created}

    @app.get("/v1/reports/{report_id}/premium")
    def read_premium(report_id: str, who: Principal = Depends(principal)) -> dict:
        """The purchased, validated overlay. Read-only: no model call on read."""
        return reader_for(who).premium_content(report_id=report_id, principal_id=who.principal_id)

    def exports() -> ExportService:
        if services.exports is None:
            raise Unsupported("exports_not_configured")
        return services.exports

    @app.post("/v1/report-exports", status_code=202)
    def request_export(body: ExportBody, who: Principal = Depends(principal)) -> dict:
        """Render the authorized projection of the latest revision. Never calls a model."""
        return export_status(exports().request(who.principal_id, body.report_id, body.layout,
                                               tuple(body.sections), body.share_grant_ref))

    @app.get("/v1/report-exports/{export_id}")
    def read_export(export_id: str, who: Principal = Depends(principal)) -> dict:
        return export_status(exports().status(who.principal_id, export_id))

    @app.get("/v1/report-exports/{export_id}/file")
    def download_export(export_id: str, request: Request, who: Principal = Depends(principal)) -> Response:
        data, row = exports().download(who.principal_id, export_id, call_context(request))
        suffix = "pdf" if row.media_type == "application/pdf" else "png"
        return Response(content=data, media_type=row.media_type, headers={
            "Content-Disposition": f'attachment; filename="princess-{row.report_id}-r{row.revision}.{suffix}"',
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    def feedback() -> FeedbackService:
        if services.feedback is None:
            raise Unsupported("feedback_not_configured")
        return services.feedback

    @app.post("/v1/reports/{report_id}/feedback", status_code=201)
    def submit_feedback(report_id: str, body: FeedbackBody, who: Principal = Depends(principal)) -> dict:
        """Report-content feedback. Stored redacted and owner-bound; never sent to telemetry or analytics."""
        record = feedback().submit(who.principal_id, FeedbackSubmission(
            report_id=report_id, category=body.category, target_kind=body.target_kind, target_ref=body.target_ref,
            comment=body.comment, request_id=body.request_id))
        return {"feedback_id": record.feedback_id, "report_id": record.report_id, "revision": record.revision,
                "category": record.category, "comment_stored": record.comment,
                "expires_at": rfc3339(record.expires_at), "contract_version": record.contract_version}

    @app.delete("/v1/feedback/{feedback_id}", status_code=204)
    def withdraw_feedback(feedback_id: str, who: Principal = Depends(principal)) -> Response:
        at = feedback().withdraw(who.principal_id, feedback_id)
        tombstone(FEEDBACK_WITHDRAWN, who.principal_id, feedback_id, at=at)
        return Response(status_code=204)

    def notifications() -> NotificationService:
        if services.notifications is None:
            raise Unsupported("notifications_not_configured")
        return services.notifications

    @app.post("/v1/me/push-installations", status_code=201)
    def register_push(body: PushInstallationBody, who: Principal = Depends(principal)) -> dict:
        """Bind this device to the signed-in principal (moves it from any other account)."""
        installation_id = notifications().register(who, body.device_token, body.platform, body.app_environment,
                                                   body.locale)
        return {"installation_id": installation_id}

    @app.get("/v1/me/push-installations")
    def list_push(who: Principal = Depends(principal)) -> dict:
        return {"installations": [
            {"installation_id": i.installation_id, "platform": i.platform.value,
             "app_environment": i.app_environment.value, "registered_at": rfc3339(i.registered_at)}
            for i in notifications().installations(who.principal_id)]}

    @app.delete("/v1/me/push-installations/{installation_id}", status_code=204)
    def unregister_push(installation_id: str, who: Principal = Depends(principal)) -> Response:
        """Logout or account switch on a device; notices still queued for it are dropped."""
        at = notifications().unregister(who.principal_id, installation_id)
        if at is not None:
            tombstone(DEVICE_UNREGISTERED, who.principal_id, installation_id, at=at)
        return Response(status_code=204)

    @app.get("/v1/me/notification-preferences")
    def read_notification_preferences(who: Principal = Depends(principal)) -> dict:
        prefs = notifications().preferences(who.principal_id)
        return {"mail_report_ready": prefs.mail_report_ready, "locale": prefs.locale}

    @app.put("/v1/me/notification-preferences")
    def write_notification_preferences(body: NotificationPreferencesBody,
                                       who: Principal = Depends(principal)) -> dict:
        prefs = notifications().set_preferences(who, body.mail_report_ready, body.locale)
        return {"mail_report_ready": prefs.mail_report_ready, "locale": prefs.locale}

    @app.get("/v1/premium-jobs/{job_id}")
    def premium_job(job_id: str, who: Principal = Depends(principal)) -> dict:
        state, error = commerce().premium_status(who.principal_id, job_id)
        return {"job_id": job_id, "state": state, "error_code": error}

    if services.dev_store is not None and services.environment in (Environment.LOCAL, Environment.TEST,
                                                                   Environment.PREVIEW):
        store = services.dev_store

        @app.put("/v1/dev/uploads/{upload_id}", status_code=204)
        async def dev_upload(upload_id: str, request: Request) -> Response:
            """Local/test only: stands in for a provider's presigned PUT."""
            data = await read_bounded(request, MAX_UPLOAD_BYTES)
            store.accept_signed_put(upload_id, request.query_params.get("sig"), data,
                                    request.headers.get("content-type"))
            return Response(status_code=204)

    if services.dev_identity is not None and services.environment in (Environment.LOCAL, Environment.TEST):
        dev = services.dev_identity

        @app.post("/v1/dev/id-tokens", status_code=201)
        def dev_token(body: DevTokenBody) -> dict:
            """Local/test only: mint a fake credential for one synthetic sign-in."""
            return {"id_token": dev.issue_token(
                body.subject, session_id=f"dev-{body.subject}",
                auth_time=services.clock.now(),
            )}

    return app
