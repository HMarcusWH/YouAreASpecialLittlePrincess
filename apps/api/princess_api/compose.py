"""Compose the API from a validated runtime configuration.

Identity is fake-only in local/test/preview. The owner-approved staging/sandbox
Supabase verifier composes only when its protected receipt-derived binding
matches the qualified profile; production/live still fails closed.
Run locally with::

    PRINCESS_ENV=local PRINCESS_COMPONENT=api PRINCESS_DATABASE_URL=... \\
    PRINCESS_SESSION_SECRET=... PRINCESS_IDENTITY_AUDIENCE=princess-local \\
    PRINCESS_STORAGE_SIGNING_KEY=... uvicorn --factory princess_api.compose:app_from_environment
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from princess_app.adapters.fakes import FakeAbuseChallenge, FakeIdentityProvider, FakePaymentProvider
from princess_app.adapters.imaging import inspect_header
from princess_app.adapters.localfs import LocalObjectStore
from princess_app.adapters.localfs.tombstones import JsonlTombstoneLog
from princess_app.adapters.postgres.access import PostgresReportAccess
from princess_app.adapters.postgres.commerce import PostgresLedger
from princess_app.adapters.postgres.exports import PostgresExportRepository
from princess_app.adapters.postgres.feedback import PostgresFeedbackRepository
from princess_app.adapters.postgres.intake import PostgresIntakeRepository
from princess_app.adapters.postgres.notifications import PostgresNotificationRepository
from princess_app.adapters.postgres.stores import (
    Database,
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
    make_engine,
)
from princess_app.adapters.supabase import SupabaseIdentityProvider
from princess_app.adapters.supabase.jwks import SupabaseJwksSource
from princess_app.application.commerce import CommerceService
from princess_app.application.exports import ExportService
from princess_app.application.feedback import FeedbackService
from princess_app.application.identity import GuestAdmission, IdentityService
from princess_app.application.intake import IntakeService
from princess_app.application.notices import NoticeCatalog
from princess_app.application.notifications import NotificationService
from princess_app.application.permissions import PermissionService
from princess_app.config import RuntimeConfig, load_runtime_config
from princess_app.config_supabase import normalized_manifest_sha256, parse_supabase_staging_runtime_binding
from princess_app.domain.commerce import CATALOG
from princess_app.ports.payments import PaymentRail
from princess_app.ports.base import Environment, ProviderMode, SystemClock, Unsupported
from princess_graphology import __version__ as ENGINE_VERSION

from .app import Services, create_app

ROOT = Path(__file__).resolve().parents[3]


class UuidIds:
    def new_id(self, prefix: str) -> str:
        import uuid

        return f"{prefix}_{uuid.uuid4().hex}"


def _manifest_sha256(environment: Environment) -> str:
    path = ROOT / "infra" / "environments" / f"{environment.value}.json"
    try:
        raw = path.read_bytes()
    except OSError:
        raise Unsupported("identity_runtime_manifest_unreadable", detail=environment.value) from None

    return normalized_manifest_sha256(raw)


def compose_identity_provider(config: RuntimeConfig, clock):
    audience = config.secret("PRINCESS_IDENTITY_AUDIENCE")
    mode = config.provider_mode("IdentityProvider")
    if mode is ProviderMode.FAKE:
        return FakeIdentityProvider(audience=audience, clock=clock, environment=config.environment)
    if config.environment is Environment.STAGING and mode is ProviderMode.SANDBOX:
        issuer = config.protected_value("PRINCESS_IDENTITY_ISSUER")
        binding = parse_supabase_staging_runtime_binding(
            config.protected_value("PRINCESS_IDENTITY_BINDING"),
            issuer=issuer,
            audience=audience,
            current_manifest_sha256=_manifest_sha256(config.environment),
        )
        return SupabaseIdentityProvider(
            issuer=issuer,
            audience=audience,
            allowed_roles=frozenset({binding.allowed_role}),
            jwks_source=SupabaseJwksSource(issuer),
            clock=clock,
            environment=config.environment,
            mode=mode,
            stock_claims_profile=True,
        )
    raise Unsupported(
        "identity_adapter_not_configured",
        detail=f"{config.environment.value}:{mode.value}",
    )


def compose(config: RuntimeConfig) -> Services:
    if config.component != "api":
        raise Unsupported("wrong_component", detail=config.component)
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    clock = SystemClock()
    provider = compose_identity_provider(config, clock)
    public_guest_only = (config.environment is Environment.TEST
                         and os.environ.get("PRINCESS_TEST_PUBLIC_GUEST_ONLY") == "1")
    admission = GuestAdmission(limit=int(os.environ.get("PRINCESS_GUEST_ADMISSIONS_PER_MINUTE", "300")))
    identity = IdentityService(provider, PostgresIdentityStore(db), clock, UuidIds(),
                               guest_admission=admission)
    permissions = PermissionService(
        PostgresPermissionStore(db), clock, UuidIds(),
        # Draft T03 notices authorize nothing outside synthetic local/test data.
        allow_draft_policy=config.environment in (Environment.LOCAL, Environment.TEST))
    if config.provider_mode("ObjectStore") is not ProviderMode.FAKE:
        raise Unsupported("object_store_adapter_not_configured", detail="ADR-004 provider pending")
    store = local_store(config, clock)
    intake = IntakeService(repo=PostgresIntakeRepository(db, engine_version=ENGINE_VERSION), store=store,
                           permissions=permissions, challenge=FakeAbuseChallenge(clock=clock,
                                                                                   environment=config.environment),
                           inspect=inspect_header, clock=clock, ids=UuidIds(),
                           challenge_site=os.environ.get("PRINCESS_CHALLENGE_SITE", "localhost"),
                           uploads_enabled=lambda: config.enabled("uploads"))
    if config.provider_mode("PaymentProvider") is not ProviderMode.FAKE:
        # Real Stripe/StoreKit/Play adapters wait on accounts, products and terms
        # (price_account_terms_before_charges); only the fake rails compose.
        raise Unsupported("payment_adapters_not_configured", detail="price_account_terms_before_charges")
    reports = lambda principal_id: PostgresReportStore(db, principal_id)  # noqa: E731
    commerce = CommerceService(
        ledger=PostgresLedger(db, UuidIds()),
        providers={rail: FakePaymentProvider(rail, catalog=CATALOG, clock=clock, environment=config.environment)
                   for rail in PaymentRail},
        permissions=permissions, reports=reports, clock=clock, ids=UuidIds(), environment=config.environment)
    kill_switches = dict(config.manifest.kill_switches)
    access = PostgresReportAccess(db)
    exports = ExportService(reports=reports, access=access, repo=PostgresExportRepository(db), store=store,
                            clock=clock, ids=UuidIds(), sharing_enabled=lambda: kill_switches.get("sharing", False),
                            permissions=permissions)
    return Services(environment=config.environment, clock=clock, identity=identity, permissions=permissions,
                    report_store_for=reports, kill_switches=kill_switches,
                    dev_identity=provider if isinstance(provider, FakeIdentityProvider) else None,
                    intake=intake, dev_store=store, commerce=commerce,
                    report_access=access, exports=exports,
                    feedback=FeedbackService(reports=reports, repo=PostgresFeedbackRepository(db), clock=clock),
                    tombstones=tombstone_log(),
                    # Registration and preferences only; delivery is the notification worker's.
                    notifications=NotificationService(repo=PostgresNotificationRepository(db), clock=clock,
                                                      ids=UuidIds(), environment=config.environment),
                    readiness=db.ping,
                    notices=NoticeCatalog.from_registry(ROOT / "contracts" / "consent" / "v1" / "notices.json",
                                                        allow_draft_policy=permissions.allows_draft_policy),
                    comparisons_enabled=True)


def local_store(config: RuntimeConfig, clock) -> LocalObjectStore:
    root = Path(os.environ.get("PRINCESS_LOCAL_STORAGE_DIR", str(ROOT / ".local-storage")))
    key_name = "PRINCESS_STORAGE_SIGNING_KEY" if config.component == "api" else "PRINCESS_STORAGE_READ_KEY"
    return LocalObjectStore(root, signing_key=config.secret(key_name).encode(), clock=clock,
                            environment=config.environment,
                            public_base=os.environ.get("PRINCESS_PUBLIC_API_BASE", "http://127.0.0.1:8000"))


def tombstone_log() -> JsonlTombstoneLog:
    """Kept apart from the database so a restore cannot roll it back
    (production: an append-only store, pending ADR-004)."""
    default = Path(os.environ.get("PRINCESS_LOCAL_STORAGE_DIR", str(ROOT / ".local-storage"))) / "tombstones"
    return JsonlTombstoneLog(Path(os.environ.get("PRINCESS_TOMBSTONE_DIR", str(default))))


def app_from_environment() -> FastAPI:
    return create_app(compose(load_runtime_config(os.environ, ROOT)))

