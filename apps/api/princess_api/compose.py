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

from princess_app.adapters.fakes import FakeIdentityProvider
from princess_app.adapters.postgres.stores import (
    Database,
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
    make_engine,
)
from princess_app.application.identity import IdentityService
from princess_app.application.permissions import PermissionService
from princess_app.config import RuntimeConfig, load_runtime_config
from princess_app.ports.base import ProviderMode, SystemClock, Unsupported

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
    permissions = PermissionService(PostgresPermissionStore(db), clock, UuidIds())
    return Services(environment=config.environment, clock=clock, identity=identity, permissions=permissions,
                    report_store_for=lambda principal_id: PostgresReportStore(db, principal_id),
                    kill_switches=dict(config.manifest.kill_switches), dev_identity=provider, audience=audience)


def app_from_environment() -> FastAPI:
    return create_app(compose(load_runtime_config(os.environ, ROOT)))

