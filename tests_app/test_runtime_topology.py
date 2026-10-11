"""T24 runtime preflight and health semantics."""
from __future__ import annotations

import hashlib
import json
import socket
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from princess_api.app import Services, create_app
from princess_app.adapters.fakes import FakeClock
from princess_app.application.intake import analysis_config_sha256, runtime_analysis_profile_and_config
import princess_app.config_supabase as binding_module
from princess_app.ports.base import Environment, InvalidInput, TransientUnavailable, Unsupported

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra" / "runtime"))
import runtime_policy  # noqa: E402
import railway_test_stack  # noqa: E402
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


def test_runtime_preflight_manifest_hash_is_line_ending_stable(tmp_path):
    manifest_dir = tmp_path / "infra" / "environments"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "staging.json"
    lf = b'{\n  "providers": {"IdentityProvider": "sandbox"}\n}\n'
    crlf = lf.replace(b"\n", b"\r\n")

    manifest_path.write_bytes(lf)
    stable = runtime_policy._manifest_sha256(tmp_path, Environment.STAGING)

    manifest_path.write_bytes(crlf)
    assert runtime_policy._manifest_sha256(tmp_path, Environment.STAGING) == stable
    assert stable == hashlib.sha256(lf).hexdigest()


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


def test_staging_identity_support_moves_fail_closed_boundary_to_object_store(monkeypatch):
    project_ref = "runtime-staging-ref"
    issuer = f"https://{project_ref}.supabase.co/auth/v1"
    audience = "runtime-staging-audience"
    manifest_hash = runtime_policy._manifest_sha256(ROOT, Environment.STAGING)
    receipt_hash = "2" * 64
    snapshot_hash = "3" * 64
    project_hash = hashlib.sha256(project_ref.encode()).hexdigest()
    source_revision = "4" * 40
    monkeypatch.setattr(binding_module, "QUALIFIED_ENVIRONMENT_MANIFEST_SHA256", manifest_hash)
    monkeypatch.setattr(binding_module, "QUALIFICATION_RECEIPT_SHA256", receipt_hash)
    monkeypatch.setattr(binding_module, "ACCOUNT_SNAPSHOT_SHA256", snapshot_hash)
    monkeypatch.setattr(binding_module, "PROJECT_REF_SHA256", project_hash)
    monkeypatch.setattr(binding_module, "QUALIFIED_ISSUER_SHA256", hashlib.sha256(issuer.encode()).hexdigest())
    monkeypatch.setattr(binding_module, "QUALIFIED_AUDIENCE_SHA256", hashlib.sha256(audience.encode()).hexdigest())
    monkeypatch.setattr(binding_module, "QUALIFIED_ROLE_SHA256", hashlib.sha256(b"authenticated").hexdigest())
    monkeypatch.setattr(binding_module, "SOURCE_REVISION", source_revision)
    binding = {
        "version": binding_module.BINDING_VERSION,
        "provider": binding_module.PROVIDER,
        "project_alias": binding_module.PROJECT_ALIAS,
        "project_binding": binding_module.PROJECT_BINDING,
        "environment": binding_module.ENVIRONMENT,
        "provider_mode": binding_module.PROVIDER_MODE,
        "qualification_receipt_sha256": receipt_hash,
        "qualified_environment_manifest_sha256": manifest_hash,
        "account_snapshot_sha256": snapshot_hash,
        "project_ref_sha256": project_hash,
        "source_revision": source_revision,
        "issuer_sha256": hashlib.sha256(issuer.encode()).hexdigest(),
        "audience": audience,
        "allowed_role": "authenticated",
        "stock_claims_profile": True,
    }
    env = {
        "PRINCESS_ENV": "staging",
        "PRINCESS_COMPONENT": "api",
        "PRINCESS_DATABASE_URL": "postgresql://runtime:stage-secret@db:5432/princess_staging",
        "PRINCESS_SESSION_SECRET": "stage-session-0123456789",
        "PRINCESS_IDENTITY_AUDIENCE": audience,
        "PRINCESS_STORAGE_SIGNING_KEY": "stage-storage-0123456789",
        "PRINCESS_IDENTITY_ISSUER": issuer,
        "PRINCESS_IDENTITY_BINDING": json.dumps(binding),
    }
    with pytest.raises(Unsupported) as err:
        preflight(env, ROOT)
    assert err.value.code == "runtime_provider_not_configured"
    assert err.value.detail == "api:ObjectStore"


def services(readiness):
    return Services(
        environment=Environment.TEST,
        clock=FakeClock(),
        identity=cast(Any, object()),
        permissions=cast(Any, object()),
        report_store_for=cast(Any, lambda _owner: None),
        readiness=readiness,
    )


def test_public_synthetic_guest_endpoint_refuses_account_bearers():
    api = services(lambda: None)
    api.guest_only = True
    client = TestClient(create_app(api))
    response = client.get("/v1/me", headers={"Authorization": "Bearer fakeid.kid-1.tok_1234"})
    assert response.status_code == 401
    assert response.json() == {"error": "guest_only_test_endpoint"}


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


def test_railway_test_stack_forwards_git_provenance_only_to_api(monkeypatch):
    """The API must get genuine Railway source metadata; the worker must not."""
    monkeypatch.setattr(railway_test_stack, "preflight", lambda _env, _root: None)
    for key, value in {
        "PRINCESS_ENV": "test",
        "PRINCESS_API_DATABASE_URL": "postgresql://api:synthetic@db/princess_test",
        "PRINCESS_WORKER_DATABASE_URL": "postgresql://worker:synthetic@db/princess_test",
        "PRINCESS_SESSION_SECRET": "synthetic-only-api-session",
        "PRINCESS_IDENTITY_AUDIENCE": "princess-api",
        "PRINCESS_STORAGE_SIGNING_KEY": "synthetic-only-api-storage",
        "PRINCESS_STORAGE_READ_KEY": "synthetic-only-worker-storage",
        "RAILWAY_GIT_COMMIT_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    api_env = railway_test_stack.role_env("api")
    worker_env = railway_test_stack.role_env("analysis_worker")
    assert api_env["RAILWAY_GIT_COMMIT_SHA"] == "a" * 40
    assert "RAILWAY_GIT_COMMIT_SHA" not in worker_env
    assert "PRINCESS_STORAGE_READ_KEY" not in api_env
    assert "PRINCESS_SESSION_SECRET" not in worker_env
    fingerprint = analysis_config_sha256(grid_profile="legacy")
    assert api_env["PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256"] == fingerprint
    assert worker_env["PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256"] == fingerprint
    assert runtime_analysis_profile_and_config(api_env) == ("legacy", fingerprint)
    assert runtime_analysis_profile_and_config(worker_env) == ("legacy", fingerprint)


def test_railway_test_stack_does_not_fabricate_missing_git_commit(monkeypatch):
    """A deployment without Railway Git metadata must fail closed at /health/build."""
    monkeypatch.setattr(railway_test_stack, "preflight", lambda _env, _root: None)
    for key, value in {
        "PRINCESS_ENV": "test",
        "PRINCESS_API_DATABASE_URL": "postgresql://api:synthetic@db/princess_test",
        "PRINCESS_SESSION_SECRET": "synthetic-only-api-session",
        "PRINCESS_IDENTITY_AUDIENCE": "princess-api",
        "PRINCESS_STORAGE_SIGNING_KEY": "synthetic-only-api-storage",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    api_env = railway_test_stack.role_env("api")
    assert "RAILWAY_GIT_COMMIT_SHA" not in api_env

def test_preflight_refuses_unapproved_grid_runtime_before_any_engine_is_started():
    worker = {"PRINCESS_ENV": "test", "PRINCESS_COMPONENT": "analysis_worker",
              "PRINCESS_DATABASE_URL": DB_TEST,
              "PRINCESS_STORAGE_READ_KEY": "runtime-worker-read-0123456789"}
    for base in (API_TEST, worker):
        for overrides in (
            {"PRINCESS_ANALYSIS_PROFILE": "grid-v1"},
            {"PRINCESS_ANALYSIS_PROFILE": "grid-v1",
             "PRINCESS_GRID_V1_RESEARCH_OPT_IN": "1",
             "PRINCESS_TEST_PUBLIC_GUEST_ONLY": "1"},
            {"PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256": "0" * 64},
        ):
            with pytest.raises(ValueError):
                preflight({**base, **overrides}, ROOT)


def test_railway_private_test_only_profile_is_shared_and_pinned(monkeypatch):
    monkeypatch.setattr(railway_test_stack, "preflight", lambda _env, _root: None)
    for key, value in {
        "PRINCESS_ENV": "test",
        "PRINCESS_ANALYSIS_PROFILE": "grid-v1",
        "PRINCESS_GRID_V1_RESEARCH_OPT_IN": "1",
        "PRINCESS_API_DATABASE_URL": "postgresql://api:test@db/princess_test",
        "PRINCESS_WORKER_DATABASE_URL": "postgresql://worker:test@db/princess_test",
        "PRINCESS_SESSION_SECRET": "test-session",
        "PRINCESS_IDENTITY_AUDIENCE": "test-audience",
        "PRINCESS_STORAGE_SIGNING_KEY": "test-signing",
        "PRINCESS_STORAGE_READ_KEY": "test-read",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PRINCESS_TEST_PUBLIC_GUEST_ONLY", raising=False)
    monkeypatch.delenv("PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256", raising=False)
    a, w = railway_test_stack.role_env("api"), railway_test_stack.role_env("analysis_worker")
    digest = analysis_config_sha256(grid_profile="grid-v1")
    assert a["PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256"] == digest
    assert w["PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256"] == digest
    assert runtime_analysis_profile_and_config(a) == ("grid-v1", digest)
    assert runtime_analysis_profile_and_config(w) == ("grid-v1", digest)
    monkeypatch.setenv("PRINCESS_TEST_PUBLIC_GUEST_ONLY", "1")
    with pytest.raises(RuntimeError, match="grid-v1 is not approved"):
        railway_test_stack.role_env("api")
    with pytest.raises(RuntimeError, match="grid-v1 is not approved"):
        railway_test_stack.role_env("analysis_worker")


def test_build_endpoint_announces_the_service_processing_hash(monkeypatch):
    app_services = services(lambda: None)
    # Health provenance must follow the composed API configuration, rather
    # than a module import-time constant from an unrelated process.
    app_services.analysis_config_sha256 = analysis_config_sha256(grid_profile="grid-v1")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "b" * 40)
    response = TestClient(create_app(app_services)).get("/health/build")
    assert response.status_code == 200
    assert response.json()["analysis_config_sha256"] == app_services.analysis_config_sha256

def test_qualified_v2_independent_services_require_identical_reviewed_pin():
    from princess_app.application.intake import analysis_config_sha256
    env = {'PRINCESS_ENV': 'test',
           'PRINCESS_ANALYSIS_PROFILE': 'qualified-v2',
           'PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN': '1'}
    api = {**API_TEST, **env}
    with pytest.raises(ValueError, match='paired API/worker'):
        preflight(api, ROOT)
    digest = analysis_config_sha256(grid_profile='qualified-v2')
    expected = {**api, 'PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256': digest}
    assert preflight(expected, ROOT).component == 'api'
    with pytest.raises(ValueError, match='analysis_config_mismatch'):
        preflight({**api, 'PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256': '0' * 64}, ROOT)
