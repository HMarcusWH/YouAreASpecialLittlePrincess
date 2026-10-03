#!/usr/bin/env python3
"""Fail closed unless all three Supabase staging Auth evidence gates are complete.

This checker is intentionally *not* a substitute for running the protected
operator procedures. It validates only Git-safe closeout artifacts after those
procedures have completed.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for path in (SRC, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from princess_app.config_supabase import (  # noqa: E402
    ACCOUNT_SNAPSHOT_SHA256,
    PROJECT_REF_SHA256,
    QUALIFICATION_RECEIPT_SHA256,
    QUALIFIED_AUDIENCE_SHA256,
    QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
    QUALIFIED_ISSUER_SHA256,
    QUALIFIED_ROLE_SHA256,
    SOURCE_REVISION,
)
from princess_app.ports import identity as identity_port  # noqa: E402
from build_supabase_auth_settings_snapshot import (  # noqa: E402
    validate_snapshot as validate_auth_snapshot,
)
from build_supabase_staging_cleanup_evidence import (  # noqa: E402
    validate_cleanup_evidence,
)

CONFORMANCE_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
AUTH_SNAPSHOT_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
CLEANUP_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
ACCOUNT_EVIDENCE_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md"

FROZEN_CONFORMANCE_COMMIT = "c653a7d0cc29e0398a0cfb9e5c8113b9b2acd6b3"
CONFORMANCE_RECEIPT_VERSION = "supabase-staging-runtime-conformance/1"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_CONFORMANCE_KEYS = frozenset({
    "provider",
    "project_alias",
    "receipt_version",
    "environment",
    "provider_mode",
    "capability",
    "checked_date",
    "princess_commit",
    "receipt_sha256",
    "protected_evidence_ref",
    "qualification_receipt_sha256",
    "runtime_binding_sha256",
    "account_snapshot_sha256",
    "qualified_environment_manifest_sha256",
    "project_ref_sha256",
    "issuer_sha256",
    "audience_sha256",
    "role_sha256",
    "source_revision",
    "jwks_fetch",
    "credential_verified",
    "identity_service_authenticated",
    "stable_principal_mapping",
    "principal_kind",
    "auth_time_present",
    "session_id_present",
    "credential_unexpired",
    "provider_cleanup_required",
    "provider_cleanup_performed_by_tool",
    "application_login",
    "production_activation",
    "global_gate_closure",
    "result",
})


class CloseoutError(ValueError):
    """Static closeout failure code."""


def _load_json(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file():
        raise CloseoutError(f"{code}_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CloseoutError(f"{code}_invalid") from None
    if not isinstance(value, dict):
        raise CloseoutError(f"{code}_invalid")
    return value


def _parse_conformance_record(text: str) -> dict[str, str]:
    match = re.search(r"## Evidence record\s+```text\n(.*?)\n```", text, re.DOTALL)
    if match is None:
        raise CloseoutError("runtime_conformance_record_missing")

    record: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        item = re.fullmatch(r"([a-z0-9_]+):\s+(.+)", line)
        if item is None:
            raise CloseoutError("runtime_conformance_record_shape")
        key, value = item.group(1), item.group(2).strip()
        if key in record:
            raise CloseoutError("runtime_conformance_duplicate_key")
        record[key] = value

    if set(record) != set(_CONFORMANCE_KEYS):
        raise CloseoutError("runtime_conformance_record_shape")
    return record


def _validate_conformance(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise CloseoutError("runtime_conformance_missing")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise CloseoutError("runtime_conformance_invalid") from None

    if "**Status: PASS —" not in text:
        raise CloseoutError("runtime_conformance_not_pass")
    if "PENDING REAL STAGING RUN" in text:
        raise CloseoutError("runtime_conformance_still_pending")

    record = _parse_conformance_record(text)

    expected = {
        "provider": "supabase-auth",
        "project_alias": "princess-staging",
        "receipt_version": CONFORMANCE_RECEIPT_VERSION,
        "environment": "staging",
        "provider_mode": "sandbox",
        "capability": identity_port.VERIFY_CREDENTIAL,
        "princess_commit": FROZEN_CONFORMANCE_COMMIT,
        "qualification_receipt_sha256": QUALIFICATION_RECEIPT_SHA256,
        "account_snapshot_sha256": ACCOUNT_SNAPSHOT_SHA256,
        "qualified_environment_manifest_sha256": QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "issuer_sha256": QUALIFIED_ISSUER_SHA256,
        "audience_sha256": QUALIFIED_AUDIENCE_SHA256,
        "role_sha256": QUALIFIED_ROLE_SHA256,
        "source_revision": SOURCE_REVISION,
        "jwks_fetch": "PASS",
        "credential_verified": "PASS",
        "identity_service_authenticated": "PASS",
        "stable_principal_mapping": "PASS",
        "principal_kind": "ACCOUNT",
        "auth_time_present": "PASS",
        "session_id_present": "PASS",
        "credential_unexpired": "PASS",
        "provider_cleanup_required": "true",
        "provider_cleanup_performed_by_tool": "false",
        "application_login": "false",
        "production_activation": "false",
        "global_gate_closure": "false",
        "result": "PASS",
    }
    for key, value in expected.items():
        if record.get(key) != value:
            if key == "princess_commit":
                raise CloseoutError("runtime_conformance_commit_binding")
            raise CloseoutError(f"runtime_conformance_{key}")

    checked_date = record.get("checked_date", "")
    if not DATE_RE.fullmatch(checked_date):
        raise CloseoutError("runtime_conformance_checked_date")
    try:
        date.fromisoformat(checked_date)
    except ValueError:
        raise CloseoutError("runtime_conformance_checked_date") from None

    for key in ("receipt_sha256", "runtime_binding_sha256"):
        value = record.get(key, "")
        if not HEX64_RE.fullmatch(value):
            raise CloseoutError(f"runtime_conformance_{key}")

    evidence_ref = record.get("protected_evidence_ref", "")
    if not EVIDENCE_REF_RE.fullmatch(evidence_ref):
        raise CloseoutError("runtime_conformance_protected_evidence_ref")

    return record


def _validate_owner_scope(path: Path) -> None:
    if not path.is_file():
        raise CloseoutError("account_evidence_missing")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise CloseoutError("account_evidence_invalid") from None

    if "application_login:      NOT APPROVED BY THIS DECISION" not in text:
        raise CloseoutError("application_login_owner_gate_widened")
    if "production_activation:  false" not in text:
        raise CloseoutError("production_owner_gate_widened")
    if "global_gate_closure:    false" not in text:
        raise CloseoutError("global_gate_widened")


def check_closeout(root: Path = ROOT) -> None:
    conformance = root / "docs" / "ci" / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
    auth_snapshot_path = root / "docs" / "ci" / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
    cleanup_path = root / "docs" / "ci" / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    account_path = root / "docs" / "ci" / "T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md"

    conformance_record = _validate_conformance(conformance)

    auth_snapshot = _load_json(auth_snapshot_path, "auth_settings_snapshot")
    validate_auth_snapshot(auth_snapshot)
    if auth_snapshot.get("project_ref_sha256") != PROJECT_REF_SHA256:
        raise CloseoutError("auth_settings_project_binding")
    if auth_snapshot.get("application_login_activation") is not False:
        raise CloseoutError("auth_settings_login_activation")
    if auth_snapshot.get("production_activation") is not False:
        raise CloseoutError("auth_settings_production_activation")

    cleanup = _load_json(cleanup_path, "cleanup_evidence")
    validate_cleanup_evidence(cleanup)
    if cleanup.get("project_ref_sha256") != PROJECT_REF_SHA256:
        raise CloseoutError("cleanup_project_binding")
    if cleanup.get("conformance_receipt_sha256") != conformance_record["receipt_sha256"]:
        raise CloseoutError("cleanup_conformance_receipt_mismatch")

    conformance_date = date.fromisoformat(conformance_record["checked_date"])
    auth_date = date.fromisoformat(auth_snapshot["captured_date"])
    cleanup_date = date.fromisoformat(cleanup["checked_date"])
    if auth_date < conformance_date:
        raise CloseoutError("auth_settings_before_conformance")
    if cleanup_date < conformance_date:
        raise CloseoutError("cleanup_before_conformance")
    if cleanup_date < auth_date:
        raise CloseoutError("cleanup_before_auth_settings")

    _validate_owner_scope(account_path)


def main() -> int:
    try:
        check_closeout()
    except (CloseoutError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception:
        print("FAIL: closeout_unexpected_failure")
        return 1

    print("PASS: Supabase staging Auth evidence gates are complete without widening login/production authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
