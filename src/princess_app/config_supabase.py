"""Git-safe validation of the qualified Supabase staging runtime profile.

The invasive v4 qualification receipt stays outside Git. Runtime composition
receives the raw issuer through protected process configuration plus a compact
binding generated from that protected receipt. This module validates only
hashes and safe profile facts; it performs no provider/network I/O.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .ports.base import InvalidInput

BINDING_VERSION = "supabase-staging-runtime-binding/1"
PROVIDER = "supabase-auth"
PROJECT_ALIAS = "princess-staging"
PROJECT_BINDING = "INTENDED_RUNTIME_PROFILE"
ENVIRONMENT = "staging"
PROVIDER_MODE = "sandbox"
SOURCE_REVISION = "ce9a8eee0cc042be8c7a42981a7ddae631e41d91"

# Git-safe evidence already recorded by T17.
QUALIFICATION_RECEIPT_SHA256 = "c9e23770d23b5b066cf32596d26bde5564bdd440d460074deb61d0cab1be85fe"
# The 2026-10-01 v4 receipt was generated from a clean Windows checkout. Git's
# CRLF working-tree transform changed only the raw bytes hashed by that receipt.
QUALIFICATION_ENVIRONMENT_MANIFEST_SHA256 = "4441a12bdb89688634e30a00785daae6e0e44dadfab6ae219affc4ef9067e7b7"
# Runtime composition uses the stable LF-normalized/Git manifest bytes.
QUALIFIED_ENVIRONMENT_MANIFEST_SHA256 = "bc9ef87478461e1a13098e116d34f46c7b84addefbdb65004a2e9a71aa642f1c"
ACCOUNT_SNAPSHOT_SHA256 = "905a943563fcce0c921b07f3c661032f2e732dbd968f8dcc6b6b31bf4e2c96a1"
PROJECT_REF_SHA256 = "730f049be2bb48fbca59f87518cece081ca02f313c465fd55498e84a9d590a99"
QUALIFIED_ISSUER_SHA256 = "0c619c9e3850c9bca069636be52c55b7e85165ae295fa682566797073e551cf0"
QUALIFIED_AUDIENCE_SHA256 = "40c041842ccbe556bd30396b6ba8070418afa56119feebd79d2b74a15d176fc8"
QUALIFIED_ROLE_SHA256 = "40c041842ccbe556bd30396b6ba8070418afa56119feebd79d2b74a15d176fc8"
# Canonical SHA-256 of the exact qualified Git-safe runtime-binding payload.
# This is redundant with the pinned constituent anchors by design: the closeout
# chain can detect a changed aggregate binding even when every field is present.
QUALIFIED_RUNTIME_BINDING_SHA256 = "b4d4e547c43f733657dc35f9077b2c883e53c022e9892637fa0a6a570e291c3b"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KEYS = frozenset({
    "version",
    "provider",
    "project_alias",
    "project_binding",
    "environment",
    "provider_mode",
    "qualification_receipt_sha256",
    "qualified_environment_manifest_sha256",
    "account_snapshot_sha256",
    "project_ref_sha256",
    "source_revision",
    "issuer_sha256",
    "audience",
    "allowed_role",
    "stock_claims_profile",
})


@dataclass(frozen=True)
class SupabaseStagingRuntimeBinding:
    issuer_sha256: str
    audience: str
    allowed_role: str


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise InvalidInput("identity_runtime_binding_duplicate_key", detail=key[:64])
        out[key] = value
    return out


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_manifest_sha256(raw: bytes) -> str:
    """Hash manifest bytes after canonicalizing line endings to LF."""
    normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def _project_ref_from_issuer(issuer: str) -> str:
    parts = urlsplit(issuer)
    host = parts.hostname or ""
    suffix = ".supabase.co"
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not host.endswith(suffix)
        or parts.path.rstrip("/") != "/auth/v1"
    ):
        raise InvalidInput("identity_runtime_issuer_not_qualified")
    project_ref = host[: -len(suffix)]
    if not project_ref or "." in project_ref:
        raise InvalidInput("identity_runtime_issuer_not_qualified")
    return project_ref


def parse_supabase_staging_runtime_binding(
    raw: str,
    *,
    issuer: str,
    audience: str,
    current_manifest_sha256: str,
) -> SupabaseStagingRuntimeBinding:
    """Validate a receipt-derived binding against the protected runtime values."""
    try:
        data = json.loads(raw, object_pairs_hook=_pairs)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise InvalidInput("identity_runtime_binding_invalid_json") from None
    if not isinstance(data, dict) or set(data) != set(_ALLOWED_KEYS):
        raise InvalidInput("identity_runtime_binding_shape")

    expected = {
        "version": BINDING_VERSION,
        "provider": PROVIDER,
        "project_alias": PROJECT_ALIAS,
        "project_binding": PROJECT_BINDING,
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "qualification_receipt_sha256": QUALIFICATION_RECEIPT_SHA256,
        "qualified_environment_manifest_sha256": QUALIFIED_ENVIRONMENT_MANIFEST_SHA256,
        "account_snapshot_sha256": ACCOUNT_SNAPSHOT_SHA256,
        "project_ref_sha256": PROJECT_REF_SHA256,
        "source_revision": SOURCE_REVISION,
        "issuer_sha256": QUALIFIED_ISSUER_SHA256,
        "stock_claims_profile": True,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            raise InvalidInput("identity_runtime_binding_mismatch", detail=key)

    if current_manifest_sha256 != QUALIFIED_ENVIRONMENT_MANIFEST_SHA256:
        raise InvalidInput("identity_runtime_manifest_changed")

    issuer_sha256 = data.get("issuer_sha256")
    if not isinstance(issuer_sha256, str) or not _HEX64.fullmatch(issuer_sha256):
        raise InvalidInput("identity_runtime_binding_issuer_hash")
    if _sha256_text(issuer) != issuer_sha256:
        raise InvalidInput("identity_runtime_issuer_mismatch")

    project_ref = _project_ref_from_issuer(issuer)
    if _sha256_text(project_ref) != PROJECT_REF_SHA256:
        raise InvalidInput("identity_runtime_project_mismatch")

    bound_audience = data.get("audience")
    role = data.get("allowed_role")
    if not isinstance(bound_audience, str) or not bound_audience or len(bound_audience) > 512:
        raise InvalidInput("identity_runtime_binding_audience")
    if _sha256_text(bound_audience) != QUALIFIED_AUDIENCE_SHA256:
        raise InvalidInput("identity_runtime_binding_mismatch", detail="audience")
    if audience != bound_audience:
        raise InvalidInput("identity_runtime_audience_mismatch")
    if not isinstance(role, str) or not role or len(role) > 128:
        raise InvalidInput("identity_runtime_binding_role")
    if role in {"anon", "service_role", "supabase_admin"}:
        raise InvalidInput("identity_runtime_binding_role")
    if _sha256_text(role) != QUALIFIED_ROLE_SHA256:
        raise InvalidInput("identity_runtime_binding_mismatch", detail="allowed_role")

    return SupabaseStagingRuntimeBinding(
        issuer_sha256=issuer_sha256,
        audience=bound_audience,
        allowed_role=role,
    )
