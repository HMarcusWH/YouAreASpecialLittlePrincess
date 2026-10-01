#!/usr/bin/env python3
"""Build a Git-safe Supabase staging runtime binding from protected v4 evidence.

The input qualification receipt remains protected and is never copied into the
output. The output contains only safe profile facts and hashes and may be
stored in protected deployment configuration as PRINCESS_IDENTITY_BINDING.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
    BINDING_VERSION,
    ENVIRONMENT,
    PROJECT_ALIAS,
    PROJECT_BINDING,
    PROJECT_REF_SHA256,
    PROVIDER,
    PROVIDER_MODE,
    QUALIFICATION_RECEIPT_SHA256,
    QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
    SOURCE_REVISION,
)
from qualify_supabase_identity import QualificationError, validate_receipt  # noqa: E402


class BindingError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_binding(receipt_bytes: bytes, account_snapshot: dict[str, Any]) -> dict[str, Any]:
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeDecodeError, ValueError):
        raise BindingError("receipt_unreadable") from None
    if not isinstance(receipt, dict):
        raise BindingError("receipt_unreadable")
    try:
        validate_receipt(receipt)
    except QualificationError as exc:
        raise BindingError(f"receipt_invalid:{exc}") from None

    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_sha != QUALIFICATION_RECEIPT_SHA256:
        raise BindingError("receipt_sha256_mismatch")
    if (
        receipt.get("project_alias") != PROJECT_ALIAS
        or receipt.get("evidence_kind") != "MANAGED_PROJECT"
        or receipt.get("project_binding") != PROJECT_BINDING
        or receipt.get("environment") != ENVIRONMENT
        or receipt.get("provider_mode") != PROVIDER_MODE
        or receipt.get("environment_manifest_sha256") != QUALIFIED_ENVIRONMENT_MANIFEST_SHA256
        or receipt.get("source_revision") != SOURCE_REVISION
        or receipt.get("stock_claims_profile") is not True
        or receipt.get("result") != "PASS"
    ):
        raise BindingError("receipt_scope_mismatch")

    if _canonical_hash(account_snapshot) != ACCOUNT_SNAPSHOT_SHA256:
        raise BindingError("account_snapshot_sha256_mismatch")
    if (
        account_snapshot.get("project_alias") != PROJECT_ALIAS
        or account_snapshot.get("project_ref_sha256") != PROJECT_REF_SHA256
        or account_snapshot.get("contains_secrets") is not False
        or account_snapshot.get("production_activation") is not False
    ):
        raise BindingError("account_snapshot_scope_mismatch")

    issuer_sha256 = receipt.get("issuer_sha256")
    audience = receipt.get("audience")
    role = receipt.get("allowed_role")
    if not isinstance(issuer_sha256, str) or len(issuer_sha256) != 64:
        raise BindingError("receipt_issuer_hash_missing")
    if not isinstance(audience, str) or not audience:
        raise BindingError("receipt_audience_missing")
    if not isinstance(role, str) or not role:
        raise BindingError("receipt_role_missing")

    return {
        "version": BINDING_VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "project_binding": PROJECT_BINDING,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "qualification_receipt_sha256": receipt_sha,
        "qualified_environment_manifest_sha256": receipt["environment_manifest_sha256"],
        "account_snapshot_sha256": ACCOUNT_SNAPSHOT_SHA256,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "source_revision": receipt["source_revision"],
        "issuer_sha256": issuer_sha256,
        "audience": audience,
        "allowed_role": role,
        "stock_claims_profile": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--account-snapshot",
        type=Path,
        default=ROOT / "docs" / "ci" / "T17_SUPABASE_STAGING_ACCOUNT_SNAPSHOT.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        receipt_bytes = args.receipt.read_bytes()
        snapshot = json.loads(args.account_snapshot.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            raise BindingError("account_snapshot_unreadable")
        binding = build_binding(receipt_bytes, snapshot)
        args.output.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, BindingError) as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"PASS {BINDING_VERSION} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
