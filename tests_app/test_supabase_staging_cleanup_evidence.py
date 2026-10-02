"""Tests for the Git-safe Supabase staging cleanup evidence builder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import build_supabase_staging_cleanup_evidence as cleanup
import verify_supabase_staging_runtime as conformance

ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bind_project(monkeypatch):
    ref = "qualified-staging-ref"
    monkeypatch.setattr(cleanup, "PROJECT_REF_SHA256", _sha(ref))
    return ref


def _conformance_receipt_bytes(**overrides) -> bytes:
    receipt = {
        "version": conformance.VERSION,
        "provider": "supabase-auth",
        "project_alias": conformance.binding_config.PROJECT_ALIAS,
        "environment": "staging",
        "provider_mode": "sandbox",
        "capability": conformance.identity_port.VERIFY_CREDENTIAL,
        "checked_date": "2026-10-02",
        "princess_commit": "7cf6371a1daec3cfd46f4adf35d6175c57452cc0",
        "qualification_receipt_sha256": conformance.binding_config.QUALIFICATION_RECEIPT_SHA256,
        "runtime_binding_sha256": "b" * 64,
        "account_snapshot_sha256": conformance.binding_config.ACCOUNT_SNAPSHOT_SHA256,
        "qualified_environment_manifest_sha256": conformance.binding_config.QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
        "project_ref_sha256": conformance.binding_config.PROJECT_REF_SHA256,
        "issuer_sha256": conformance.binding_config.QUALIFIED_ISSUER_SHA256,
        "audience_sha256": conformance.binding_config.QUALIFIED_AUDIENCE_SHA256,
        "role_sha256": conformance.binding_config.QUALIFIED_ROLE_SHA256,
        "source_revision": conformance.binding_config.SOURCE_REVISION,
        "jwks_fetch_observed": True,
        "credential_verified": True,
        "identity_service_authenticated": True,
        "stable_principal_mapping": True,
        "principal_kind": "ACCOUNT",
        "auth_time_present": True,
        "session_id_present": True,
        "credential_unexpired": True,
        "provider_cleanup_required": True,
        "provider_cleanup_performed_by_tool": False,
        "application_login": False,
        "production_activation": False,
        "global_gate_closure": False,
        "result": "PASS",
    }
    receipt.update(overrides)
    return (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _raw(**overrides):
    value = {
        "checked_date": "2026-10-02",
        "operator_role": "product/technical owner",
        "affected_test_population_count": 1,
        "all_sessions_for_test_user_revoked": True,
        "provider_refresh_state_revoked": True,
        "disposable_auth_user_deleted": True,
        "persistent_princess_binding_created_by_witness": False,
        "application_login_active": False,
        "jwt_age_out_required": True,
        "project_decommission": "NOT_APPLICABLE",
        "production_activation": False,
        "protected_evidence_ref": "operator-local:princess-staging-cleanup-2026-10-02",
    }
    value.update(overrides)
    return value


def _build(monkeypatch, **raw_overrides):
    ref = _bind_project(monkeypatch)
    receipt_bytes = _conformance_receipt_bytes()
    result = cleanup.build_cleanup_evidence(
        project_ref=ref,
        raw=_raw(**raw_overrides),
        conformance_receipt_bytes=receipt_bytes,
    )
    return ref, receipt_bytes, result


def test_build_cleanup_evidence_is_non_identifying_and_receipt_bound(monkeypatch):
    ref, receipt_bytes, result = _build(monkeypatch)
    assert result["result"] == "PASS"
    assert result["project_ref_sha256"] == _sha(ref)
    assert result["application_login_active"] is False
    assert result["production_activation"] is False
    assert result["persistent_princess_binding_created_by_witness"] is False
    assert result["project_decommission"] == "NOT_APPLICABLE"
    assert result["affected_test_population_count"] == 1
    assert result["conformance_receipt_sha256"] == hashlib.sha256(receipt_bytes).hexdigest()
    rendered = json.dumps(result, sort_keys=True)
    assert ref not in rendered
    assert "provider_user_id" not in result
    assert "session_id" not in result
    assert "11111111-1111-4111-8111-111111111111" not in rendered


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("all_sessions_for_test_user_revoked", False, "cleanup_all_sessions_for_test_user_revoked"),
        ("provider_refresh_state_revoked", False, "cleanup_provider_refresh_state_revoked"),
        ("disposable_auth_user_deleted", False, "cleanup_disposable_auth_user_deleted"),
        ("persistent_princess_binding_created_by_witness", True, "cleanup_persistent_princess_binding_created_by_witness"),
        ("application_login_active", True, "cleanup_application_login_active"),
        ("jwt_age_out_required", False, "cleanup_jwt_age_out_required"),
        ("production_activation", True, "cleanup_production_activation"),
        ("project_decommission", "PASS", "cleanup_project_decommission"),
    ],
)
def test_cleanup_cannot_overclaim(monkeypatch, field, value, code):
    ref = _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match=code):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=_raw(**{field: value}),
            conformance_receipt_bytes=_conformance_receipt_bytes(),
        )


def test_cleanup_rejects_manual_conformance_digest(monkeypatch):
    ref = _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_input_shape"):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=_raw(conformance_receipt_sha256="a" * 64),
            conformance_receipt_bytes=_conformance_receipt_bytes(),
        )


@pytest.mark.parametrize(
    "receipt_bytes",
    [
        b"{}",
        _conformance_receipt_bytes(result="FAIL"),
        _conformance_receipt_bytes(princess_commit="not-a-commit"),
    ],
)
def test_cleanup_requires_valid_protected_conformance_receipt(monkeypatch, receipt_bytes):
    ref = _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_conformance_receipt_invalid"):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=_raw(),
            conformance_receipt_bytes=receipt_bytes,
        )


def test_cleanup_requires_exact_project_binding(monkeypatch):
    _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="project_ref_mismatch"):
        cleanup.build_cleanup_evidence(
            project_ref="other-project",
            raw=_raw(),
            conformance_receipt_bytes=_conformance_receipt_bytes(),
        )


def test_cleanup_rejects_extra_identifier_fields(monkeypatch):
    ref = _bind_project(monkeypatch)
    raw = _raw()
    raw["provider_user_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_input_shape"):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=raw,
            conformance_receipt_bytes=_conformance_receipt_bytes(),
        )


@pytest.mark.parametrize("count", [0, -1, True, "1", 2, 1000, 1001])
def test_population_count_must_be_exactly_one(monkeypatch, count):
    ref = _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_population_count"):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=_raw(affected_test_population_count=count),
            conformance_receipt_bytes=_conformance_receipt_bytes(),
        )


def test_protected_inputs_cannot_live_in_checkout(tmp_path):
    with pytest.raises(cleanup.CleanupEvidenceError, match="project_ref_inside_repository"):
        cleanup._protected_input(ROOT / "README.md", "project_ref")
    external = tmp_path / "cleanup.json"
    external.write_text("{}", encoding="utf-8")
    assert cleanup._protected_input(external, "cleanup_input") == external.resolve()


def test_output_path_is_canonical(tmp_path):
    with pytest.raises(cleanup.CleanupEvidenceError, match="output_path_not_canonical"):
        cleanup._canonical_output(tmp_path / "cleanup.json")
