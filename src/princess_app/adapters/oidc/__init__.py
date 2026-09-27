"""Generic OIDC ID-token verification behind the IdentityProvider port (T02).

The vendor (ADR-002) is still pending; this adapter implements the
provider-neutral part: JWKS from a *configured* source only, asymmetric
algorithms only, issuer/audience/expiry/not-before checks against the
injected clock, and one throttled JWKS refresh on an unknown key ID. Token
headers such as ``jku``/``x5u``/``jwk`` are never followed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

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

ASYMMETRIC = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA"})
JwksSource = Callable[[], Mapping[str, Any]]


class OidcIdentityProvider:
    port_name = port.PORT

    def __init__(self, *, issuer: str, jwks_source: JwksSource, clock: Clock, environment: Environment,
                 mode: ProviderMode, allowed_algorithms: frozenset[str] = frozenset({"RS256", "ES256"}),
                 leeway_s: int = 30, min_refresh_interval_s: int = 60) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if not allowed_algorithms or not allowed_algorithms <= ASYMMETRIC:
            raise ValueError("only asymmetric JWS algorithms may be configured")
        self.issuer = issuer
        self._source = jwks_source
        self._clock = clock
        self._algorithms = allowed_algorithms
        self._leeway = timedelta(seconds=leeway_s)
        self._min_refresh = timedelta(seconds=min_refresh_interval_s)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_refresh: datetime | None = None
        self.refresh_count = 0
        self.profile = CapabilityProfile(port=port.PORT, provider="oidc", mode=mode,
                                         capabilities=frozenset({port.VERIFY_ID_TOKEN}))

    def _refresh(self) -> None:
        with provider_errors():
            document = self._source()
        keys: dict[str, jwt.PyJWK] = {}
        for raw in document.get("keys", []) if isinstance(document, Mapping) else []:
            if not isinstance(raw, Mapping) or raw.get("kty") not in {"RSA", "EC", "OKP"} or not raw.get("kid"):
                continue  # symmetric or unidentified keys are never accepted
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

    def verify_credential(self, credential: str, expected_audience: str, ctx: CallContext) -> port.VerifiedIdentity:
        self.profile.require(port.VERIFY_ID_TOKEN)
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)
        try:
            header = jwt.get_unverified_header(credential)
        except jwt.InvalidTokenError:
            raise Unauthenticated("malformed_token") from None
        alg, kid = header.get("alg"), header.get("kid")
        if alg not in self._algorithms or not isinstance(kid, str):
            raise Unauthenticated("unsupported_token_algorithm")
        key = self._key(kid)
        if key.algorithm_name != alg:
            raise Unauthenticated("algorithm_key_mismatch")
        try:
            claims = jwt.decode(credential, key.key, algorithms=[alg], audience=expected_audience, issuer=self.issuer,
                                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_exp": False,
                                         "verify_nbf": False, "verify_iat": False})
        except jwt.InvalidAudienceError:
            raise Unauthenticated("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise Unauthenticated("wrong_issuer") from None
        except jwt.InvalidTokenError:
            raise Unauthenticated("invalid_token") from None
        now = self._clock.now()
        expires = _time(claims["exp"])
        if expires is None or now >= expires + self._leeway:
            raise Unauthenticated("expired")
        not_before = _time(claims.get("nbf"))
        issued = _time(claims["iat"])
        if (not_before is not None and now + self._leeway < not_before) or issued is None or issued > now + self._leeway:
            raise Unauthenticated("not_yet_valid")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise Unauthenticated("invalid_subject")
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        verified = claims.get("email_verified") if type(claims.get("email_verified")) is bool else None
        return port.VerifiedIdentity(issuer=self.issuer, subject=subject, audience=expected_audience,
                                     expires_at=expires, session_id=claims.get("sid") if isinstance(
                                         claims.get("sid"), str) else None, email=email, email_verified=verified,
                                     auth_time=_time(claims.get("auth_time")) or issued)

    def revoke_session(self, session_id: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="oidc:revoke_session")

    def delete_provider_account(self, issuer: str, subject: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="oidc:delete_provider_account")


def _time(value: Any) -> datetime | None:
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
