"""Receipt-derived runtime binding for the qualified Supabase staging profile."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import build_supabase_staging_runtime_binding as binding_builder
import princess_app.config_supabase as binding_module
import princess_api.compose as compose_module
from princess_app.adapters.fakes import FakeClock
from princess_app.adapters.supabase import SupabaseIdentityProvider
from princess_app.config import load_runtime_config
from princess_app.ports import identity as identity_port
from princess_app.ports.base import Environment, InvalidInput, ProviderMode, Unsupported

ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(monkeypatch):
    project_ref = "qualified-staging-ref"
    issuer = f"https://{project_ref}.supabase.co/auth/v1"
    audience = "qualified-audience"
    role = "qualified-role"
    manifest_hash = "1" * 64
    receipt_hash = "2" * 64
    snapshot_hash = "3" * 64
    project_hash = _sha(project_ref)
    source_revision = "4" * 40
    monkeypatch.setattr(binding_module, "QUALIFIED_ENVIRONMENT_MANIFEST_SHA256", manifest_hash)
    monkeypatch.setattr(binding_module, "QUALIFICATION_RECEIPT_SHA256", receipt_hash)
    monkeypatch.setattr(binding_module, "ACCOUNT_SNAPSHOT_SHA256", snapshot_hash)
    monkeypatch.setattr(binding_module, "PROJECT_REF_SHA256", project_hash)
    monkeypatch.setattr(binding_module, "QUALIFIED_ISSUER_SHA256", _sha(issuer))
    monkeypatch.setattr(binding_module, "QUALIFIED_AUDIENCE_SHA256", _sha(audience))
    monkeypatch.setattr(binding_module, "QUALIFIED_ROLE_SHA256", _sha(role))
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
        "issuer_sha256": _sha(issuer),
        "audience": audience,
        "allowed_role": role,
        "stock_claims_profile": True,
    }
    return issuer, audience, role, manifest_hash, binding


def code(fn) -> str:
    with pytest.raises(InvalidInput) as err:
        fn()
    return err.value.code


def test_runtime_manifest_hash_is_line_ending_stable(tmp_path, monkeypatch):
    manifest_dir = tmp_path / "infra" / "environments"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "staging.json"
    lf = b'{\n  "providers": {"IdentityProvider": "sandbox"}\n}\n'
    crlf = lf.replace(b"\n", b"\r\n")

    monkeypatch.setattr(compose_module, "ROOT", tmp_path)

    manifest_path.write_bytes(lf)
    stable = compose_module._manifest_sha256(Environment.STAGING)

    manifest_path.write_bytes(crlf)
    assert compose_module._manifest_sha256(Environment.STAGING) == stable
    assert stable == hashlib.sha256(lf).hexdigest()


def test_builder_migrates_historical_crlf_receipt_anchor_to_stable_runtime_manifest(monkeypatch):
    qualification_manifest_hash = "1" * 64
    runtime_manifest_hash = "2" * 64
    issuer = "https://qualified-staging-ref.supabase.co/auth/v1"
    audience = "authenticated"
    role = "authenticated"
    project_ref_hash = _sha("qualified-staging-ref")

    receipt = {
        "project_alias": binding_builder.PROJECT_ALIAS,
        "evidence_kind": "MANAGED_PROJECT",
        "project_binding": binding_builder.PROJECT_BINDING,
        "environment": binding_builder.ENVIRONMENT,
        "provider_mode": binding_builder.PROVIDER_MODE,
        "environment_manifest_sha256": qualification_manifest_hash,
        "source_revision": binding_builder.SOURCE_REVISION,
        "stock_claims_profile": True,
        "result": "PASS",
        "issuer_sha256": _sha(issuer),
        "audience": audience,
        "allowed_role": role,
    }
    receipt_bytes = json.dumps(receipt, sort_keys=True).encode("utf-8")
    snapshot = {
        "project_alias": binding_builder.PROJECT_ALIAS,
        "project_ref_sha256": project_ref_hash,
        "contains_secrets": False,
        "production_activation": False,
    }

    monkeypatch.setattr(binding_builder, "validate_receipt", lambda value: None)
    monkeypatch.setattr(binding_builder, "QUALIFICATION_RECEIPT_SHA256", hashlib.sha256(receipt_bytes).hexdigest())
    monkeypatch.setattr(binding_builder, "QUALIFICATION_ENVIRONMENT_MANIFEST_SHA256", qualification_manifest_hash)
    monkeypatch.setattr(binding_builder, "QUALIFIED_ENVIRONMENT_MANIFEST_SHA256", runtime_manifest_hash)
    monkeypatch.setattr(binding_builder, "ACCOUNT_SNAPSHOT_SHA256", binding_builder._canonical_hash(snapshot))
    monkeypatch.setattr(binding_builder, "PROJECT_REF_SHA256", project_ref_hash)
    monkeypatch.setattr(binding_builder, "QUALIFIED_ISSUER_SHA256", _sha(issuer))
    monkeypatch.setattr(binding_builder, "QUALIFIED_AUDIENCE_SHA256", _sha(audience))
    monkeypatch.setattr(binding_builder, "QUALIFIED_ROLE_SHA256", _sha(role))

    built = binding_builder.build_binding(receipt_bytes, snapshot)
    assert built["qualified_environment_manifest_sha256"] == runtime_manifest_hash
    assert built["qualified_environment_manifest_sha256"] != qualification_manifest_hash


def test_receipt_binding_accepts_only_exact_runtime_profile(monkeypatch):
    issuer, audience, role, manifest_hash, binding = _fixture(monkeypatch)
    parsed = binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding),
        issuer=issuer,
        audience=audience,
        current_manifest_sha256=manifest_hash,
    )
    assert parsed.allowed_role == role
    assert parsed.audience == audience
    assert parsed.issuer_sha256 == _sha(issuer)


@pytest.mark.parametrize("field", [
    "qualification_receipt_sha256",
    "qualified_environment_manifest_sha256",
    "account_snapshot_sha256",
    "project_ref_sha256",
    "source_revision",
])
def test_evidence_anchor_changes_fail_closed(monkeypatch, field):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    binding[field] = "f" * len(binding[field])
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_mismatch"


def test_issuer_audience_role_and_manifest_drift_fail_closed(monkeypatch):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer + "/other", audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_issuer_mismatch"
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience="other", current_manifest_sha256=manifest_hash
    )) == "identity_runtime_audience_mismatch"
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256="9" * 64
    )) == "identity_runtime_manifest_changed"

    binding["allowed_role"] = "service_role"
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_role"

    _, _, _, _, binding = _fixture(monkeypatch)
    binding["audience"] = "other-qualified-looking-audience"
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_mismatch"

    _, _, _, _, binding = _fixture(monkeypatch)
    binding["allowed_role"] = "other-qualified-looking-role"
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_mismatch"


def test_other_supabase_project_and_binding_shape_are_rejected(monkeypatch):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    other = "https://different-project.supabase.co/auth/v1"
    binding["issuer_sha256"] = _sha(other)
    # Pass the exact-issuer evidence layer deliberately so this regression
    # still proves the independent project-ref pin rejects another project.
    monkeypatch.setattr(binding_module, "QUALIFIED_ISSUER_SHA256", _sha(other))
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=other, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_project_mismatch"

    _, _, _, _, binding = _fixture(monkeypatch)
    binding["extra"] = True
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        json.dumps(binding), issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_shape"


def test_duplicate_binding_keys_are_rejected(monkeypatch):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    raw = json.dumps(binding)[:-1] + ',"audience":"other"}'
    assert code(lambda: binding_module.parse_supabase_staging_runtime_binding(
        raw, issuer=issuer, audience=audience, current_manifest_sha256=manifest_hash
    )) == "identity_runtime_binding_duplicate_key"


def test_api_composes_only_the_qualified_staging_sandbox_profile(monkeypatch):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    monkeypatch.setattr(compose_module, "_manifest_sha256", lambda _environment: manifest_hash)
    env = {
        "PRINCESS_ENV": "staging",
        "PRINCESS_COMPONENT": "api",
        "PRINCESS_DATABASE_URL": "postgresql://svc:stage-secret@db/princess_staging",
        "PRINCESS_SESSION_SECRET": "stage-session-0123456789",
        "PRINCESS_IDENTITY_AUDIENCE": audience,
        "PRINCESS_STORAGE_SIGNING_KEY": "stage-storage-0123456789",
        "PRINCESS_IDENTITY_ISSUER": issuer,
        "PRINCESS_IDENTITY_BINDING": json.dumps(binding),
    }
    config = load_runtime_config(env, ROOT)
    provider = compose_module.compose_identity_provider(config, FakeClock())
    assert isinstance(provider, SupabaseIdentityProvider)
    assert provider.profile.capabilities == frozenset({identity_port.VERIFY_CREDENTIAL})
    assert provider.allowed_roles == frozenset({binding["allowed_role"]})

    providers = dict(config.manifest.providers)
    providers["IdentityProvider"] = ProviderMode.LIVE
    live = replace(config, manifest=replace(config.manifest, providers=MappingProxyType(providers)))
    with pytest.raises(Unsupported) as err:
        compose_module.compose_identity_provider(live, FakeClock())
    assert err.value.code == "identity_adapter_not_configured"
