"""Tests for the Git-safe Supabase staging cleanup evidence builder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import build_supabase_staging_cleanup_evidence as cleanup

ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bind_project(monkeypatch):
    ref = "qualified-staging-ref"
    monkeypatch.setattr(cleanup, "PROJECT_REF_SHA256", _sha(ref))
    return ref


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
        "conformance_receipt_sha256": "a" * 64,
    }
    value.update(overrides)
    return value


def test_build_cleanup_evidence_is_non_identifying_and_fail_closed(monkeypatch):
    ref = _bind_project(monkeypatch)
    result = cleanup.build_cleanup_evidence(project_ref=ref, raw=_raw())
    assert result["result"] == "PASS"
    assert result["project_ref_sha256"] == _sha(ref)
    assert result["application_login_active"] is False
    assert result["production_activation"] is False
    assert result["persistent_princess_binding_created_by_witness"] is False
    assert result["project_decommission"] == "NOT_APPLICABLE"
    assert result["conformance_receipt_sha256"] == "a" * 64
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
        cleanup.build_cleanup_evidence(project_ref=ref, raw=_raw(**{field: value}))


def test_cleanup_requires_valid_conformance_receipt_hash(monkeypatch):
    ref = _bind_project(monkeypatch)
    for value in ("", "not-a-hash", "A" * 64, "a" * 63):
        with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_conformance_receipt_sha256"):
            cleanup.build_cleanup_evidence(
                project_ref=ref,
                raw=_raw(conformance_receipt_sha256=value),
            )


def test_cleanup_requires_exact_project_binding(monkeypatch):
    _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="project_ref_mismatch"):
        cleanup.build_cleanup_evidence(project_ref="other-project", raw=_raw())


def test_cleanup_rejects_extra_identifier_fields(monkeypatch):
    ref = _bind_project(monkeypatch)
    raw = _raw()
    raw["provider_user_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_input_shape"):
        cleanup.build_cleanup_evidence(project_ref=ref, raw=raw)


@pytest.mark.parametrize("count", [0, -1, True, "1", 1001])
def test_population_count_is_bounded_integer(monkeypatch, count):
    ref = _bind_project(monkeypatch)
    with pytest.raises(cleanup.CleanupEvidenceError, match="cleanup_population_count"):
        cleanup.build_cleanup_evidence(
            project_ref=ref,
            raw=_raw(affected_test_population_count=count),
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
