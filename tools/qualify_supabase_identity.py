#!/usr/bin/env python3
"""Supabase Auth account-profile qualification; emits no credential material."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from princess_app.adapters.fakes import SequentialIds  # noqa: E402
from princess_app.adapters.supabase import SupabaseIdentityProvider  # noqa: E402
from princess_app.adapters.supabase.jwks import SupabaseJwksSource, supabase_jwks_url  # noqa: E402
from princess_app.application.identity import IdentityService, InMemoryIdentityStore  # noqa: E402
from princess_app.config import load_manifest  # noqa: E402
from princess_app.ports.base import CallContext, Environment, PortError, ProviderMode, Unauthenticated  # noqa: E402

VERSION = "supabase-identity-qualification/4"
SOURCE_REVISION = "ce9a8eee0cc042be8c7a42981a7ddae631e41d91"
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_KINDS = ("SYNTHETIC_TEST", "MANAGED_PROJECT")
ACCOUNT_POLICY_STATES = ("disabled", "enabled")
REFRESH_SOURCES = ("SUPPLIED_SYNTHETIC_REFRESH", "LIVE_PROVIDER_REFRESH")
PROJECT_BINDINGS = ("QUALIFICATION_ONLY", "INTENDED_RUNTIME_PROFILE")
QUALIFICATION_ENVIRONMENTS = frozenset({Environment.STAGING, Environment.PRODUCTION})
MAX_REFRESH_RESPONSE_BYTES = 256 * 1024
ASYMMETRIC = frozenset({"RS256", "RS512", "ES256", "ES512", "EdDSA"})


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


def _issuer_host(issuer: str) -> str:
    host = urlsplit(issuer).hostname
    if not host:
        raise QualificationError("issuer_host_invalid")
    return host


def _jwks_url(issuer: str) -> str:
    return supabase_jwks_url(issuer)


def _qualification_scope(environment: str, provider_mode: str) -> tuple[Environment, ProviderMode, str]:
    try:
        env = Environment.parse(environment)
    except PortError as exc:
        raise QualificationError("qualification_environment_invalid") from exc
    try:
        mode = ProviderMode(provider_mode)
    except ValueError as exc:
        raise QualificationError("qualification_provider_mode_invalid") from exc
    if env not in QUALIFICATION_ENVIRONMENTS:
        raise QualificationError("qualification_environment_not_managed")
    try:
        manifest = load_manifest(ROOT, env)
    except PortError as exc:
        raise QualificationError("qualification_environment_manifest_invalid") from exc
    if manifest.providers["IdentityProvider"] is not mode:
        raise QualificationError("identity_mode_manifest_mismatch")
    path = ROOT / "infra" / "environments" / f"{env.value}.json"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise QualificationError("qualification_environment_manifest_unreadable") from exc
    return env, mode, digest


def _repo_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("princess_commit_unavailable") from exc
    commit = result.stdout.strip().lower()
    if not COMMIT.fullmatch(commit):
        raise QualificationError("princess_commit_invalid")
    if status.stdout.strip():
        raise QualificationError("princess_checkout_dirty")
    return commit


def _api_key_kind(value: str) -> str:
    if value.startswith("sb_publishable_") and len(value) <= 512:
        return "publishable"
    if value.startswith("sb_secret_"):
        raise QualificationError("elevated_api_key_not_allowed")
    try:
        claims = jwt.decode(value, options={"verify_signature": False, "verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise QualificationError("unsupported_api_key_profile") from exc
    if not isinstance(claims, dict):
        raise QualificationError("unsupported_api_key_profile")
    role = claims.get("role")
    if role == "anon":
        return "legacy_anon"
    if role == "service_role":
        raise QualificationError("elevated_api_key_not_allowed")
    raise QualificationError("unsupported_api_key_profile")


def _fetch_jwks(
    issuer: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    try:
        return dict(SupabaseJwksSource(issuer, transport=transport, timeout_s=timeout_s)())
    except PortError as exc:
        if exc.code in {"identity_jwks_invalid", "identity_jwks_too_large"}:
            raise QualificationError("jwks_invalid") from exc
        raise QualificationError("jwks_request_failed") from exc


def _refresh_access_token(
    issuer: str,
    *,
    api_key: str,
    refresh_token: str,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 10.0,
    max_response_bytes: int = MAX_REFRESH_RESPONSE_BYTES,
) -> tuple[str, int]:
    _api_key_kind(api_key)
    if not refresh_token or len(refresh_token) > 65536:
        raise QualificationError("refresh_token_invalid")
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not 0 < float(timeout_s) <= 30:
        raise QualificationError("refresh_timeout_invalid")
    if type(max_response_bytes) is not int or not 4096 <= max_response_bytes <= 1024 * 1024:
        raise QualificationError("refresh_response_limit_invalid")

    _jwks_url(issuer)  # Reuse the reviewed HTTPS issuer-shape validation.
    endpoint = issuer.rstrip("/") + "/token"
    try:
        with httpx.Client(
            transport=transport,
            timeout=float(timeout_s),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream(
                "POST",
                endpoint,
                params={"grant_type": "refresh_token"},
                headers={"apikey": api_key, "Accept": "application/json"},
                json={"refresh_token": refresh_token},
            ) as response:
                status = response.status_code
                if status == 429:
                    raise QualificationError("refresh_rate_limited")
                if 500 <= status <= 599:
                    raise QualificationError("refresh_unavailable")
                if 300 <= status <= 399:
                    raise QualificationError("refresh_redirect_refused")
                if status != 200:
                    raise QualificationError("refresh_http_error")

                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_response_bytes:
                        raise QualificationError("refresh_response_too_large")
                    chunks.append(chunk)
    except QualificationError:
        raise
    except httpx.HTTPError as exc:
        raise QualificationError("refresh_request_failed") from exc

    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, ValueError) as exc:
        raise QualificationError("refresh_response_invalid") from exc
    if not isinstance(payload, dict):
        raise QualificationError("refresh_response_invalid")
    access_token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 65536:
        raise QualificationError("refresh_access_token_missing")
    if type(expires_in) is not int or expires_in <= 0:
        raise QualificationError("refresh_expires_in_invalid")
    return access_token, expires_in


def _context(clock: MutableClock, environment: Environment) -> CallContext:
    return CallContext("supabase-qualification", environment, clock.now() + timedelta(minutes=1))


def _provider(
    *,
    issuer: str,
    audience: str,
    role: str,
    jwks: dict[str, Any],
    clock: MutableClock,
    environment: Environment,
    mode: ProviderMode,
) -> SupabaseIdentityProvider:
    return SupabaseIdentityProvider(
        issuer=issuer,
        audience=audience,
        allowed_roles=frozenset({role}),
        jwks_source=lambda: jwks,
        clock=clock,
        environment=environment,
        mode=mode,
        stock_claims_profile=True,
    )


def _token_lifetime(claims: dict[str, Any], name: str) -> int:
    issued = _dt(claims.get("iat"), f"{name}_iat")
    expires = _dt(claims.get("exp"), f"{name}_exp")
    seconds = int((expires - issued).total_seconds())
    if seconds <= 0:
        raise QualificationError(f"{name}_lifetime_invalid")
    return seconds


def _amr_methods(claims: dict[str, Any]) -> list[str]:
    raw = claims.get("amr")
    if not isinstance(raw, list):
        return []
    methods: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            methods.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("method"), str):
            methods.add(str(entry["method"]))
    return sorted(methods)


def _jwks_key_ids(jwks: dict[str, Any]) -> list[str]:
    return sorted({
        str(key["kid"])
        for key in jwks.get("keys", [])
        if isinstance(key, dict) and isinstance(key.get("kid"), str) and key["kid"]
    })


def qualify(
    *,
    project_alias: str,
    evidence_kind: str,
    project_binding: str,
    environment: str,
    provider_mode: str,
    princess_commit: str,
    issuer: str,
    audience: str,
    role: str,
    custom_access_token_hook: str,
    anonymous_sign_in_policy: str,
    oauth_server_status: str,
    pre_rotation_jwks: dict[str, Any],
    jwks: dict[str, Any],
    initial_token: str,
    refreshed_token: str,
    reauth_token: str,
    refresh_source: str,
    refresh_response_expires_in_s: int,
) -> dict[str, Any]:
    if not ALIAS.fullmatch(project_alias):
        raise QualificationError("project_alias_invalid")
    if evidence_kind not in EVIDENCE_KINDS:
        raise QualificationError("evidence_kind_invalid")
    if project_binding not in PROJECT_BINDINGS:
        raise QualificationError("project_binding_invalid")
    if evidence_kind == "SYNTHETIC_TEST" and project_binding != "QUALIFICATION_ONLY":
        raise QualificationError("synthetic_cannot_bind_runtime_profile")
    env, mode, environment_manifest_sha256 = _qualification_scope(environment, provider_mode)
    if not COMMIT.fullmatch(princess_commit):
        raise QualificationError("princess_commit_invalid")
    if custom_access_token_hook != "disabled":
        raise QualificationError("custom_access_token_hook_not_qualified")
    if anonymous_sign_in_policy not in ACCOUNT_POLICY_STATES:
        raise QualificationError("anonymous_sign_in_policy_unreviewed")
    if oauth_server_status not in ACCOUNT_POLICY_STATES:
        raise QualificationError("oauth_server_status_unreviewed")
    if refresh_source not in REFRESH_SOURCES:
        raise QualificationError("refresh_source_invalid")
    if evidence_kind == "MANAGED_PROJECT" and refresh_source != "LIVE_PROVIDER_REFRESH":
        raise QualificationError("managed_project_requires_live_refresh")
    if type(refresh_response_expires_in_s) is not int or refresh_response_expires_in_s <= 0:
        raise QualificationError("refresh_expires_in_invalid")

    initial_header, initial_claims = _peek(initial_token)
    refresh_header, refresh_claims = _peek(refreshed_token)
    reauth_header, reauth_claims = _peek(reauth_token)
    initial_iat = _dt(initial_claims.get("iat"), "initial_iat")
    refresh_iat = _dt(refresh_claims.get("iat"), "refresh_iat")
    reauth_iat = _dt(reauth_claims.get("iat"), "reauth_iat")

    initial_lifetime = _token_lifetime(initial_claims, "initial")
    refresh_lifetime = _token_lifetime(refresh_claims, "refresh")
    reauth_lifetime = _token_lifetime(reauth_claims, "reauth")
    if len({initial_lifetime, refresh_lifetime, reauth_lifetime}) != 1:
        raise QualificationError("access_token_lifetime_drift")
    if abs(refresh_response_expires_in_s - refresh_lifetime) > 1:
        raise QualificationError("refresh_expires_in_mismatch")

    initial_kid = initial_header.get("kid")
    refresh_kid = refresh_header.get("kid")
    reauth_kid = reauth_header.get("kid")
    if not all(isinstance(kid, str) and kid for kid in (initial_kid, refresh_kid, reauth_kid)):
        raise QualificationError("signing_key_id_missing")
    if refresh_kid != initial_kid:
        raise QualificationError("refresh_signing_key_changed_before_rotation_witness")
    if reauth_kid == refresh_kid:
        raise QualificationError("signing_key_rotation_not_observed")
    pre_rotation_kids = set(_jwks_key_ids(pre_rotation_jwks))
    final_kids = set(_jwks_key_ids(jwks))
    if initial_kid not in pre_rotation_kids:
        raise QualificationError("pre_rotation_jwks_missing_initial_key")
    if initial_kid not in final_kids or reauth_kid not in final_kids:
        raise QualificationError("rotation_jwks_missing_trusted_key")

    clock = MutableClock(initial_iat)
    provider = _provider(
        issuer=issuer,
        audience=audience,
        role=role,
        jwks=jwks,
        clock=clock,
        environment=env,
        mode=mode,
    )
    initial = provider.verify_credential(initial_token, _context(clock, env))
    clock.set(refresh_iat)
    refreshed = provider.verify_credential(refreshed_token, _context(clock, env))
    clock.set(reauth_iat)
    reauth = provider.verify_credential(reauth_token, _context(clock, env))

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

    fence = refresh_iat + (reauth.auth_time - refresh_iat) / 2
    clock.set(initial_iat)
    provider = _provider(
        issuer=issuer,
        audience=audience,
        role=role,
        jwks=jwks,
        clock=clock,
        environment=env,
        mode=mode,
    )
    service = IdentityService(provider, InMemoryIdentityStore(), clock, SequentialIds())
    principal = service.authenticate(initial_token, _context(clock, env))

    clock.set(fence)
    service.logout_everywhere(principal, _context(clock, env))
    refresh_rejected = False
    try:
        service.authenticate(refreshed_token, _context(clock, env))
    except Unauthenticated as exc:
        refresh_rejected = exc.code == "session_revoked"
    if not refresh_rejected:
        raise QualificationError("refresh_crossed_revocation_fence")

    clock.set(reauth_iat)
    rebound = service.authenticate(reauth_token, _context(clock, env))
    if rebound.principal_id != principal.principal_id:
        raise QualificationError("reauth_principal_continuity_failed")

    key_algs = sorted({
        str(key.get("alg"))
        for key in jwks.get("keys", [])
        if isinstance(key, dict) and isinstance(key.get("alg"), str)
    })
    if not key_algs or any(alg not in ASYMMETRIC for alg in key_algs):
        raise QualificationError("jwks_not_asymmetric")
    token_algs = sorted({
        str(initial_header.get("alg")),
        str(refresh_header.get("alg")),
        str(reauth_header.get("alg")),
    })
    if any(alg not in ASYMMETRIC for alg in token_algs):
        raise QualificationError("token_not_asymmetric")

    receipt = {
        "version": VERSION,
        "provider": "supabase-auth",
        "project_alias": project_alias,
        "evidence_kind": evidence_kind,
        "project_binding": project_binding,
        "environment": env.value,
        "provider_mode": mode.value,
        "environment_manifest_sha256": environment_manifest_sha256,
        "checked_date": datetime.now(timezone.utc).date().isoformat(),
        "princess_commit": princess_commit,
        "provider_selection_claim": False,
        "production_activation": False,
        "source_revision": SOURCE_REVISION,
        "issuer_host": _issuer_host(issuer),
        "issuer_sha256": _text_hash(issuer),
        "jwks_url_sha256": _text_hash(_jwks_url(issuer)),
        "audience": audience,
        "allowed_role": role,
        "custom_access_token_hook": "disabled",
        "anonymous_sign_in_policy": anonymous_sign_in_policy,
        "oauth_server_status": oauth_server_status,
        "stock_claims_profile": True,
        "pre_rotation_jwks_sha256": _canonical_hash(pre_rotation_jwks),
        "jwks_sha256": _canonical_hash(jwks),
        "jwks_key_count": len(jwks.get("keys", [])),
        "jwks_key_ids": _jwks_key_ids(jwks),
        "jwks_algorithms": key_algs,
        "observed_token_algorithms": token_algs,
        "access_token_lifetime_s": initial_lifetime,
        "refresh_source": refresh_source,
        "refresh_response_expires_in_s": refresh_response_expires_in_s,
        "amr_methods_initial": _amr_methods(initial_claims),
        "amr_methods_refreshed": _amr_methods(refresh_claims),
        "amr_methods_reauth": _amr_methods(reauth_claims),
        "same_subject_initial_refresh": True,
        "same_session_initial_refresh": True,
        "reauth_same_subject": True,
        "reauth_new_session": True,
        "refresh_iat_advanced": True,
        "refresh_auth_time_unchanged": True,
        "reauth_iat_advanced": True,
        "reauth_auth_time_advanced": True,
        "signing_key_rotation_observed": True,
        "pre_rotation_signing_kid": initial_kid,
        "post_rotation_signing_kid": reauth_kid,
        "post_rotation_jwks_contains_old_kid": True,
        "post_rotation_jwks_contains_new_kid": True,
        "anonymous_profile_excluded_by_adapter": True,
        "oauth_client_profile_excluded_by_adapter": True,
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
        "stock_claims_profile",
        "same_subject_initial_refresh",
        "same_session_initial_refresh",
        "reauth_same_subject",
        "reauth_new_session",
        "refresh_iat_advanced",
        "refresh_auth_time_unchanged",
        "reauth_iat_advanced",
        "reauth_auth_time_advanced",
        "signing_key_rotation_observed",
        "post_rotation_jwks_contains_old_kid",
        "post_rotation_jwks_contains_new_kid",
        "anonymous_profile_excluded_by_adapter",
        "oauth_client_profile_excluded_by_adapter",
        "logout_fence_refresh_rejected",
        "logout_fence_reauth_accepted",
    )
    if data.get("version") != VERSION or data.get("provider") != "supabase-auth":
        raise QualificationError("receipt_version")
    if data.get("provider_selection_claim") is not False or data.get("production_activation") is not False:
        raise QualificationError("receipt_scope")
    if data.get("source_revision") != SOURCE_REVISION:
        raise QualificationError("receipt_source_revision")
    if not isinstance(data.get("checked_date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["checked_date"]):
        raise QualificationError("receipt_checked_date")
    if not isinstance(data.get("princess_commit"), str) or not COMMIT.fullmatch(data["princess_commit"]):
        raise QualificationError("receipt_princess_commit")
    if not isinstance(data.get("issuer_host"), str) or not data["issuer_host"]:
        raise QualificationError("receipt_issuer_host")
    for name in ("issuer_sha256", "jwks_url_sha256", "pre_rotation_jwks_sha256", "jwks_sha256"):
        value = data.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise QualificationError(f"receipt_{name}")
    if data.get("evidence_kind") not in EVIDENCE_KINDS or data.get("custom_access_token_hook") != "disabled":
        raise QualificationError("receipt_profile")
    if data.get("project_binding") not in PROJECT_BINDINGS:
        raise QualificationError("receipt_project_binding")
    environment = data.get("environment")
    provider_mode = data.get("provider_mode")
    if not isinstance(environment, str) or not isinstance(provider_mode, str):
        raise QualificationError("receipt_environment_scope")
    try:
        _, _, expected_manifest_hash = _qualification_scope(environment, provider_mode)
    except QualificationError as exc:
        raise QualificationError("receipt_environment_scope") from exc
    manifest_hash = data.get("environment_manifest_sha256")
    if not isinstance(manifest_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash):
        raise QualificationError("receipt_environment_manifest_sha256")
    if manifest_hash != expected_manifest_hash:
        raise QualificationError("receipt_environment_manifest_mismatch")
    if data.get("evidence_kind") == "SYNTHETIC_TEST" and data.get("project_binding") != "QUALIFICATION_ONLY":
        raise QualificationError("receipt_synthetic_runtime_binding")
    if data.get("anonymous_sign_in_policy") not in ACCOUNT_POLICY_STATES:
        raise QualificationError("receipt_anonymous_policy")
    if data.get("oauth_server_status") not in ACCOUNT_POLICY_STATES:
        raise QualificationError("receipt_oauth_server_status")
    if data.get("refresh_source") not in REFRESH_SOURCES:
        raise QualificationError("receipt_refresh_source")
    if data.get("evidence_kind") == "MANAGED_PROJECT" and data.get("refresh_source") != "LIVE_PROVIDER_REFRESH":
        raise QualificationError("receipt_managed_refresh")
    if any(data.get(name) is not True for name in booleans):
        raise QualificationError("receipt_witness")
    for name in (
        "access_token_lifetime_s",
        "refresh_response_expires_in_s",
        "refresh_iat_delta_s",
        "reauth_iat_delta_s",
        "reauth_auth_time_delta_s",
    ):
        if not isinstance(data.get(name), int) or data[name] <= 0:
            raise QualificationError(f"receipt_{name}")
    if not isinstance(data.get("jwks_key_count"), int) or data["jwks_key_count"] < 2:
        raise QualificationError("receipt_jwks_key_count")
    kids = data.get("jwks_key_ids")
    if not isinstance(kids, list) or len(kids) < 2 or any(not isinstance(kid, str) or not kid for kid in kids):
        raise QualificationError("receipt_jwks_key_ids")
    if data.get("pre_rotation_signing_kid") == data.get("post_rotation_signing_kid"):
        raise QualificationError("receipt_rotation_kid")
    for name in ("pre_rotation_signing_kid", "post_rotation_signing_kid"):
        if data.get(name) not in kids:
            raise QualificationError(f"receipt_{name}")
    for name in ("jwks_algorithms", "observed_token_algorithms"):
        algs = data.get(name)
        if not isinstance(algs, list) or not algs or any(alg not in ASYMMETRIC for alg in algs):
            raise QualificationError(f"receipt_{name}")
    for name in ("amr_methods_initial", "amr_methods_refreshed", "amr_methods_reauth"):
        methods = data.get(name)
        if not isinstance(methods, list) or not methods or any(not isinstance(method, str) for method in methods):
            raise QualificationError(f"receipt_{name}")
    if data.get("result") != "PASS":
        raise QualificationError("receipt_result")


def _synthetic_or_managed_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], str, str, str, str, int]:
    initial_token = _read_secret(args.initial_token_file)
    if args.evidence_kind == "SYNTHETIC_TEST":
        if args.jwks_file is None or args.pre_rotation_jwks_file is None or args.refreshed_token_file is None:
            raise QualificationError("synthetic_fixture_inputs_required")
        if args.reauth_token_file is None:
            raise QualificationError("reauth_token_file_required")
        pre_rotation_jwks = _load_jwks(args.pre_rotation_jwks_file)
        jwks = _load_jwks(args.jwks_file)
        refreshed_token = _read_secret(args.refreshed_token_file)
        reauth_token = _read_secret(args.reauth_token_file)
        _, refresh_claims = _peek(refreshed_token)
        return (
            pre_rotation_jwks,
            jwks,
            initial_token,
            refreshed_token,
            reauth_token,
            "SUPPLIED_SYNTHETIC_REFRESH",
            _token_lifetime(refresh_claims, "refresh"),
        )

    if args.api_key_file is None or args.refresh_token_file is None or args.reauth_token_file is None:
        raise QualificationError("managed_refresh_inputs_required")
    if not sys.stdin.isatty():
        raise QualificationError("managed_qualification_requires_tty")
    api_key = _read_secret(args.api_key_file)
    refresh_token = _read_secret(args.refresh_token_file)
    reauth_before = None
    if args.reauth_token_file.exists():
        reauth_before = _text_hash(_read_secret(args.reauth_token_file))

    pre_rotation_jwks = _fetch_jwks(args.issuer)
    refreshed_token, expires_in = _refresh_access_token(
        args.issuer,
        api_key=api_key,
        refresh_token=refresh_token,
    )

    print(
        "LIVE REFRESH PASSED. In the authorized qualification project, rotate the asymmetric signing key, "
        "wait for JWKS propagation, then perform a genuine new sign-in. Write only the new access JWT to "
        f"{args.reauth_token_file} and press Enter."
    )
    try:
        input()
    except EOFError as exc:
        raise QualificationError("managed_qualification_confirmation_missing") from exc

    reauth_token = _read_secret(args.reauth_token_file)
    if reauth_before is not None and _text_hash(reauth_token) == reauth_before:
        raise QualificationError("reauth_token_file_not_replaced_after_refresh")
    jwks = _fetch_jwks(args.issuer)
    return (
        pre_rotation_jwks,
        jwks,
        initial_token,
        refreshed_token,
        reauth_token,
        "LIVE_PROVIDER_REFRESH",
        expires_in,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-alias", required=True)
    parser.add_argument("--evidence-kind", choices=EVIDENCE_KINDS, required=True)
    parser.add_argument("--project-binding", choices=PROJECT_BINDINGS, required=True)
    parser.add_argument("--environment", choices=tuple(env.value for env in QUALIFICATION_ENVIRONMENTS), required=True)
    parser.add_argument("--provider-mode", choices=tuple(mode.value for mode in ProviderMode), required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--custom-access-token-hook", choices=("disabled", "enabled", "unknown"), required=True)
    parser.add_argument("--anonymous-sign-ins", choices=("disabled", "enabled", "unknown"), required=True)
    parser.add_argument("--oauth-server", choices=("disabled", "enabled", "unknown"), required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--refresh-token-file", type=Path)
    parser.add_argument("--pre-rotation-jwks-file", type=Path)
    parser.add_argument("--jwks-file", type=Path)
    parser.add_argument("--initial-token-file", type=Path, required=True)
    parser.add_argument("--refreshed-token-file", type=Path)
    parser.add_argument("--reauth-token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if os.environ.get("PRINCESS_SUPABASE_QUALIFY") != "1":
        print("FAIL: explicit PRINCESS_SUPABASE_QUALIFY=1 gate required")
        return 2

    try:
        (
            pre_rotation_jwks,
            jwks,
            initial_token,
            refreshed_token,
            reauth_token,
            refresh_source,
            refresh_expires_in,
        ) = _synthetic_or_managed_inputs(args)
        document = qualify(
            project_alias=args.project_alias,
            evidence_kind=args.evidence_kind,
            project_binding=args.project_binding,
            environment=args.environment,
            provider_mode=args.provider_mode,
            princess_commit=_repo_commit(),
            issuer=args.issuer,
            audience=args.audience,
            role=args.role,
            custom_access_token_hook=args.custom_access_token_hook,
            anonymous_sign_in_policy=args.anonymous_sign_ins,
            oauth_server_status=args.oauth_server,
            pre_rotation_jwks=pre_rotation_jwks,
            jwks=jwks,
            initial_token=initial_token,
            refreshed_token=refreshed_token,
            reauth_token=reauth_token,
            refresh_source=refresh_source,
            refresh_response_expires_in_s=refresh_expires_in,
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
