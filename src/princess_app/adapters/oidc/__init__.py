"""Current provider-neutral OIDC ID-token profile behind IdentityProvider.

ADR-002 still owns the production credential decision. This adapter deliberately
remains ID-token-shaped and rejects RFC 9068 access-token types until that
decision is made. It verifies only a configured issuer/JWKS source, asymmetric
algorithms, audience/time claims and bounded key refresh. Token headers such as
``jku``/``x5u``/``jwk`` are never followed.
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


# A token without ``auth_time`` keeps it unknown: substituting ``iat`` would let
# a refreshed ID token pass the logout/deletion fence without a new sign-in.
ACCESS_TOKEN_TYPES = frozenset({"at+jwt", "application/at+jwt"})


class OidcIdentityProvider:
    port_name = port.PORT

    def __init__(self, *, issuer: str, audience: str, jwks_source: JwksSource, clock: Clock,
                 environment: Environment, mode: ProviderMode,
                 allowed_algorithms: frozenset[str] = frozenset({"RS256", "ES256"}),
                 leeway_s: int = 30, min_refresh_interval_s: int = 60) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if not allowed_algorithms or not allowed_algorithms <= ASYMMETRIC:
            raise ValueError("only asymmetric JWS algorithms may be configured")
        if not isinstance(audience, str) or not audience or len(audience) > 512:
            raise InvalidInput("invalid_identity_audience")
        self.issuer = issuer
        self.audience = audience
        self._source = jwks_source
        self._clock = clock
        self._algorithms = allowed_algorithms
        self._leeway = timedelta(seconds=leeway_s)
        self._min_refresh = timedelta(seconds=min_refresh_interval_s)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_refresh: datetime | None = None
        self.refresh_count = 0
        self.profile = CapabilityProfile(port=port.PORT, provider="oidc", mode=mode,
                                         capabilities=frozenset({port.VERIFY_CREDENTIAL}))

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
        if str(header.get("typ", "")).lower() in ACCESS_TOKEN_TYPES:
            raise Unauthenticated("not_an_id_token")  # RFC 9068 access tokens never authenticate a session
        if alg not in self._algorithms or not isinstance(kid, str):
            raise Unauthenticated("unsupported_token_algorithm")
        key = self._key(kid)
        if key.algorithm_name != alg:
            raise Unauthenticated("algorithm_key_mismatch")
        try:
            claims = jwt.decode(credential, key.key, algorithms=[alg], audience=self.audience, issuer=self.issuer,
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
        raw_auth_time = claims.get("auth_time")
        auth_time = _time(raw_auth_time)
        if raw_auth_time is not None and auth_time is None:
            raise Unauthenticated("invalid_auth_time")
        if auth_time is not None and (auth_time > now + self._leeway or auth_time > issued + self._leeway):
            raise Unauthenticated("invalid_auth_time")
        return port.VerifiedIdentity(issuer=self.issuer, subject=subject,
                                     expires_at=expires, session_id=claims.get("sid") if isinstance(
                                         claims.get("sid"), str) else None, email=email, email_verified=verified,
                                     auth_time=auth_time)

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
