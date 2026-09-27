"""IdentityProvider port (docs/connectors/identity.md).

A :class:`VerifiedIdentity` proves who authenticated; it carries no authority
to read a report. The application maps ``(issuer, subject)`` to its own
principal and authorizes objects separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .base import CallContext, CapabilityProfile, InvalidInput, require_utc

PORT = "IdentityProvider"

# Capability names.
VERIFY_ID_TOKEN = "verify_id_token"
REVOKE_SESSION = "revoke_session"
DELETE_PROVIDER_ACCOUNT = "delete_provider_account"


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    audience: str
    expires_at: datetime
    session_id: str | None = None
    # Attributes are present only if the provider supplied them; ``None`` means
    # unknown, never "false" or "unverified".
    email: str | None = None
    email_verified: bool | None = None
    auth_time: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("issuer", "subject", "audience"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 512:
                raise InvalidInput("invalid_identity_claim", detail=name)
        require_utc(self.expires_at, "expires_at")
        if self.auth_time is not None:
            require_utc(self.auth_time, "auth_time")
        if self.email_verified is not None and type(self.email_verified) is not bool:
            raise InvalidInput("invalid_identity_claim", detail="email_verified")

    @property
    def binding_key(self) -> tuple[str, str]:
        """The only stable identity key. Email is never an account key."""
        return (self.issuer, self.subject)


class IdentityProvider(Protocol):
    profile: CapabilityProfile

    def verify_credential(self, credential: str, expected_audience: str,
                          ctx: CallContext) -> VerifiedIdentity:
        """Verify a bearer credential for ``expected_audience``.

        Raises ``Unauthenticated`` for bad signature, wrong issuer/audience,
        expiry, unknown key or revoked session.
        """
        ...

    def revoke_session(self, session_id: str, ctx: CallContext) -> None: ...

    def delete_provider_account(self, issuer: str, subject: str, ctx: CallContext) -> None:
        """Provider-side deletion coordination; does not delete application data."""
        ...
