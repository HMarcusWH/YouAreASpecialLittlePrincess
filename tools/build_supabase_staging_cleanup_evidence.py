#!/usr/bin/env python3
"""Build Git-safe evidence for disposable Supabase staging identity cleanup.

The operator performs provider cleanup through owner-authorized Supabase
controls. This tool does not revoke sessions or delete users. It verifies the
selected staging project binding and converts a protected operator attestation
into a strict non-identifying JSON artifact.
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

VERSION = "supabase-staging-cleanup/2"
OUTPUT_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
MAX_INPUT_BYTES = 64 * 1024
MAX_PROJECT_REF_BYTES = 1024
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_ALLOWED_INPUT_KEYS = frozenset({
    "checked_date",
    "operator_role",
    "affected_test_population_count",
    "all_sessions_for_test_user_revoked",
    "provider_refresh_state_revoked",
    "disposable_auth_user_deleted",
    "persistent_princess_binding_created_by_witness",
    "application_login_active",
    "jwt_age_out_required",
    "project_decommission",
    "production_activation",
    "protected_evidence_ref",
    "conformance_receipt_sha256",
})


class CleanupEvidenceError(ValueError):
    """Static, non-sensitive cleanup-evidence failure code."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _protected_input(path: Path, name: str) -> Path:
    if not path.is_absolute():
        raise CleanupEvidenceError(f"{name}_path_must_be_absolute")
    resolved = path.resolve()
    if _inside_repo(resolved):
        raise CleanupEvidenceError(f"{name}_inside_repository")
    if not resolved.is_file():
        raise CleanupEvidenceError(f"{name}_unreadable")
    return resolved


def _canonical_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != OUTPUT_PATH.resolve():
        raise CleanupEvidenceError("output_path_not_canonical")
    return resolved


def _read_text(path: Path, *, name: str, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise CleanupEvidenceError(f"{name}_size")
        raw = path.read_bytes()
    except OSError:
        raise CleanupEvidenceError(f"{name}_unreadable") from None
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise CleanupEvidenceError(f"{name}_unreadable") from None
    if not value or "\x00" in value:
        raise CleanupEvidenceError(f"{name}_unreadable")
    return value


def _load_json(path: Path, name: str) -> dict[str, Any]:
    raw = _read_text(path, name=name, max_bytes=MAX_INPUT_BYTES)
    try:
        value = json.loads(raw)
    except ValueError:
        raise CleanupEvidenceError(f"{name}_unreadable") from None
    if not isinstance(value, dict):
        raise CleanupEvidenceError(f"{name}_unreadable")
    return value


def _validate_date(value: object) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise CleanupEvidenceError("cleanup_checked_date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise CleanupEvidenceError("cleanup_checked_date") from None
    return value


def build_cleanup_evidence(*, project_ref: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    if _sha256_text(project_ref) != PROJECT_REF_SHA256:
        raise CleanupEvidenceError("project_ref_mismatch")
    if not isinstance(raw, Mapping) or set(raw) != set(_ALLOWED_INPUT_KEYS):
        raise CleanupEvidenceError("cleanup_input_shape")

    checked_date = _validate_date(raw.get("checked_date"))
    if raw.get("operator_role") != "product/technical owner":
        raise CleanupEvidenceError("cleanup_operator_role")
    count = raw.get("affected_test_population_count")
    if type(count) is not int or not (1 <= count <= 1000):
        raise CleanupEvidenceError("cleanup_population_count")

    for key in (
        "all_sessions_for_test_user_revoked",
        "provider_refresh_state_revoked",
        "disposable_auth_user_deleted",
        "jwt_age_out_required",
    ):
        if raw.get(key) is not True:
            raise CleanupEvidenceError(f"cleanup_{key}")

    for key in (
        "persistent_princess_binding_created_by_witness",
        "application_login_active",
        "production_activation",
    ):
        if raw.get(key) is not False:
            raise CleanupEvidenceError(f"cleanup_{key}")

    if raw.get("project_decommission") != "NOT_APPLICABLE":
        raise CleanupEvidenceError("cleanup_project_decommission")

    evidence_ref = raw.get("protected_evidence_ref")
    if not isinstance(evidence_ref, str) or not REF_RE.fullmatch(evidence_ref):
        raise CleanupEvidenceError("cleanup_protected_evidence_ref")
    conformance_receipt_sha256 = raw.get("conformance_receipt_sha256")
    if not isinstance(conformance_receipt_sha256, str) or not HEX64_RE.fullmatch(conformance_receipt_sha256):
        raise CleanupEvidenceError("cleanup_conformance_receipt_sha256")

    result = {
        "version": VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "checked_date": checked_date,
        "operator_role": "product/technical owner",
        "affected_test_population_count": count,
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
        "protected_evidence_ref": evidence_ref,
        "conformance_receipt_sha256": conformance_receipt_sha256,
        "result": "PASS",
    }
    validate_cleanup_evidence(result)
    return result


def validate_cleanup_evidence(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "version",
        "provider",
        "project_alias",
        "environment",
        "provider_mode",
        "project_ref_sha256",
        "checked_date",
        "operator_role",
        "affected_test_population_count",
        "all_sessions_for_test_user_revoked",
        "provider_refresh_state_revoked",
        "disposable_auth_user_deleted",
        "persistent_princess_binding_created_by_witness",
        "application_login_active",
        "jwt_age_out_required",
        "project_decommission",
        "production_activation",
        "contains_provider_user_ids",
        "contains_session_ids",
        "contains_secrets",
        "protected_evidence_ref",
        "conformance_receipt_sha256",
        "result",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise CleanupEvidenceError("cleanup_evidence_shape")
    fixed = {
        "version": VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "operator_role": "product/technical owner",
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
        "result": "PASS",
    }
    for key, expected in fixed.items():
        if value.get(key) != expected:
            raise CleanupEvidenceError(f"cleanup_evidence_{key}")
    _validate_date(value.get("checked_date"))
    count = value.get("affected_test_population_count")
    if type(count) is not int or not (1 <= count <= 1000):
        raise CleanupEvidenceError("cleanup_evidence_population_count")
    ref = value.get("protected_evidence_ref")
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise CleanupEvidenceError("cleanup_evidence_protected_evidence_ref")
    conformance_receipt_sha256 = value.get("conformance_receipt_sha256")
    if not isinstance(conformance_receipt_sha256, str) or not HEX64_RE.fullmatch(conformance_receipt_sha256):
        raise CleanupEvidenceError("cleanup_evidence_conformance_receipt_sha256")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref-file", type=Path, required=True)
    parser.add_argument("--cleanup-input-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        project_path = _protected_input(args.project_ref_file, "project_ref")
        cleanup_path = _protected_input(args.cleanup_input_file, "cleanup_input")
        output_path = _canonical_output(args.output)
        project_ref = _read_text(project_path, name="project_ref", max_bytes=MAX_PROJECT_REF_BYTES)
        raw = _load_json(cleanup_path, "cleanup_input")
        result = build_cleanup_evidence(project_ref=project_ref, raw=raw)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except CleanupEvidenceError as exc:
        print(f"FAIL: {exc}")
        return 1
    except OSError:
        print("FAIL: cleanup_output_write_failed")
        return 1
    except Exception:
        print("FAIL: cleanup_unexpected_failure")
        return 1

    print(f"PASS {VERSION} -> {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
