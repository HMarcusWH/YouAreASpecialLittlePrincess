"""Production-disabled Supabase Auth access-token candidate for IdentityProvider.

This adapter qualifies one narrow first-party Supabase Auth profile only:

* asymmetric project signing keys from a configured JWKS source;
* exact configured issuer and singleton audience;
* configured authenticated application roles;
* non-anonymous sessions with canonical UUID user/session identifiers;
* the stock claims profile (no unaudited Custom Access Token Hook);
* authentication freshness derived only from timestamped, reviewed AMR methods.

It is not composed by the API. ADR-002 still requires provider/account/data approval,
actual project qualification and web/native lifecycle evidence before activation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from uuid import UUID

import jwt

from ...ports import identity as port
from ...ports.base import (
    CallContext,
    CapabilityProfile,
    Clock,
    Environment,
    InvalidInput,
    ProviderMode,
    Unauthenticated,
    Unsupported,
    check_mode_allowed,
    provider_errors,
)

ASYMMETRIC = frozenset({"RS256", "RS512", "ES256", "ES512", "EdDSA"})
JwksSource = Callable[[], Mapping[str, Any]]
MAX_AMR_ENTRIES = 32

# Reviewed against supabase/auth@ce9a8eee0cc042be8c7a42981a7ddae631e41d91.
# These methods represent a user authentication / reauthentication ceremony.
FRESHNESS_METHODS = frozenset({
    "oauth",
    "password",
    "otp",
    "totp",
    "mfa/phone",
    "mfa/webauthn",
    "mfa/recovery_code",
    "sso/saml",
    "magiclink",
    "recovery",
    "web3",
    "oauth_provider/authorization_code",
    "passkey",
})


class SupabaseIdentityProvider:
    """Verify the reviewed first-party Supabase access-token candidate profile."""

    port_name = port.PORT

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_roles: frozenset[str],
        jwks_source: JwksSource,
        clock: Clock,
        environment: Environment,
        mode: ProviderMode,
        stock_claims_profile: bool,
        allowed_algorithms: frozenset[str] = ASYMMETRIC,
        leeway_s: int = 30,
        min_refresh_interval_s: int = 60,
    ) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if stock_claims_profile is not True:
            raise Unsupported("supabase_custom_claim_profile_not_qualified")
        if not _https_issuer(issuer):
            raise InvalidInput("invalid_identity_issuer")
        if not isinstance(audience, str) or not audience or len(audience) > 512:
            raise InvalidInput("invalid_identity_audience")
        if (
            not isinstance(allowed_roles, frozenset)
            or not allowed_roles
            or any(not isinstance(role, str) or not role or len(role) > 128 for role in allowed_roles)
        ):
            raise InvalidInput("invalid_identity_roles")
        if not allowed_algorithms or not allowed_algorithms <= ASYMMETRIC:
            raise ValueError("supabase candidate requires reviewed asymmetric JWS algorithms")
        if type(leeway_s) is not int or leeway_s < 0:
            raise InvalidInput("invalid_identity_leeway")
        if type(min_refresh_interval_s) is not int or min_refresh_interval_s < 1:
            raise InvalidInput("invalid_identity_refresh_interval")

        self.issuer = issuer
        self.audience = audience
        self.allowed_roles = allowed_roles
        self._source = jwks_source
        self._clock = clock
        self._algorithms = allowed_algorithms
        self._leeway = timedelta(seconds=leeway_s)
        self._min_refresh = timedelta(seconds=min_refresh_interval_s)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_refresh: datetime | None = None
        self.refresh_count = 0
        self.profile = CapabilityProfile(
            port=port.PORT,
            provider="supabase-auth-candidate",
            mode=mode,
            capabilities=frozenset({port.VERIFY_CREDENTIAL}),
            notes=("stock_claims_profile_only", "asymmetric_signing_only"),
        )

    def _refresh(self) -> None:
        with provider_errors():
            document = self._source()
        keys: dict[str, jwt.PyJWK] = {}
        for raw in document.get("keys", []) if isinstance(document, Mapping) else []:
            if not isinstance(raw, Mapping) or raw.get("kty") not in {"RSA", "EC", "OKP"} or not raw.get("kid"):
                continue
            if raw.get("use") not in (None, "sig"):
                continue
            try:
                key = jwt.PyJWK(dict(raw))
            except jwt.PyJWKError:
                continue
            if key.algorithm_name in self._algorithms:
                keys[str(raw["kid"])] = key
        self._keys = keys
        self._last_refresh = self._clock.now()
        self.refresh_count += 1

    def _key(self, kid: str) -> jwt.PyJWK:
        if kid not in self._keys:
            now = self._clock.now()
            if self._last_refresh is None or now - self._last_refresh >= self._min_refresh:
                self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise Unauthenticated("unknown_signing_key")
        return key

    def verify_credential(self, credential: str, ctx: CallContext) -> port.VerifiedIdentity:
        self.profile.require(port.VERIFY_CREDENTIAL)
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)
        try:
            header = jwt.get_unverified_header(credential)
        except jwt.InvalidTokenError:
            raise Unauthenticated("malformed_token") from None

        alg, kid = header.get("alg"), header.get("kid")
        if alg not in self._algorithms or not isinstance(kid, str) or not kid:
            raise Unauthenticated("unsupported_token_algorithm")
        key = self._key(kid)
        if key.algorithm_name != alg:
            raise Unauthenticated("algorithm_key_mismatch")

        try:
            claims = jwt.decode(
                credential,
                key.key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "role", "aal", "session_id", "is_anonymous"],
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
        except jwt.InvalidAudienceError:
            raise Unauthenticated("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise Unauthenticated("wrong_issuer") from None
        except jwt.InvalidTokenError:
            raise Unauthenticated("invalid_token") from None

        # The reviewed stock first-party profile serializes one project audience
        # as a string. Multi-audience/OAuth-server credentials are another profile.
        if claims.get("aud") != self.audience:
            raise Unauthenticated("wrong_audience")
        role = claims.get("role")
        if not isinstance(role, str) or role not in self.allowed_roles:
            raise Unauthenticated("unapproved_role")
        if claims.get("aal") not in {"aal1", "aal2"}:
            raise Unauthenticated("invalid_aal")
        if claims.get("is_anonymous") is not False:
            raise Unauthenticated("anonymous_identity_not_allowed")
        if "client_id" in claims:
            raise Unauthenticated("unsupported_credential_profile")

        subject = _canonical_uuid(claims.get("sub"), "invalid_subject")
        session_id = _canonical_uuid(claims.get("session_id"), "invalid_session_id")

        now = self._clock.now()
        expires = _time(claims.get("exp"))
        issued = _time(claims.get("iat"))
        if expires is None or issued is None:
            raise Unauthenticated("invalid_token_time")
        if now >= expires + self._leeway:
            raise Unauthenticated("expired")
        if issued > now + self._leeway:
            raise Unauthenticated("not_yet_valid")

        raw_nbf = claims.get("nbf")
        if raw_nbf is not None:
            not_before = _time(raw_nbf)
            if not_before is None:
                raise Unauthenticated("invalid_token_time")
            if now + self._leeway < not_before:
                raise Unauthenticated("not_yet_valid")

        auth_time = _amr_auth_time(claims.get("amr"), now=now, issued=issued, leeway=self._leeway)
        return port.VerifiedIdentity(
            issuer=self.issuer,
            subject=subject,
            expires_at=expires,
            session_id=session_id,
            auth_time=auth_time,
        )

    def revoke_session(self, session_id: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="supabase-auth-candidate:revoke_session")

    def delete_provider_account(self, issuer: str, subject: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="supabase-auth-candidate:delete_provider_account")


def _amr_auth_time(raw: Any, *, now: datetime, issued: datetime, leeway: timedelta) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > MAX_AMR_ENTRIES:
        raise Unauthenticated("invalid_amr")
    freshness: list[datetime] = []
    for entry in raw:
        if isinstance(entry, str):
            if not entry or len(entry) > 64:
                raise Unauthenticated("invalid_amr")
            # Supabase can parse string AMR in compatibility paths, but without
            # a timestamp it cannot satisfy Princess's revocation freshness fence.
            continue
        if not isinstance(entry, Mapping):
            raise Unauthenticated("invalid_amr")
        method = entry.get("method")
        timestamp = entry.get("timestamp")
        if not isinstance(method, str) or not method or len(method) > 64 or type(timestamp) is not int:
            raise Unauthenticated("invalid_amr")
        at = _time(timestamp)
        if at is None or at > now + leeway or at > issued + leeway:
            raise Unauthenticated("invalid_amr")
        if method in FRESHNESS_METHODS:
            freshness.append(at)
    return max(freshness) if freshness else None


def _canonical_uuid(value: Any, code: str) -> str:
    if not isinstance(value, str):
        raise Unauthenticated(code)
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        raise Unauthenticated(code) from None
    if value != canonical:
        raise Unauthenticated(code)
    return canonical


def _time(value: Any) -> datetime | None:
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _https_issuer(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
    )
