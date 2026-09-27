"""Deletion, withdrawal and revocation tombstones that survive a database restore (T24).

A backup restored after a deletion would bring the deleted account or capture
back. The same holds for a withdrawn permission, which would be granted again,
and for "log out everywhere", whose sessions would be valid again. Each such
change is therefore also written to an append-only tombstone log kept outside
the database, which is never restored with it. After a restore, before the
environment serves traffic, ``replay`` re-applies each tombstone the restored
database does not reflect. The normal workers then erase again (idempotent for
bytes that are already gone) and propagate the withdrawals again.

Writers: the API right after it commits a change (fast path, best effort),
and the erasure worker before it processes the change's outbox event. That
durable path holds the event pending until the tombstone is written.
Deletions also tombstone the guests merged into the account, because a
backup from before the merge still holds the guest's copy. Entries hold
opaque IDs, purpose/scope codes and times only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

from ..domain.permissions import Decision, Scope
from ..ports.base import InvalidInput, NotFound, require_opaque_id
from .identity import IdentityStore
from .intake import IntakeRepository
from .permissions import PermissionService

ACCOUNT_DELETED = "ACCOUNT_DELETED"
CAPTURE_DELETED = "CAPTURE_DELETED"
PERMISSION_WITHDRAWN = "PERMISSION_WITHDRAWN"  # ref: the withdrawing permission event
SESSIONS_REVOKED = "SESSIONS_REVOKED"  # ref: the principal; "log out everywhere"
KINDS = frozenset({ACCOUNT_DELETED, CAPTURE_DELETED, PERMISSION_WITHDRAWN, SESSIONS_REVOKED})


@dataclass(frozen=True)
class Tombstone:
    kind: str
    owner_id: str
    ref: str  # the principal, capture or permission event
    recorded_at: datetime
    # PERMISSION_WITHDRAWN only: what was withdrawn, and under which notice.
    purpose_id: str | None = None
    scope_kind: str | None = None
    scope_ref: str | None = None
    notice_version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise InvalidInput("unknown_tombstone_kind")
        require_opaque_id(self.owner_id, "owner_id")
        require_opaque_id(self.ref, "ref")
        permission = (self.purpose_id, self.scope_kind, self.notice_version)
        if self.kind == PERMISSION_WITHDRAWN:
            for name, value in zip(("purpose_id", "scope_kind", "notice_version"), permission):
                require_opaque_id(value, name)
            if self.scope_ref is not None:
                require_opaque_id(self.scope_ref, "scope_ref")
        elif any(v is not None for v in (*permission, self.scope_ref)):
            raise InvalidInput("unexpected_permission_fields")

    def to_json(self) -> dict:
        data = {"kind": self.kind, "owner_id": self.owner_id, "ref": self.ref,
                "recorded_at": self.recorded_at.isoformat()}
        for name in ("purpose_id", "scope_kind", "scope_ref", "notice_version"):
            if getattr(self, name) is not None:
                data[name] = getattr(self, name)
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Tombstone":
        return cls(data["kind"], data["owner_id"], data["ref"], datetime.fromisoformat(data["recorded_at"]),
                   data.get("purpose_id"), data.get("scope_kind"), data.get("scope_ref"), data.get("notice_version"))


@dataclass(frozen=True)
class LogContents:
    tombstones: tuple[Tombstone, ...]
    unreadable: int  # complete lines that do not parse: investigate before trusting the replay


class TombstoneLog(Protocol):
    def append(self, tombstone: Tombstone) -> None:
        """Durably append (flushed to stable storage before returning)."""
        ...

    def read(self) -> LogContents: ...


class DeviceBindings(Protocol):
    def forget_devices(self, owner_id: str, registered_before: datetime | None = None) -> int: ...


@dataclass(frozen=True)
class ReplayResult:
    reapplied: int  # the restored database had lost this change
    already: int    # the restored database already reflects it (or something newer)
    unknown: int    # the subject is not in the restored database at all
    unreadable: int = 0


def replay(log: TombstoneLog, identities: IdentityStore, captures: IntakeRepository,
           permissions: PermissionService, devices: DeviceBindings | None = None) -> ReplayResult:
    """Re-apply the changes a restore has undone. Idempotent. Run it before the
    restored environment serves traffic, then let the erasure worker run."""
    counts = {"reapplied": 0, "already": 0, "unknown": 0}
    contents = log.read()
    seen: set[tuple] = set()
    for t in contents.tombstones:
        key = (t.kind, t.owner_id, t.ref) + ((t.recorded_at,) if t.kind == SESSIONS_REVOKED else ())
        if key in seen:
            continue
        seen.add(key)
        counts[_replay_one(t, identities, captures, permissions, devices)] += 1
    return ReplayResult(counts["reapplied"], counts["already"], counts["unknown"], contents.unreadable)


def _replay_one(t: Tombstone, identities: IdentityStore, captures: IntakeRepository,
                permissions: PermissionService, devices: DeviceBindings | None) -> str:
    if t.kind == CAPTURE_DELETED:
        capture = captures.capture(t.owner_id, t.ref)
        if capture is None:
            return "unknown"
        if capture.deleted:
            return "already"
        try:
            captures.delete_capture(t.owner_id, t.ref, t.recorded_at)  # re-queues byte erasure
        except NotFound:
            return "unknown"
        return "reapplied"
    principal = identities.principal(t.owner_id)
    if principal is None:
        return "unknown"
    if principal.deleted_at is not None:
        return "already"  # deletion supersedes withdrawals and revocations
    if t.kind == ACCOUNT_DELETED:
        if principal.transferred_to is not None:
            return "already"  # a merged guest: its data lives with the account
        identities.mark_deleted(t.owner_id, t.recorded_at)  # re-queues account erasure
        return "reapplied"
    if t.kind == SESSIONS_REVOKED:
        if principal.revoked_before is not None and principal.revoked_before >= t.recorded_at:
            return "already"
        identities.revoke_sessions(t.owner_id, t.recorded_at)
        if devices is not None:
            devices.forget_devices(t.owner_id, registered_before=t.recorded_at)
        return "reapplied"
    # PERMISSION_WITHDRAWN: a decision at or after the withdrawal (the
    # withdrawal itself, or a later grant) means the restored ledger already
    # covers it; re-withdrawing would undo a newer choice.
    purpose = str(t.purpose_id)
    scope = Scope(str(t.scope_kind), t.scope_ref)
    if any(e.recorded_at >= t.recorded_at for e in permissions.history(t.owner_id, purpose)):
        return "already"
    if not permissions.check(t.owner_id, purpose, scope).allowed:
        return "already"
    permissions.record(subject_id=t.owner_id, actor_id=t.owner_id, purpose_id=purpose, scope=scope,
                       decision=Decision.WITHDRAW, notice_version=str(t.notice_version),
                       request_id=f"restore.{t.ref}")  # idempotent across repeated replays
    return "reapplied"


def merged_expansion(kind: str, owner_id: str, ref: str, at: datetime, guests: Iterable[str]) -> list[Tombstone]:
    """A deletion's tombstones, plus one per guest merged into the account:
    a backup from before the merge holds that data under the guest's ID."""
    tombstones = [Tombstone(kind, owner_id, ref, at)]
    for guest in guests:
        tombstones.append(Tombstone(kind, guest, guest if kind == ACCOUNT_DELETED else ref, at))
    return tombstones


__all__ = ["ACCOUNT_DELETED", "CAPTURE_DELETED", "DeviceBindings", "LogContents", "PERMISSION_WITHDRAWN",
           "ReplayResult", "SESSIONS_REVOKED", "Tombstone", "TombstoneLog", "merged_expansion", "replay"]
