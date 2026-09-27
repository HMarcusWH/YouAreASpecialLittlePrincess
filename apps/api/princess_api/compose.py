"""Compose the API from a validated runtime configuration.

Only fake-mode identity is wired today; sandbox/live identity requires the
ADR-002 vendor decision and fails explicitly instead of silently falling back.
Run locally with::

    PRINCESS_ENV=local PRINCESS_COMPONENT=api PRINCESS_DATABASE_URL=... \\
    PRINCESS_SESSION_SECRET=... PRINCESS_IDENTITY_AUDIENCE=princess-local \\
    PRINCESS_STORAGE_SIGNING_KEY=... uvicorn --factory princess_api.compose:app_from_environment
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from princess_app.adapters.fakes import FakeAbuseChallenge, FakeIdentityProvider
from princess_app.adapters.imaging import inspect_header
from princess_app.adapters.localfs import LocalObjectStore
from princess_app.adapters.postgres.intake import PostgresIntakeRepository
from princess_app.adapters.postgres.stores import (
    Database,
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
    make_engine,
)
from princess_app.application.identity import IdentityService
from princess_app.application.intake import IntakeService
from princess_app.application.permissions import PermissionService
from princess_app.config import RuntimeConfig, load_runtime_config
from princess_app.ports.base import Environment, ProviderMode, SystemClock, Unsupported
from princess_graphology import __version__ as ENGINE_VERSION

from .app import Services, create_app

ROOT = Path(__file__).resolve().parents[3]


class UuidIds:
    def new_id(self, prefix: str) -> str:
        import uuid

        return f"{prefix}_{uuid.uuid4().hex}"


def compose(config: RuntimeConfig) -> Services:
    if config.component != "api":
        raise Unsupported("wrong_component", detail=config.component)
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    clock = SystemClock()
    audience = config.secret("PRINCESS_IDENTITY_AUDIENCE")
    if config.provider_mode("IdentityProvider") is not ProviderMode.FAKE:
        raise Unsupported("identity_adapter_not_configured", detail="ADR-002 vendor pending")
    provider = FakeIdentityProvider(clock=clock, environment=config.environment)
    identity = IdentityService(provider, PostgresIdentityStore(db), clock, UuidIds(), audience)
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
    return Services(environment=config.environment, clock=clock, identity=identity, permissions=permissions,
                    report_store_for=lambda principal_id: PostgresReportStore(db, principal_id),
                    kill_switches=dict(config.manifest.kill_switches), dev_identity=provider, audience=audience,
                    intake=intake, dev_store=store)


def local_store(config: RuntimeConfig, clock) -> LocalObjectStore:
    root = Path(os.environ.get("PRINCESS_LOCAL_STORAGE_DIR", str(ROOT / ".local-storage")))
    key_name = "PRINCESS_STORAGE_SIGNING_KEY" if config.component == "api" else "PRINCESS_STORAGE_READ_KEY"
    return LocalObjectStore(root, signing_key=config.secret(key_name).encode(), clock=clock,
                            environment=config.environment,
                            public_base=os.environ.get("PRINCESS_PUBLIC_API_BASE", "http://127.0.0.1:8000"))


def app_from_environment() -> FastAPI:
    return create_app(compose(load_runtime_config(os.environ, ROOT)))

