"""Tests for the Supabase staging Auth closeout checker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import check_supabase_staging_auth_closeout as closeout
from build_supabase_auth_settings_snapshot import SAFE_PROVIDER_FIELDS
from princess_app.config_supabase import PROJECT_REF_SHA256


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_world(root: Path):
    ci = root / "docs" / "ci"
    ci.mkdir(parents=True)

    conformance = "\n".join([
        "# T17 Supabase staging runtime conformance",
        "",
        "**Status: PASS — real witness**",
        "",
        f"project_ref_sha256:                    {PROJECT_REF_SHA256}",
        "jwks_fetch:                            PASS",
        "credential_verified:                   PASS",
        "identity_service_authenticated:        PASS",
        "stable_principal_mapping:              PASS",
        "principal_kind:                        ACCOUNT",
        "auth_time_present:                     PASS",
        "session_id_present:                    PASS",
        "credential_unexpired:                  PASS",
        "provider_cleanup_performed_by_tool:    false",
        "application_login:                     false",
        "production_activation:                 false",
        "global_gate_closure:                   false",
        "result:                                PASS",
        "",
    ])
    (ci / "T17_SUPABASE_RUNTIME_CONFORMANCE.md").write_text(conformance, encoding="utf-8")

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
        "snapshot_version": "supabase-auth-settings/1",
        "provider": "supabase-auth",
        "project_alias": "princess-staging",
        "environment": "staging",
        "provider_mode": "sandbox",
        "captured_date": "2026-10-02",
        "source_kind": "SUPABASE_MANAGEMENT_API",
        "source_action": "GET /v1/projects/{ref}/config/auth",
        "project_ref_sha256": PROJECT_REF_SHA256,
        "safe_projection_sha256": hashlib.sha256(_canonical_bytes(projection)).hexdigest(),
        **projection,
        "contains_secrets": False,
        "application_login_activation": False,
        "production_activation": False,
    }
    assert set(projection) == set(SAFE_PROVIDER_FIELDS)
    (ci / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json").write_text(
        json.dumps(auth), encoding="utf-8"
    )

    cleanup = {
        "version": "supabase-staging-cleanup/1",
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


def test_closeout_requires_all_three_real_evidence_classes(tmp_path):
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
