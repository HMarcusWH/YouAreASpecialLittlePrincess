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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for path in (SRC, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from princess_app.config_supabase import PROJECT_REF_SHA256  # noqa: E402
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

_REQUIRED_CONFORMANCE_LINES = (
    "result:                                PASS",
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
)


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


def _validate_conformance(path: Path) -> None:
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
    for line in _REQUIRED_CONFORMANCE_LINES:
        if line not in text:
            raise CloseoutError("runtime_conformance_incomplete")

    match = re.search(r"^project_ref_sha256:\s+([0-9a-f]{64})$", text, re.MULTILINE)
    if match is None or match.group(1) != PROJECT_REF_SHA256:
        raise CloseoutError("runtime_conformance_project_binding")


def _validate_owner_scope(path: Path) -> None:
    if not path.is_file():
        raise CloseoutError("account_evidence_missing")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise CloseoutError("account_evidence_invalid") from None

    # Closeout of staging evidence must not rewrite the 2026-10-01 narrow
    # owner decision into application-login or production approval.
    if "application_login:      NOT APPROVED BY THIS DECISION" not in text:
        raise CloseoutError("application_login_owner_gate_widened")
    if "production_activation:  false" not in text:
        raise CloseoutError("production_owner_gate_widened")
    if "global_gate_closure:    false" not in text:
        raise CloseoutError("global_gate_widened")


def check_closeout(root: Path = ROOT) -> None:
    global CONFORMANCE_PATH, AUTH_SNAPSHOT_PATH, CLEANUP_PATH, ACCOUNT_EVIDENCE_PATH

    conformance = root / "docs" / "ci" / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
    auth_snapshot_path = root / "docs" / "ci" / "T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json"
    cleanup_path = root / "docs" / "ci" / "T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json"
    account_path = root / "docs" / "ci" / "T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md"

    _validate_conformance(conformance)

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
