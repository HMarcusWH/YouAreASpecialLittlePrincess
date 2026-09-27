"""FastAPI composition for the product API (T02 slice).

HTTP is a thin boundary: requests authenticate through ``IdentityService``,
use cases run in ``princess_app.application`` and responses are validated
product contracts. Provider SDKs, SQL and entitlement logic stay outside the
route handlers.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from princess_app.adapters.fakes import FakeIdentityProvider
from princess_app.application.identity import IdentityService, Principal
from princess_app.application.permissions import PermissionService
from princess_app.application.reports import ReportReader, ReportStore
from princess_app.domain.analysis import rfc3339
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
from princess_contracts import compile_document
from princess_contracts import generated as g

REQUEST_DEADLINE = timedelta(seconds=10)
_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
STATUS = [(RateLimited, 429), (DeadlineExceeded, 504), (TransientUnavailable, 503), (Unauthenticated, 401),
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
    audience: str = "princess-api"


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


class DevTokenBody(_Strict):
    subject: str = Field(min_length=1, max_length=128)


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="Princess product API", version="0.1.0", docs_url=None, redoc_url=None)

    @app.exception_handler(PortError)
    async def port_error(_: Request, exc: PortError) -> JSONResponse:
        status = next((code for kind, code in STATUS if isinstance(exc, kind)), 500)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
        if isinstance(exc, RateLimited) and exc.retry_after_s is not None:
            headers["Retry-After"] = str(int(exc.retry_after_s))
        return JSONResponse({"error": exc.code}, status_code=status, headers=headers)

    def call_context(request: Request) -> CallContext:
        supplied = request.headers.get("x-correlation-id", "")
        correlation = supplied if _CORRELATION.match(supplied) else uuid.uuid4().hex
        return CallContext(correlation, services.environment, services.clock.now() + REQUEST_DEADLINE)

    def principal(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or len(header) > 8192:
            raise Unauthenticated("missing_credential")
        return services.identity.authenticate(header[len("Bearer "):], call_context(request))

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
        return Response(status_code=204)

    @app.delete("/v1/me", status_code=202)
    def delete_me(request: Request, who: Principal = Depends(principal)) -> dict:
        services.identity.delete_account(who, call_context(request))
        return {"state": "DELETION_REQUESTED"}

    @app.post("/v1/me/permissions", status_code=201)
    def record_permission(body: PermissionBody, who: Principal = Depends(principal)) -> dict:
        event = services.permissions.record(
            subject_id=who.principal_id, actor_id=who.principal_id, purpose_id=body.purpose_id,
            scope=Scope(body.scope_kind, body.scope_ref), decision=Decision(body.decision),
            notice_version=body.notice_version)
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

    @app.get("/v1/reports/{report_id}")
    def read_report(report_id: str, projection: Literal["FREE", "OWNER", "EXPORT"] = "OWNER",
                    who: Principal = Depends(principal)) -> dict:
        reader = ReportReader(services.report_store_for(who.principal_id), services.clock)
        commerce = services.kill_switches.get("commerce", False)
        actions = {"EXPORT": None, "SAVE": None, "DELETE": None,
                   "SHARE": None if services.kill_switches.get("sharing", False) else "sharing_disabled",
                   "COMPARE": "comparison_not_available",
                   "PURCHASE": None if commerce else "commerce_disabled"}
        view = reader.view(report_id=report_id, principal_id=who.principal_id, projection=projection,
                           actions=actions)
        return view.to_dict()

    if services.dev_identity is not None and services.environment in (Environment.LOCAL, Environment.TEST):
        dev = services.dev_identity

        @app.post("/v1/dev/id-tokens", status_code=201)
        def dev_token(body: DevTokenBody) -> dict:
            """Local/test only: mint a fake provider ID token for a synthetic subject."""
            return {"id_token": dev.issue_token(body.subject, services.audience, session_id=f"dev-{body.subject}")}

    return app
