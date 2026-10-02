#!/usr/bin/env python3
"""Build a Git-safe Supabase staging Auth-settings snapshot from protected account evidence.

The operator captures the selected project's current Auth configuration from
Supabase Management API GET /v1/projects/{ref}/config/auth and keeps that raw
response plus the raw project ref outside Git. This tool verifies the project
binding, extracts only reviewed non-secret operational fields, and emits the
canonical safe snapshot used by T17.

It performs no network request and accepts no Supabase access token or API key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from princess_app.config_supabase import (  # noqa: E402
    ENVIRONMENT,
    PROJECT_ALIAS,
    PROJECT_REF_SHA256,
    PROVIDER,
    PROVIDER_MODE,
)

SNAPSHOT_VERSION = "supabase-auth-settings/2"
SOURCE_KIND = "SUPABASE_MANAGEMENT_API"
SOURCE_ACTION = "GET /v1/projects/{ref}/config/auth"
OUTPUT_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
MAX_AUTH_CONFIG_BYTES = 1024 * 1024
MAX_PROJECT_REF_BYTES = 1024
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

RATE_LIMIT_FIELDS = (
    "rate_limit_anonymous_users",
    "rate_limit_email_sent",
    "rate_limit_sms_sent",
    "rate_limit_verify",
    "rate_limit_token_refresh",
    "rate_limit_otp",
    "rate_limit_web3",
)
SECURITY_FIELDS = (
    "security_sb_forwarded_for_enabled",
)
SAFE_PROVIDER_FIELDS = RATE_LIMIT_FIELDS + SECURITY_FIELDS


class AuthSettingsError(ValueError):
    """Static, non-sensitive failure code for the evidence builder."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _protected_input(path: Path, name: str) -> Path:
    if not path.is_absolute():
        raise AuthSettingsError(f"{name}_path_must_be_absolute")
    resolved = path.resolve()
    if _inside_repo(resolved):
        raise AuthSettingsError(f"{name}_inside_repository")
    if not resolved.is_file():
        raise AuthSettingsError(f"{name}_unreadable")
    return resolved


def _canonical_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != OUTPUT_PATH.resolve():
        raise AuthSettingsError("output_path_not_canonical")
    return resolved


def _read_bytes(path: Path, *, name: str, max_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise AuthSettingsError(f"{name}_size")
        data = path.read_bytes()
    except OSError:
        raise AuthSettingsError(f"{name}_unreadable") from None
    if not data or len(data) > max_bytes:
        raise AuthSettingsError(f"{name}_size")
    return data


def _read_project_ref(path: Path) -> str:
    raw = _read_bytes(path, name="project_ref", max_bytes=MAX_PROJECT_REF_BYTES)
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise AuthSettingsError("project_ref_unreadable") from None
    if not value or any(ch.isspace() for ch in value) or "\x00" in value:
        raise AuthSettingsError("project_ref_unreadable")
    if _sha256_text(value) != PROJECT_REF_SHA256:
        raise AuthSettingsError("project_ref_mismatch")
    return value


def _load_auth_config(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(path, name="auth_config", max_bytes=MAX_AUTH_CONFIG_BYTES)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise AuthSettingsError("auth_config_unreadable") from None
    if not isinstance(value, dict):
        raise AuthSettingsError("auth_config_unreadable")
    return value, raw


def _strict_nonnegative_int(raw: Mapping[str, Any], field: str) -> int:
    value = raw.get(field)
    if type(value) is not int or value < 0 or value > 2_147_483_647:
        raise AuthSettingsError(f"auth_config_{field}")
    return value


def _strict_bool(raw: Mapping[str, Any], field: str) -> bool:
    value = raw.get(field)
    if type(value) is not bool:
        raise AuthSettingsError(f"auth_config_{field}")
    return value


def build_snapshot(
    *,
    project_ref: str,
    auth_config: Mapping[str, Any],
    source_response_bytes: bytes,
    captured_date: str,
    protected_evidence_ref: str,
) -> dict[str, Any]:
    if not isinstance(project_ref, str) or not project_ref:
        raise AuthSettingsError("project_ref_unreadable")
    if _sha256_text(project_ref) != PROJECT_REF_SHA256:
        raise AuthSettingsError("project_ref_mismatch")
    if not isinstance(auth_config, Mapping):
        raise AuthSettingsError("auth_config_unreadable")
    if not isinstance(captured_date, str) or not DATE_RE.fullmatch(captured_date):
        raise AuthSettingsError("captured_date_invalid")
    try:
        date.fromisoformat(captured_date)
    except ValueError:
        raise AuthSettingsError("captured_date_invalid") from None

    if not isinstance(source_response_bytes, bytes) or not source_response_bytes:
        raise AuthSettingsError("auth_config_source_response")
    if len(source_response_bytes) > MAX_AUTH_CONFIG_BYTES:
        raise AuthSettingsError("auth_config_source_response")
    try:
        source_value = json.loads(source_response_bytes)
    except (UnicodeDecodeError, ValueError):
        raise AuthSettingsError("auth_config_source_response") from None
    if not isinstance(source_value, dict) or source_value != dict(auth_config):
        raise AuthSettingsError("auth_config_source_mismatch")
    if not isinstance(protected_evidence_ref, str) or not REF_RE.fullmatch(protected_evidence_ref):
        raise AuthSettingsError("auth_config_protected_evidence_ref")

    source_response_sha256 = _sha256_bytes(source_response_bytes)

    provider_projection: dict[str, Any] = {}
    for field in RATE_LIMIT_FIELDS:
        provider_projection[field] = _strict_nonnegative_int(auth_config, field)
    for field in SECURITY_FIELDS:
        provider_projection[field] = _strict_bool(auth_config, field)

    projection_hash = _sha256_bytes(_canonical_bytes(provider_projection))
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "captured_date": captured_date,
        "source_kind": SOURCE_KIND,
        "source_action": SOURCE_ACTION,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "source_response_sha256": source_response_sha256,
        "protected_evidence_ref": protected_evidence_ref,
        "safe_projection_sha256": projection_hash,
        **provider_projection,
        "contains_secrets": False,
        "application_login_activation": False,
        "production_activation": False,
    }
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    expected_keys = {
        "snapshot_version",
        "provider",
        "project_alias",
        "environment",
        "provider_mode",
        "captured_date",
        "source_kind",
        "source_action",
        "project_ref_sha256",
        "source_response_sha256",
        "protected_evidence_ref",
        "safe_projection_sha256",
        *SAFE_PROVIDER_FIELDS,
        "contains_secrets",
        "application_login_activation",
        "production_activation",
    }
    if not isinstance(snapshot, Mapping) or set(snapshot) != expected_keys:
        raise AuthSettingsError("auth_settings_snapshot_shape")

    expected = {
        "snapshot_version": SNAPSHOT_VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "source_kind": SOURCE_KIND,
        "source_action": SOURCE_ACTION,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "contains_secrets": False,
        "application_login_activation": False,
        "production_activation": False,
    }
    for field, value in expected.items():
        if snapshot.get(field) != value:
            raise AuthSettingsError(f"auth_settings_snapshot_{field}")

    captured = snapshot.get("captured_date")
    if not isinstance(captured, str) or not DATE_RE.fullmatch(captured):
        raise AuthSettingsError("auth_settings_snapshot_captured_date")
    try:
        date.fromisoformat(captured)
    except ValueError:
        raise AuthSettingsError("auth_settings_snapshot_captured_date") from None

    source_response_sha256 = snapshot.get("source_response_sha256")
    if not isinstance(source_response_sha256, str) or not HEX64_RE.fullmatch(source_response_sha256):
        raise AuthSettingsError("auth_settings_snapshot_source_response_sha256")
    protected_evidence_ref = snapshot.get("protected_evidence_ref")
    if not isinstance(protected_evidence_ref, str) or not REF_RE.fullmatch(protected_evidence_ref):
        raise AuthSettingsError("auth_settings_snapshot_protected_evidence_ref")

    provider_projection: dict[str, Any] = {}
    for field in RATE_LIMIT_FIELDS:
        provider_projection[field] = _strict_nonnegative_int(snapshot, field)
    for field in SECURITY_FIELDS:
        provider_projection[field] = _strict_bool(snapshot, field)

    expected_hash = _sha256_bytes(_canonical_bytes(provider_projection))
    if snapshot.get("safe_projection_sha256") != expected_hash:
        raise AuthSettingsError("auth_settings_snapshot_projection_hash")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref-file", type=Path, required=True)
    parser.add_argument("--auth-config-file", type=Path, required=True)
    parser.add_argument("--captured-date", required=True)
    parser.add_argument("--protected-evidence-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        project_ref_path = _protected_input(args.project_ref_file, "project_ref")
        auth_config_path = _protected_input(args.auth_config_file, "auth_config")
        output_path = _canonical_output(args.output)
        project_ref = _read_project_ref(project_ref_path)
        auth_config, auth_config_bytes = _load_auth_config(auth_config_path)
        snapshot = build_snapshot(
            project_ref=project_ref,
            auth_config=auth_config,
            source_response_bytes=auth_config_bytes,
            captured_date=args.captured_date,
            protected_evidence_ref=args.protected_evidence_ref,
        )
        output_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except AuthSettingsError as exc:
        print(f"FAIL: {exc}")
        return 1
    except OSError:
        print("FAIL: auth_settings_output_write_failed")
        return 1
    except Exception:
        # Do not forward provider payloads, filesystem details or access-token
        # related text from unexpected dependencies.
        print("FAIL: auth_settings_unexpected_failure")
        return 1

    print(f"PASS {SNAPSHOT_VERSION} -> {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
