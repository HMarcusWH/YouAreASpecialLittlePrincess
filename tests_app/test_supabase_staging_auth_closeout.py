"""Tests for the Supabase staging Auth closeout checker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import check_supabase_staging_auth_closeout as closeout
import verify_supabase_staging_runtime as conformance
from build_supabase_auth_settings_snapshot import SAFE_PROVIDER_FIELDS
from princess_app.config_supabase import (
    ACCOUNT_SNAPSHOT_SHA256,
    PROJECT_REF_SHA256,
    QUALIFICATION_RECEIPT_SHA256,
    QUALIFIED_AUDIENCE_SHA256,
    QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
    QUALIFIED_ISSUER_SHA256,
    QUALIFIED_ROLE_SHA256,
    QUALIFIED_RUNTIME_BINDING_SHA256,
    SOURCE_REVISION,
)

CONFORMANCE_RECEIPT_SHA256 = "a" * 64
RUNTIME_BINDING_SHA256 = QUALIFIED_RUNTIME_BINDING_SHA256


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _conformance_receipt(**overrides):
    receipt = {
        "version": conformance.VERSION,
        "provider": "supabase-auth",
        "project_alias": "princess-staging",
        "environment": "staging",
        "provider_mode": "sandbox",
        "capability": conformance.identity_port.VERIFY_CREDENTIAL,
        "checked_date": "2026-10-02",
        "princess_commit": closeout.FROZEN_CONFORMANCE_COMMIT,
        "qualification_receipt_sha256": QUALIFICATION_RECEIPT_SHA256,
        "runtime_binding_sha256": RUNTIME_BINDING_SHA256,
        "account_snapshot_sha256": ACCOUNT_SNAPSHOT_SHA256,
        "qualified_environment_manifest_sha256": QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "issuer_sha256": QUALIFIED_ISSUER_SHA256,
        "audience_sha256": QUALIFIED_AUDIENCE_SHA256,
        "role_sha256": QUALIFIED_ROLE_SHA256,
        "source_revision": SOURCE_REVISION,
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
    return receipt


def _conformance_text(**overrides):
    return conformance.render_safe_index(
        _conformance_receipt(**overrides),
        receipt_sha256=CONFORMANCE_RECEIPT_SHA256,
        protected_evidence_ref="operator-local:runtime-conformance",
    )


def _write_world(root: Path):
    ci = root / "docs" / "ci"
    ci.mkdir(parents=True)

    (ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md").write_text(
        _conformance_text(), encoding="utf-8"
    )

    projection = {
        "rate_limit_anonymous_users": 30,
        "rate_limit_email_sent": 2,
        "rate_limit_sms_sent": 30,
        "rate_limit_verify": 360,
        "rate_limit_token_refresh": 1800,
        "rate_limit_otp": 30,
        "rate_limit_web3": 30,
        "security_sb_forwarded_for_enabled": False,
    }
    auth = {
        "snapshot_version": "supabase-auth-settings/3",
        "provider": "supabase-auth",
        "project_alias": "princess-staging",
        "environment": "staging",
        "provider_mode": "sandbox",
        "captured_date": "2026-10-02",
        "source_kind": "SUPABASE_MANAGEMENT_API",
        "source_action": "GET /v1/projects/{ref}/config/auth",
        "project_ref_sha256": PROJECT_REF_SHA256,
        "source_response_sha256": "d" * 64,
        "protected_evidence_ref": "operator-local:auth-config",
        "safe_projection_sha256": hashlib.sha256(_canonical_bytes(projection)).hexdigest(),
        **projection,
        "contains_secrets": False,
        "application_login_activation": False,
        "production_activation": False,
    }
    auth["evidence_sha256"] = hashlib.sha256(_canonical_bytes(auth)).hexdigest()
    assert set(projection) == set(SAFE_PROVIDER_FIELDS)
    (ci / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json").write_text(
        json.dumps(auth), encoding="utf-8"
    )

    cleanup = {
        "version": "supabase-staging-cleanup/2",
        "provider": "supabase-auth",
        "project_alias": "princess-staging",
        "environment": "staging",
        "provider_mode": "sandbox",
        "project_ref_sha256": PROJECT_REF_SHA256,
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
        "contains_provider_user_ids": False,
        "contains_session_ids": False,
        "contains_secrets": False,
        "protected_evidence_ref": "operator-local:cleanup",
        "conformance_receipt_sha256": CONFORMANCE_RECEIPT_SHA256,
        "result": "PASS",
    }
    (ci / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json").write_text(
        json.dumps(cleanup), encoding="utf-8"
    )

    account = "\n".join([
        "application_login:      NOT APPROVED BY THIS DECISION",
        "production_activation:  false",
        "global_gate_closure:    false",
        "",
    ])
    (ci / "T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md").write_text(
        account, encoding="utf-8"
    )
    return ci


def test_real_conformance_renderer_output_is_closeout_compatible(tmp_path):
    _write_world(tmp_path)
    closeout.check_closeout(tmp_path)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("T17_SUPABASE_RUNTIME_CONFORMANCE.md", "runtime_conformance_missing"),
        ("T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json", "auth_settings_snapshot_missing"),
        ("T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json", "cleanup_evidence_missing"),
    ],
)
def test_closeout_fails_when_any_evidence_class_is_missing(tmp_path, name, code):
    ci = _write_world(tmp_path)
    (ci / name).unlink()
    with pytest.raises(Exception, match=code):
        closeout.check_closeout(tmp_path)


def test_pending_conformance_cannot_close_gate(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
    p.write_text(
        "# x\n\n**Status: PENDING REAL STAGING RUN.**\n",
        encoding="utf-8",
    )
    with pytest.raises(closeout.CloseoutError, match="runtime_conformance_not_pass"):
        closeout.check_closeout(tmp_path)


def test_conformance_must_bind_exact_frozen_commit(tmp_path):
    ci = _write_world(tmp_path)
    (ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md").write_text(
        _conformance_text(princess_commit="f" * 40),
        encoding="utf-8",
    )
    with pytest.raises(closeout.CloseoutError, match="runtime_conformance_commit_binding"):
        closeout.check_closeout(tmp_path)


def test_conformance_must_bind_qualification_anchor(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
    valid = _conformance_text()
    p.write_text(
        valid.replace(QUALIFICATION_RECEIPT_SHA256, "c" * 64, 1),
        encoding="utf-8",
    )
    with pytest.raises(closeout.CloseoutError, match="runtime_conformance_qualification_receipt_sha256"):
        closeout.check_closeout(tmp_path)


def test_conformance_must_bind_exact_runtime_binding_digest(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
    valid = _conformance_text()
    p.write_text(
        valid.replace(QUALIFIED_RUNTIME_BINDING_SHA256, "b" * 64, 1),
        encoding="utf-8",
    )
    with pytest.raises(closeout.CloseoutError, match="runtime_conformance_runtime_binding_sha256"):
        closeout.check_closeout(tmp_path)


def test_cleanup_must_bind_same_conformance_receipt(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    data = json.loads(p.read_text())
    data["conformance_receipt_sha256"] = "c" * 64
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(closeout.CloseoutError, match="cleanup_conformance_receipt_mismatch"):
        closeout.check_closeout(tmp_path)


def test_auth_settings_valid_digest_edit_fails_evidence_envelope(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
    data = json.loads(p.read_text())
    data["source_response_sha256"] = "e" * 64
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Exception, match="auth_settings_snapshot_evidence_hash"):
        closeout.check_closeout(tmp_path)


def test_auth_settings_cannot_predate_conformance(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
    data = json.loads(p.read_text())
    data["captured_date"] = "2026-10-01"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(closeout.CloseoutError, match="auth_settings_before_conformance"):
        closeout.check_closeout(tmp_path)


def test_cleanup_cannot_predate_conformance_at_final_gate(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    data = json.loads(p.read_text())
    data["checked_date"] = "2026-10-01"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(closeout.CloseoutError, match="cleanup_before_conformance"):
        closeout.check_closeout(tmp_path)


def test_cleanup_cannot_predate_auth_settings(tmp_path):
    ci = _write_world(tmp_path)
    auth_path = ci / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
    auth = json.loads(auth_path.read_text())
    auth["captured_date"] = "2026-10-03"
    auth_path.write_text(json.dumps(auth), encoding="utf-8")
    cleanup_path = ci / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    cleanup = json.loads(cleanup_path.read_text())
    cleanup["checked_date"] = "2026-10-02"
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(closeout.CloseoutError, match="cleanup_before_auth_settings"):
        closeout.check_closeout(tmp_path)


def test_closeout_rejects_owner_scope_widening(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md"
    p.write_text(
        "application_login:      APPROVED\n"
        "production_activation:  false\n"
        "global_gate_closure:    false\n",
        encoding="utf-8",
    )
    with pytest.raises(closeout.CloseoutError, match="application_login_owner_gate_widened"):
        closeout.check_closeout(tmp_path)


def test_cleanup_evidence_cannot_claim_project_decommission(tmp_path):
    ci = _write_world(tmp_path)
    p = ci / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    data = json.loads(p.read_text())
    data["project_decommission"] = "PASS"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Exception, match="cleanup_evidence_project_decommission"):
        closeout.check_closeout(tmp_path)
