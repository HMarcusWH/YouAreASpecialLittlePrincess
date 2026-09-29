"""T24 runtime preflight and health semantics."""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from princess_api.app import Services, create_app
from princess_app.adapters.fakes import FakeClock
from princess_app.ports.base import Environment, InvalidInput, TransientUnavailable, Unsupported

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra" / "runtime"))
from runtime_policy import preflight  # noqa: E402

DB_TEST = "postgresql://runtime:runtime@127.0.0.1:5432/princess_test"
API_TEST = {
    "PRINCESS_ENV": "test",
    "PRINCESS_COMPONENT": "api",
    "PRINCESS_DATABASE_URL": DB_TEST,
    "PRINCESS_SESSION_SECRET": "runtime-session-0123456789",
    "PRINCESS_IDENTITY_AUDIENCE": "princess-runtime",
    "PRINCESS_STORAGE_SIGNING_KEY": "runtime-storage-0123456789",
}


def test_preflight_accepts_current_test_api_without_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("startup preflight attempted network I/O")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    config = preflight(API_TEST, ROOT)
    assert config.component == "api" and config.environment is Environment.TEST


@pytest.mark.parametrize("component", ["render_worker", "reference_worker"])
def test_dormant_boundaries_are_not_runtime_executables(component):
    with pytest.raises(InvalidInput) as err:
        preflight({"PRINCESS_ENV": "test", "PRINCESS_COMPONENT": component}, ROOT)
    assert err.value.code == "component_not_runtime_executable"


def test_production_manifest_is_not_mistaken_for_currently_composable_api():
    env = {
        "PRINCESS_ENV": "production",
        "PRINCESS_COMPONENT": "api",
        "PRINCESS_DATABASE_URL": "postgresql://runtime:prod-secret@db:5432/princess_production",
        "PRINCESS_SESSION_SECRET": "prod-session-0123456789",
        "PRINCESS_IDENTITY_AUDIENCE": "princess-prod",
        "PRINCESS_STORAGE_SIGNING_KEY": "prod-storage-0123456789",
    }
    with pytest.raises(Unsupported) as err:
        preflight(env, ROOT)
    assert err.value.code == "runtime_provider_not_configured"


def services(readiness):
    return Services(
        environment=Environment.TEST,
        clock=FakeClock(),
        identity=cast(Any, object()),
        permissions=cast(Any, object()),
        report_store_for=cast(Any, lambda _owner: None),
        readiness=readiness,
    )


def test_health_liveness_has_no_readiness_dependency():
    called = False
    def ready():
        nonlocal called
        called = True
    client = TestClient(create_app(services(ready)))
    assert client.get("/health/live").json() == {"status": "ok"}
    assert called is False
    assert "/health/live" not in client.get("/openapi.json").json()["paths"]


def test_health_readiness_is_low_cardinality_and_fails_closed():
    def unavailable():
        raise TransientUnavailable("database_unavailable")
    client = TestClient(create_app(services(unavailable)))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "/health/ready" not in client.get("/openapi.json").json()["paths"]
