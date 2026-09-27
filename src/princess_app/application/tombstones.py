"""Deletion tombstones that survive a database restore (T24).

A backup restored after a deletion would bring the deleted account or capture
back. Every deletion is therefore also written to an append-only tombstone
log kept outside the database (never restored with it). After a restore,
before serving traffic, ``replay`` re-applies each tombstone the restored
database does not reflect; the normal erasure worker then erases again, which
is idempotent for bytes that are already gone.

Writers: the API right after it commits a deletion (fast path, best effort)
and the erasure worker before it processes the deletion event (durable path:
the event stays pending until the tombstone is written). Entries hold opaque
IDs and times only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

from ..ports.base import InvalidInput, NotFound, require_opaque_id
from .identity import IdentityStore
from .intake import IntakeRepository

ACCOUNT_DELETED = "ACCOUNT_DELETED"
CAPTURE_DELETED = "CAPTURE_DELETED"
KINDS = frozenset({ACCOUNT_DELETED, CAPTURE_DELETED})


@dataclass(frozen=True)
class Tombstone:
    kind: str
    owner_id: str
    ref: str  # the principal for an account, the capture for a capture
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise InvalidInput("unknown_tombstone_kind")
        require_opaque_id(self.owner_id, "owner_id")
        require_opaque_id(self.ref, "ref")


class TombstoneLog(Protocol):
    def append(self, tombstone: Tombstone) -> None:
        """Durably append (flushed to stable storage before returning)."""
        ...

    def entries(self) -> Iterable[Tombstone]: ...


@dataclass(frozen=True)
class ReplayResult:
    reapplied: int  # the restored database had forgotten this deletion
    already: int    # the restored database already reflects it
    unknown: int    # the subject is not in the restored database at all


def replay(log: TombstoneLog, identities: IdentityStore, captures: IntakeRepository) -> ReplayResult:
    """Re-apply deletions a restore has undone. Idempotent; run it before the
    restored environment serves traffic, then let the erasure worker run."""
    reapplied = already = unknown = 0
    seen: set[tuple[str, str, str]] = set()
    for t in log.entries():
        key = (t.kind, t.owner_id, t.ref)
        if key in seen:
            continue
        seen.add(key)
        if t.kind == ACCOUNT_DELETED:
            principal = identities.principal(t.owner_id)
            if principal is None:
                unknown += 1
            elif principal.deleted_at is not None:
                already += 1
            else:
                identities.mark_deleted(t.owner_id, t.recorded_at)  # re-queues account erasure
                reapplied += 1
        else:
            capture = captures.capture(t.owner_id, t.ref)
            if capture is None:
                unknown += 1
            elif capture.deleted:
                already += 1
            else:
                try:
                    captures.delete_capture(t.owner_id, t.ref, t.recorded_at)  # re-queues byte erasure
                except NotFound:
                    unknown += 1
                    continue
                reapplied += 1
    return ReplayResult(reapplied, already, unknown)


__all__ = ["ACCOUNT_DELETED", "CAPTURE_DELETED", "ReplayResult", "Tombstone", "TombstoneLog", "replay"]
