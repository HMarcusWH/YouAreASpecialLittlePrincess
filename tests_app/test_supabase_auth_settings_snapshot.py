"""Tests for the Git-safe Supabase Auth operational-settings snapshot builder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import build_supabase_auth_settings_snapshot as snapshot

ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _config(**overrides):
    data = {
        "rate_limit_anonymous_users": 30,
        "rate_limit_email_sent": 2,
        "rate_limit_sms_sent": 30,
        "rate_limit_verify": 360,
        "rate_limit_token_refresh": 1800,
        "rate_limit_otp": 30,
        "rate_limit_web3": 30,
        "security_sb_forwarded_for_enabled": False,
        # Deliberately sensitive/unreviewed-looking fields that must never
        # cross the allowlist into Git-safe output.
        "smtp_pass": "super-secret",
        "external_google_secret": "also-secret",
        "site_url": "https://internal.example.invalid",
    }
    data.update(overrides)
    return data


def _bind_project(monkeypatch):
    project_ref = "qualified-staging-ref"
    monkeypatch.setattr(snapshot, "PROJECT_REF_SHA256", _sha(project_ref))
    return project_ref


def _source_bytes(auth_config) -> bytes:
    return (
        json.dumps(auth_config, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _build_snapshot(
    *,
    project_ref: str,
    auth_config,
    captured_date: str,
    protected_evidence_ref: str = "operator-local:princess-staging-auth-config",
):
    return snapshot.build_snapshot(
        project_ref=project_ref,
        auth_config=auth_config,
        source_response_bytes=_source_bytes(auth_config),
        captured_date=captured_date,
        protected_evidence_ref=protected_evidence_ref,
    )


def test_safe_snapshot_extracts_only_allowlisted_account_facts(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )

    assert result["snapshot_version"] == snapshot.SNAPSHOT_VERSION
    assert result["project_ref_sha256"] == _sha(project_ref)
    assert result["rate_limit_token_refresh"] == 1800
    assert result["security_sb_forwarded_for_enabled"] is False
    assert result["contains_secrets"] is False
    assert result["application_login_activation"] is False
    assert result["production_activation"] is False
    assert result["source_response_sha256"] == hashlib.sha256(_source_bytes(_config())).hexdigest()
    assert result["protected_evidence_ref"] == "operator-local:princess-staging-auth-config"
    assert result["evidence_sha256"] == snapshot._evidence_hash(result)

    rendered = json.dumps(result, sort_keys=True)
    assert project_ref not in rendered
    assert "super-secret" not in rendered
    assert "also-secret" not in rendered
    assert "internal.example.invalid" not in rendered
    assert "smtp_pass" not in result
    assert "external_google_secret" not in result
    assert "site_url" not in result


def test_unrelated_provider_fields_do_not_change_safe_projection(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    first = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(extra_provider_setting="one"),
        captured_date="2026-10-02",
    )
    second = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(extra_provider_setting="two", another_secret="hidden"),
        captured_date="2026-10-02",
    )
    assert first["safe_projection_sha256"] == second["safe_projection_sha256"]
    assert first["source_response_sha256"] != second["source_response_sha256"]
    assert first["evidence_sha256"] != second["evidence_sha256"]


def test_reviewed_setting_change_changes_projection_hash(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    first = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(rate_limit_token_refresh=1800),
        captured_date="2026-10-02",
    )
    second = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(rate_limit_token_refresh=1799),
        captured_date="2026-10-02",
    )
    assert first["safe_projection_sha256"] != second["safe_projection_sha256"]
    assert first["evidence_sha256"] != second["evidence_sha256"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rate_limit_token_refresh", None),
        ("rate_limit_token_refresh", True),
        ("rate_limit_token_refresh", "1800"),
        ("rate_limit_token_refresh", -1),
        ("rate_limit_token_refresh", 2_147_483_648),
        ("rate_limit_verify", 1.5),
        ("security_sb_forwarded_for_enabled", 0),
        ("security_sb_forwarded_for_enabled", "false"),
    ],
)
def test_invalid_or_missing_selected_account_values_fail_closed(monkeypatch, field, value):
    project_ref = _bind_project(monkeypatch)
    config = _config()
    if value is None:
        del config[field]
    else:
        config[field] = value
    with pytest.raises(snapshot.AuthSettingsError, match=f"auth_config_{field}"):
        _build_snapshot(
            project_ref=project_ref,
            auth_config=config,
            captured_date="2026-10-02",
        )


def test_generic_defaults_cannot_substitute_for_missing_account_evidence(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    public_default_like_data = {
        "rate_limit_token_refresh": 1800,
        "security_sb_forwarded_for_enabled": False,
    }
    with pytest.raises(snapshot.AuthSettingsError, match="auth_config_rate_limit_anonymous_users"):
        _build_snapshot(
            project_ref=project_ref,
            auth_config=public_default_like_data,
            captured_date="2026-10-02",
        )


def test_source_response_bytes_must_match_projected_config(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    with pytest.raises(snapshot.AuthSettingsError, match="auth_config_source_mismatch"):
        snapshot.build_snapshot(
            project_ref=project_ref,
            auth_config=_config(),
            source_response_bytes=_source_bytes(_config(rate_limit_otp=31)),
            captured_date="2026-10-02",
            protected_evidence_ref="operator-local:auth-config",
        )


def test_protected_evidence_ref_is_required(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    with pytest.raises(snapshot.AuthSettingsError, match="auth_config_protected_evidence_ref"):
        snapshot.build_snapshot(
            project_ref=project_ref,
            auth_config=_config(),
            source_response_bytes=_source_bytes(_config()),
            captured_date="2026-10-02",
            protected_evidence_ref="bad ref with spaces",
        )


def test_wrong_project_binding_fails_before_snapshot(monkeypatch):
    _bind_project(monkeypatch)
    with pytest.raises(snapshot.AuthSettingsError, match="project_ref_mismatch"):
        _build_snapshot(
            project_ref="some-other-project",
            auth_config=_config(),
            captured_date="2026-10-02",
        )


@pytest.mark.parametrize("captured", ["", "2026-13-01", "2026/10/02", "today"])
def test_capture_date_is_explicit_iso_date(monkeypatch, captured):
    project_ref = _bind_project(monkeypatch)
    with pytest.raises(snapshot.AuthSettingsError, match="captured_date_invalid"):
        _build_snapshot(
            project_ref=project_ref,
            auth_config=_config(),
            captured_date=captured,
        )


def test_snapshot_schema_cannot_be_widened_to_activate_login(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )
    result["application_login_activation"] = True
    with pytest.raises(snapshot.AuthSettingsError, match="auth_settings_snapshot_application_login_activation"):
        snapshot.validate_snapshot(result)


def test_snapshot_source_response_hash_shape_detects_tampering(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )
    result["source_response_sha256"] = "not-a-digest"
    with pytest.raises(snapshot.AuthSettingsError, match="auth_settings_snapshot_source_response_sha256"):
        snapshot.validate_snapshot(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_response_sha256", "e" * 64),
        ("captured_date", "2026-10-03"),
        ("protected_evidence_ref", "operator-local:changed-auth-config"),
    ],
)
def test_snapshot_evidence_hash_detects_valid_looking_tampering(monkeypatch, field, value):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )
    result[field] = value
    with pytest.raises(snapshot.AuthSettingsError, match="auth_settings_snapshot_evidence_hash"):
        snapshot.validate_snapshot(result)


def test_snapshot_evidence_hash_shape_is_strict(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )
    result["evidence_sha256"] = "not-a-digest"
    with pytest.raises(snapshot.AuthSettingsError, match="auth_settings_snapshot_evidence_sha256"):
        snapshot.validate_snapshot(result)


def test_snapshot_projection_hash_detects_tampering(monkeypatch):
    project_ref = _bind_project(monkeypatch)
    result = _build_snapshot(
        project_ref=project_ref,
        auth_config=_config(),
        captured_date="2026-10-02",
    )
    result["rate_limit_otp"] += 1
    with pytest.raises(snapshot.AuthSettingsError, match="auth_settings_snapshot_projection_hash"):
        snapshot.validate_snapshot(result)


def test_protected_inputs_must_be_absolute_and_outside_checkout(tmp_path):
    with pytest.raises(snapshot.AuthSettingsError, match="project_ref_path_must_be_absolute"):
        snapshot._protected_input(Path("project-ref.txt"), "project_ref")
    with pytest.raises(snapshot.AuthSettingsError, match="auth_config_inside_repository"):
        snapshot._protected_input(ROOT / "README.md", "auth_config")

    external = tmp_path / "config.json"
    external.write_text("{}", encoding="utf-8")
    assert snapshot._protected_input(external, "auth_config") == external.resolve()


def test_output_is_one_canonical_git_snapshot_path(tmp_path):
    with pytest.raises(snapshot.AuthSettingsError, match="output_path_not_canonical"):
        snapshot._canonical_output(tmp_path / "auth-settings.json")


def test_unexpected_failure_does_not_echo_provider_payload(monkeypatch, tmp_path, capsys):
    project_ref = tmp_path / "project-ref.txt"
    auth_config = tmp_path / "auth.json"
    project_ref.write_text("qualified-staging-ref", encoding="utf-8")
    auth_config.write_text('{"smtp_pass":"super-secret-provider-value"}', encoding="utf-8")
    monkeypatch.setattr(snapshot, "PROJECT_REF_SHA256", _sha("qualified-staging-ref"))

    def explode(_path):
        raise RuntimeError("super-secret-provider-value")

    monkeypatch.setattr(snapshot, "_load_auth_config", explode)
    rc = snapshot.main([
        "--project-ref-file", str(project_ref),
        "--auth-config-file", str(auth_config),
        "--captured-date", "2026-10-02",
        "--protected-evidence-ref", "operator-local:auth-config",
        "--output", str(snapshot.OUTPUT_PATH),
    ])
    rendered = capsys.readouterr().out
    assert rc == 1
    assert rendered.strip() == "FAIL: auth_settings_unexpected_failure"
    assert "super-secret-provider-value" not in rendered
