#!/usr/bin/env python3
"""Offline Supabase Auth account-profile qualification; emits no credential material."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from princess_app.adapters.fakes import SequentialIds  # noqa: E402
from princess_app.adapters.supabase import SupabaseIdentityProvider  # noqa: E402
from princess_app.application.identity import IdentityService, InMemoryIdentityStore  # noqa: E402
from princess_app.ports.base import CallContext, Environment, ProviderMode, Unauthenticated  # noqa: E402

VERSION = "supabase-identity-qualification/1"
SOURCE_REVISION = "ce9a8eee0cc042be8c7a42981a7ddae631e41d91"
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
EVIDENCE_KINDS = ("SYNTHETIC_TEST", "MANAGED_PROJECT")


class QualificationError(ValueError):
    pass


@dataclass
class MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise QualificationError("clock_not_utc")
        self.value = value


def _dt(value: object, name: str) -> datetime:
    if type(value) is not int:
        raise QualificationError(f"{name}_not_integer")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise QualificationError(f"{name}_invalid") from exc


def _peek(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise QualificationError("credential_unreadable") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise QualificationError("credential_unreadable")
    return header, claims


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value or len(value) > 65536:
        raise QualificationError("credential_file_invalid")
    return value


def _load_jwks(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
        raise QualificationError("jwks_invalid")
    return value


def _context(clock: MutableClock) -> CallContext:
    return CallContext("supabase-qualification", Environment.STAGING, clock.now() + timedelta(minutes=1))


def _provider(
    *, issuer: str, audience: str, role: str, jwks: dict[str, Any], clock: MutableClock,
) -> SupabaseIdentityProvider:
    return SupabaseIdentityProvider(
        issuer=issuer,
        audience=audience,
        allowed_roles=frozenset({role}),
        jwks_source=lambda: jwks,
        clock=clock,
        environment=Environment.STAGING,
        mode=ProviderMode.SANDBOX,
        stock_claims_profile=True,
    )


def qualify(
    *,
    project_alias: str,
    evidence_kind: str,
    issuer: str,
    audience: str,
    role: str,
    custom_access_token_hook: str,
    jwks: dict[str, Any],
    initial_token: str,
    refreshed_token: str,
    reauth_token: str,
) -> dict[str, Any]:
    if not ALIAS.fullmatch(project_alias):
        raise QualificationError("project_alias_invalid")
    if evidence_kind not in EVIDENCE_KINDS:
        raise QualificationError("evidence_kind_invalid")
    if custom_access_token_hook != "disabled":
        raise QualificationError("custom_access_token_hook_not_qualified")

    initial_header, initial_claims = _peek(initial_token)
    refresh_header, refresh_claims = _peek(refreshed_token)
    reauth_header, reauth_claims = _peek(reauth_token)
    initial_iat = _dt(initial_claims.get("iat"), "initial_iat")
    refresh_iat = _dt(refresh_claims.get("iat"), "refresh_iat")
    reauth_iat = _dt(reauth_claims.get("iat"), "reauth_iat")

    clock = MutableClock(max(initial_iat, refresh_iat, reauth_iat))
    provider = _provider(issuer=issuer, audience=audience, role=role, jwks=jwks, clock=clock)
    initial = provider.verify_credential(initial_token, _context(clock))
    refreshed = provider.verify_credential(refreshed_token, _context(clock))
    reauth = provider.verify_credential(reauth_token, _context(clock))

    if initial.subject != refreshed.subject or initial.subject != reauth.subject:
        raise QualificationError("subject_continuity_failed")
    if not initial.session_id or refreshed.session_id != initial.session_id:
        raise QualificationError("refresh_session_continuity_failed")
    if not reauth.session_id or reauth.session_id == initial.session_id:
        raise QualificationError("reauth_new_session_not_observed")
    if initial.auth_time is None or refreshed.auth_time is None or reauth.auth_time is None:
        raise QualificationError("auth_time_missing")
    if refreshed.auth_time != initial.auth_time:
        raise QualificationError("refresh_changed_auth_time")
    if refresh_iat <= initial_iat:
        raise QualificationError("refresh_iat_not_advanced")
    if reauth_iat <= refresh_iat:
        raise QualificationError("reauth_iat_not_advanced")
    if reauth.auth_time <= refreshed.auth_time:
        raise QualificationError("reauth_auth_time_not_advanced")
    if reauth.auth_time <= refresh_iat:
        raise QualificationError("reauth_must_follow_refresh_for_fence_witness")

    # Place the application fence strictly after refresh issuance but strictly
    # before the new authentication ceremony. This proves Princess semantics
    # without mutating or revoking the provider account.
    fence = refresh_iat + (reauth.auth_time - refresh_iat) / 2
    clock.set(initial_iat)
    provider = _provider(issuer=issuer, audience=audience, role=role, jwks=jwks, clock=clock)
    service = IdentityService(provider, InMemoryIdentityStore(), clock, SequentialIds())
    principal = service.authenticate(initial_token, _context(clock))

    clock.set(fence)
    service.logout_everywhere(principal, _context(clock))
    refresh_rejected = False
    try:
        service.authenticate(refreshed_token, _context(clock))
    except Unauthenticated as exc:
        refresh_rejected = exc.code == "session_revoked"
    if not refresh_rejected:
        raise QualificationError("refresh_crossed_revocation_fence")

    clock.set(reauth_iat)
    rebound = service.authenticate(reauth_token, _context(clock))
    if rebound.principal_id != principal.principal_id:
        raise QualificationError("reauth_principal_continuity_failed")

    key_algs = sorted({
        str(key.get("alg")) for key in jwks.get("keys", [])
        if isinstance(key, dict) and isinstance(key.get("alg"), str)
    })
    token_algs = sorted({
        str(initial_header.get("alg")), str(refresh_header.get("alg")), str(reauth_header.get("alg"))
    })
    receipt = {
        "version": VERSION,
        "provider": "supabase-auth",
        "project_alias": project_alias,
        "evidence_kind": evidence_kind,
        "provider_selection_claim": False,
        "production_activation": False,
        "source_revision": SOURCE_REVISION,
        "issuer_sha256": _text_hash(issuer),
        "audience": audience,
        "allowed_role": role,
        "custom_access_token_hook": "disabled",
        "jwks_sha256": _canonical_hash(jwks),
        "jwks_key_count": len(jwks.get("keys", [])),
        "jwks_algorithms": key_algs,
        "observed_token_algorithms": token_algs,
        "same_subject_initial_refresh": True,
        "same_session_initial_refresh": True,
        "reauth_same_subject": True,
        "reauth_new_session": True,
        "refresh_iat_advanced": True,
        "refresh_auth_time_unchanged": True,
        "reauth_iat_advanced": True,
        "reauth_auth_time_advanced": True,
        "logout_fence_refresh_rejected": True,
        "logout_fence_reauth_accepted": True,
        "refresh_iat_delta_s": int((refresh_iat - initial_iat).total_seconds()),
        "reauth_iat_delta_s": int((reauth_iat - refresh_iat).total_seconds()),
        "reauth_auth_time_delta_s": int((reauth.auth_time - refreshed.auth_time).total_seconds()),
        "result": "PASS",
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(data: dict[str, Any]) -> None:
    booleans = (
        "same_subject_initial_refresh", "same_session_initial_refresh", "reauth_same_subject",
        "reauth_new_session", "refresh_iat_advanced", "refresh_auth_time_unchanged",
        "reauth_iat_advanced", "reauth_auth_time_advanced", "logout_fence_refresh_rejected",
        "logout_fence_reauth_accepted",
    )
    if data.get("version") != VERSION or data.get("provider") != "supabase-auth":
        raise QualificationError("receipt_version")
    if data.get("provider_selection_claim") is not False or data.get("production_activation") is not False:
        raise QualificationError("receipt_scope")
    if data.get("source_revision") != SOURCE_REVISION:
        raise QualificationError("receipt_source_revision")
    for name in ("issuer_sha256", "jwks_sha256"):
        value = data.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise QualificationError(f"receipt_{name}")
    if data.get("evidence_kind") not in EVIDENCE_KINDS or data.get("custom_access_token_hook") != "disabled":
        raise QualificationError("receipt_profile")
    if any(data.get(name) is not True for name in booleans):
        raise QualificationError("receipt_witness")
    for name in ("refresh_iat_delta_s", "reauth_iat_delta_s", "reauth_auth_time_delta_s"):
        if not isinstance(data.get(name), int) or data[name] <= 0:
            raise QualificationError(f"receipt_{name}")
    if not isinstance(data.get("jwks_key_count"), int) or data["jwks_key_count"] < 1:
        raise QualificationError("receipt_jwks_key_count")
    if data.get("result") != "PASS":
        raise QualificationError("receipt_result")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-alias", required=True)
    parser.add_argument("--evidence-kind", choices=EVIDENCE_KINDS, required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--custom-access-token-hook", choices=("disabled", "enabled", "unknown"), required=True)
    parser.add_argument("--jwks-file", type=Path, required=True)
    parser.add_argument("--initial-token-file", type=Path, required=True)
    parser.add_argument("--refreshed-token-file", type=Path, required=True)
    parser.add_argument("--reauth-token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if os.environ.get("PRINCESS_SUPABASE_QUALIFY") != "1":
        print("FAIL: explicit PRINCESS_SUPABASE_QUALIFY=1 gate required")
        return 2

    try:
        document = qualify(
            project_alias=args.project_alias,
            evidence_kind=args.evidence_kind,
            issuer=args.issuer,
            audience=args.audience,
            role=args.role,
            custom_access_token_hook=args.custom_access_token_hook,
            jwks=_load_jwks(args.jwks_file),
            initial_token=_read_secret(args.initial_token_file),
            refreshed_token=_read_secret(args.refreshed_token_file),
            reauth_token=_read_secret(args.reauth_token_file),
        )
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, QualificationError, Unauthenticated, ValueError) as exc:
        code = exc.code if isinstance(exc, Unauthenticated) else str(exc)
        print(f"FAIL: {code}")
        return 1
    print(f"PASS {VERSION} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
