"""Principals, provider identity bindings, guests and account lifecycle (T02).

* A verified ``(issuer, subject)`` maps to one internal principal. Email is
  never used to link or merge accounts.
* Guests hold an unguessable bearer capability; only its SHA-256 is stored.
  Transfer to an account requires the guest capability *and* an
  authenticated account, is atomic, and retires the guest capability.
* Logout-everywhere and deletion set ``revoked_before``; credentials whose
  authentication time is not after it are refused even if still unexpired.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

from ..ports.base import CallContext, Clock, Conflict, IdGenerator, NotFound, RateLimited, Unauthenticated
from ..ports.identity import IdentityProvider

GUEST_PREFIX = "guest_"
GUEST_TTL = timedelta(days=30)


@dataclass(frozen=True)
class GuestAdmission:
    """Global cap on unauthenticated guest creation per fixed window."""

    limit: int = 300
    window_seconds: int = 60


@dataclass(frozen=True)
class Principal:
    principal_id: str
    kind: str  # GUEST | ACCOUNT
    created_at: datetime
    revoked_before: datetime | None = None
    deleted_at: datetime | None = None
    transferred_to: str | None = None
    guest_expires_at: datetime | None = None


def capability_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IdentityStore(Protocol):
    def principal(self, principal_id: str) -> Principal | None: ...

    def principal_for_binding(self, issuer: str, subject: str) -> Principal | None: ...

    def create_account(self, principal_id: str, issuer: str, subject: str, at: datetime) -> Principal:
        """Raises ``Conflict`` if the binding already exists (concurrent first login)."""
        ...

    def create_guest(self, principal_id: str, token_hash: str, expires_at: datetime, at: datetime) -> Principal: ...

    def admit_guest(self, at: datetime, policy: GuestAdmission) -> bool:
        """Count one guest creation in the current window; False once it is full."""
        ...

    def guest_by_capability(self, token_hash: str) -> Principal | None: ...

    def transfer_guest(self, token_hash: str, account_id: str, at: datetime) -> str:
        """Atomically move a live guest's data to the account and retire the guest.
        Returns the guest principal ID; raises ``Conflict`` if already transferred."""
        ...

    def revoke_sessions(self, principal_id: str, at: datetime) -> None: ...

    def mark_deleted(self, principal_id: str, at: datetime) -> None:
        """Revoke access and queue erasure; the binding stays as a tombstone."""
        ...

    def rebind_after_deletion(self, issuer: str, subject: str, new_principal_id: str, at: datetime) -> Principal:
        """Point a tombstoned binding at a fresh principal (never the deleted one)."""
        ...

    def bindings(self, principal_id: str) -> list[tuple[str, str]]: ...


class IdentityService:
    def __init__(self, provider: IdentityProvider, store: IdentityStore, clock: Clock, ids: IdGenerator,
                 audience: str, guest_admission: GuestAdmission = GuestAdmission()) -> None:
        self._provider = provider
        self._store = store
        self._clock = clock
        self._ids = ids
        self._audience = audience
        self._guest_admission = guest_admission

    # --- authentication --------------------------------------------------
    def authenticate(self, credential: str, ctx: CallContext) -> Principal:
        if credential.startswith(GUEST_PREFIX):
            return self.authenticate_guest(credential)
        identity = self._provider.verify_credential(credential, self._audience, ctx)
        principal = self._store.principal_for_binding(identity.issuer, identity.subject)
        if principal is None:
            try:
                principal = self._store.create_account(self._ids.new_id("prn"), identity.issuer, identity.subject,
                                                       self._clock.now())
            except Conflict:
                principal = self._store.principal_for_binding(identity.issuer, identity.subject)
                if principal is None:
                    raise Unauthenticated("binding_unavailable") from None
        if principal.deleted_at is not None:
            # A credential authenticated after the deletion may start a new, empty
            # account; anything older is refused. Deleted data is never reattached.
            if identity.auth_time is None or identity.auth_time <= principal.deleted_at:
                raise Unauthenticated("account_deleted")
            try:
                principal = self._store.rebind_after_deletion(identity.issuer, identity.subject,
                                                              self._ids.new_id("prn"), self._clock.now())
            except Conflict:
                # A concurrent fresh login already rebound the subject; converge on it.
                principal = self._store.principal_for_binding(identity.issuer, identity.subject)
                if principal is None or principal.deleted_at is not None:
                    raise Unauthenticated("binding_unavailable") from None
        self._check_live(principal, identity.auth_time)
        return principal

    def create_guest(self) -> tuple[Principal, str]:
        now = self._clock.now()
        policy = self._guest_admission
        if not self._store.admit_guest(now, policy):
            elapsed = now.timestamp() % policy.window_seconds
            raise RateLimited("guest_admission_limited", retry_after_s=max(1.0, policy.window_seconds - elapsed))
        token = GUEST_PREFIX + secrets.token_urlsafe(32)
        principal = self._store.create_guest(self._ids.new_id("prn"), capability_hash(token), now + GUEST_TTL, now)
        return principal, token

    def authenticate_guest(self, token: str) -> Principal:
        principal = self._store.guest_by_capability(capability_hash(token))
        if principal is None or principal.transferred_to is not None:
            raise Unauthenticated("guest_capability_invalid")
        if principal.guest_expires_at is not None and self._clock.now() >= principal.guest_expires_at:
            raise Unauthenticated("guest_capability_expired")
        self._check_live(principal, None)
        return principal

    def _check_live(self, principal: Principal, auth_time: datetime | None) -> None:
        if principal.deleted_at is not None:
            raise Unauthenticated("account_deleted")
        # Guests carry no auth_time, so any revocation ends the capability.
        if principal.revoked_before is not None:
            if auth_time is None or auth_time <= principal.revoked_before:
                raise Unauthenticated("session_revoked")

    # --- lifecycle -----------------------------------------------------------
    def transfer_guest(self, account: Principal, guest_token: str) -> str:
        if account.kind != "ACCOUNT":
            raise Unauthenticated("account_required")
        if not guest_token.startswith(GUEST_PREFIX):
            raise Unauthenticated("guest_capability_invalid")
        return self._store.transfer_guest(capability_hash(guest_token), account.principal_id, self._clock.now())

    def logout_everywhere(self, principal: Principal, ctx: CallContext) -> None:
        self._store.revoke_sessions(principal.principal_id, self._clock.now())

    def delete_account(self, principal: Principal, ctx: CallContext) -> None:
        """Revoke access immediately and record deletion; data erasure and
        provider-account deletion run from the outbox (T24)."""
        self._store.mark_deleted(principal.principal_id, self._clock.now())


@dataclass
class InMemoryIdentityStore:
    """Reference store for unit tests; PostgreSQL is the production store."""

    principals: dict[str, Principal] = field(default_factory=dict)
    binding_index: dict[tuple[str, str], str] = field(default_factory=dict)
    guest_index: dict[str, str] = field(default_factory=dict)
    owned: dict[str, str] = field(default_factory=dict)  # object id -> owner principal (for transfer tests)
    outbox: list[tuple[str, str]] = field(default_factory=list)
    admissions: dict[int, int] = field(default_factory=dict)

    def admit_guest(self, at: datetime, policy: GuestAdmission) -> bool:
        window = int(at.timestamp()) // policy.window_seconds
        if self.admissions.get(window, 0) >= policy.limit:
            return False
        self.admissions[window] = self.admissions.get(window, 0) + 1
        return True

    def principal(self, principal_id: str) -> Principal | None:
        return self.principals.get(principal_id)

    def principal_for_binding(self, issuer: str, subject: str) -> Principal | None:
        pid = self.binding_index.get((issuer, subject))
        return self.principals.get(pid) if pid else None

    def create_account(self, principal_id: str, issuer: str, subject: str, at: datetime) -> Principal:
        if (issuer, subject) in self.binding_index:
            raise Conflict("binding_exists")
        principal = Principal(principal_id, "ACCOUNT", at)
        self.principals[principal_id] = principal
        self.binding_index[(issuer, subject)] = principal_id
        return principal

    def create_guest(self, principal_id: str, token_hash: str, expires_at: datetime, at: datetime) -> Principal:
        principal = Principal(principal_id, "GUEST", at, guest_expires_at=expires_at)
        self.principals[principal_id] = principal
        self.guest_index[token_hash] = principal_id
        return principal

    def guest_by_capability(self, token_hash: str) -> Principal | None:
        pid = self.guest_index.get(token_hash)
        return self.principals.get(pid) if pid else None

    def transfer_guest(self, token_hash: str, account_id: str, at: datetime) -> str:
        guest_id = self.guest_index.get(token_hash)
        guest = self.principals.get(guest_id) if guest_id else None
        account = self.principals.get(account_id)
        if guest is None or account is None or account.kind != "ACCOUNT" or account.deleted_at is not None:
            raise NotFound("guest_or_account_not_found")
        if guest.transferred_to is not None:
            raise Conflict("guest_already_transferred")
        if guest.guest_expires_at is not None and at >= guest.guest_expires_at:
            raise Conflict("guest_capability_expired")
        if guest.revoked_before is not None or guest.deleted_at is not None:
            raise Conflict("guest_not_transferable")  # logout-everywhere ends the capability
        for obj, owner in list(self.owned.items()):
            if owner == guest.principal_id:
                self.owned[obj] = account_id
        self.principals[guest.principal_id] = replace(guest, transferred_to=account_id)
        del self.guest_index[token_hash]
        return guest.principal_id

    def revoke_sessions(self, principal_id: str, at: datetime) -> None:
        self.principals[principal_id] = replace(self.principals[principal_id], revoked_before=at)
        self.outbox.append(("sessions.revoked", principal_id))

    def mark_deleted(self, principal_id: str, at: datetime) -> None:
        self.principals[principal_id] = replace(self.principals[principal_id], deleted_at=at, revoked_before=at)
        self.outbox.append(("account.deletion_requested", principal_id))

    def rebind_after_deletion(self, issuer: str, subject: str, new_principal_id: str, at: datetime) -> Principal:
        old = self.principal_for_binding(issuer, subject)
        if old is None or old.deleted_at is None:
            raise Conflict("binding_not_tombstoned")
        # Credentials authenticated before the deletion stay revoked on the new principal.
        principal = Principal(new_principal_id, "ACCOUNT", at, revoked_before=old.deleted_at)
        self.principals[new_principal_id] = principal
        self.binding_index[(issuer, subject)] = new_principal_id
        return principal

    def bindings(self, principal_id: str) -> list[tuple[str, str]]:
        return sorted(k for k, v in self.binding_index.items() if v == principal_id)
