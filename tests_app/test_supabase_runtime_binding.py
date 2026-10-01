"""Receipt-derived runtime binding for the qualified Supabase staging profile."""
from __future__ import annotations

import hashlib
import json

import pytest

import princess_app.config_supabase as binding_module
from princess_app.ports.base import InvalidInput


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


def test_other_supabase_project_and_binding_shape_are_rejected(monkeypatch):
    issuer, audience, _, manifest_hash, binding = _fixture(monkeypatch)
    other = "https://different-project.supabase.co/auth/v1"
    binding["issuer_sha256"] = _sha(other)
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
