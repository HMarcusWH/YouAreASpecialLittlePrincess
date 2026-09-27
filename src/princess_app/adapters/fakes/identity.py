"""Fake IdentityProvider with expiry, audience, key rotation and revocation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ...ports import identity as port
from ...ports.base import CallContext, Unauthenticated
from .base import FakeAdapter, SequentialIds


@dataclass
class _Token:
    kid: str
    subject: str
    audience: str
    issued_at: object
    expires_at: object
    session_id: str | None
    email: str | None
    email_verified: bool | None


class FakeIdentityProvider(FakeAdapter):
    port_name = port.PORT
    provider = "fake-oidc"
    default_capabilities = frozenset({port.VERIFY_ID_TOKEN, port.REVOKE_SESSION, port.DELETE_PROVIDER_ACCOUNT})

    def __init__(self, *, issuer: str = "https://idp.fake.invalid", **kwargs) -> None:
        super().__init__(**kwargs)
        self.issuer = issuer
        self._ids = SequentialIds()
        self._kid = "kid-1"
        self._kid_generation = 1
        self._tokens: dict[str, _Token] = {}
        self._revoked_sessions: set[str] = set()
        self._deleted_subjects: set[str] = set()

    # --- test controls -------------------------------------------------
    def issue_token(self, subject: str, audience: str, *, ttl_s: int = 3600, session_id: str | None = None,
                    email: str | None = None, email_verified: bool | None = None) -> str:
        token_id = self._ids.new_id("tok")
        now = self.clock.now()
        self._tokens[token_id] = _Token(self._kid, subject, audience, now, now + timedelta(seconds=ttl_s),
                                        session_id, email, email_verified)
        return f"fakeid.{self._kid}.{token_id}"

    def rotate_keys(self) -> None:
        """Tokens signed with the previous key no longer verify."""
        self._kid_generation += 1
        self._kid = f"kid-{self._kid_generation}"

    # --- port -----------------------------------------------------------
    def verify_credential(self, credential: str, expected_audience: str, ctx: CallContext) -> port.VerifiedIdentity:
        self.profile.require(port.VERIFY_ID_TOKEN)

        def effect() -> port.VerifiedIdentity:
            parts = credential.split(".") if isinstance(credential, str) else []
            if len(parts) != 3 or parts[0] != "fakeid" or parts[2] not in self._tokens:
                raise Unauthenticated("malformed_or_unknown_token")
            token = self._tokens[parts[2]]
            if parts[1] != token.kid or token.kid != self._kid:
                raise Unauthenticated("unknown_signing_key")
            if token.audience != expected_audience:
                raise Unauthenticated("wrong_audience")
            if self.clock.now() >= token.expires_at:
                raise Unauthenticated("expired")
            if token.session_id is not None and token.session_id in self._revoked_sessions:
                raise Unauthenticated("session_revoked")
            if token.subject in self._deleted_subjects:
                raise Unauthenticated("account_deleted")
            return port.VerifiedIdentity(
                issuer=self.issuer, subject=token.subject, audience=token.audience,
                expires_at=token.expires_at, session_id=token.session_id, email=token.email,
                email_verified=token.email_verified, auth_time=token.issued_at)

        return self._run("verify_credential", ctx, effect)

    def revoke_session(self, session_id: str, ctx: CallContext) -> None:
        self.profile.require(port.REVOKE_SESSION)
        self._run("revoke_session", ctx, lambda: self._revoked_sessions.add(session_id))

    def delete_provider_account(self, issuer: str, subject: str, ctx: CallContext) -> None:
        self.profile.require(port.DELETE_PROVIDER_ACCOUNT)
        self._run("delete_provider_account", ctx, lambda: self._deleted_subjects.add(subject))
