"""Recording and checking purpose-specific permissions at use time (T02).

The store keeps an append-only event history plus a per-(subject, purpose)
*epoch* that increases on every deny/withdraw. Work that starts under a
permission captures the epoch; publication calls :meth:`PermissionService.
still_valid` (the PostgreSQL store does this under a row lock) so a
withdrawal recorded meanwhile blocks publication.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from ..domain.permissions import (
    Decision,
    PermissionEvent,
    Scope,
    current_version,
    evaluate,
    require_covering_notice,
)
from ..ports.base import Clock, Conflict, IdGenerator, NotAuthorized, require_opaque_id


@dataclass(frozen=True)
class PermissionCheck:
    allowed: bool
    reason: str
    epoch: int


class PermissionStore(Protocol):
    def append(self, event: PermissionEvent) -> PermissionEvent: ...

    def events(self, subject_id: str, purpose_id: str) -> list[PermissionEvent]: ...

    def epoch(self, subject_id: str, purpose_id: str) -> int: ...


class PermissionService:
    def __init__(self, store: PermissionStore, clock: Clock, ids: IdGenerator, *,
                 allow_draft_policy: bool = False) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._allow_draft = allow_draft_policy

    @property
    def allows_draft_policy(self) -> bool:
        """Whether grants under unapproved (DRAFT) notices count here (synthetic data only)."""
        return self._allow_draft

    def record(self, *, subject_id: str, actor_id: str, purpose_id: str, scope: Scope, decision: Decision,
               notice_version: str, effective_at: datetime | None = None,
               request_id: str | None = None) -> PermissionEvent:
        """Append one decision. With ``request_id`` the event ID is derived from
        (subject, request), so a replayed request returns the recorded event
        and can never land after, and override, a newer decision."""
        now = self._clock.now()
        version = current_version(purpose_id)
        if decision is Decision.GRANT:
            require_covering_notice(notice_version, purpose_id, version)
        event = PermissionEvent(
            event_id=self._ids.new_id("perm") if request_id is None else _request_event_id(subject_id, request_id),
            subject_id=subject_id, purpose_id=purpose_id,
            purpose_version=version, scope=scope, decision=decision, recorded_at=now,
            effective_at=effective_at or now, actor_id=actor_id, notice_version=notice_version)
        return self._store.append(event)

    def history(self, subject_id: str, purpose_id: str) -> list[PermissionEvent]:
        return self._store.events(subject_id, purpose_id)

    def check(self, subject_id: str, purpose_id: str, scope: Scope, at: datetime | None = None) -> PermissionCheck:
        epoch = self._store.epoch(subject_id, purpose_id)
        result = evaluate(self._store.events(subject_id, purpose_id), subject_id=subject_id,
                          purpose_id=purpose_id, scope=scope, at=at or self._clock.now(),
                          allow_draft_policy=self._allow_draft)
        return PermissionCheck(result.allowed, result.reason, epoch)

    def require(self, subject_id: str, purpose_id: str, scope: Scope) -> int:
        check = self.check(subject_id, purpose_id, scope)
        if not check.allowed:
            raise NotAuthorized("permission_not_granted", detail=f"{purpose_id}:{check.reason}")
        return check.epoch

    def still_valid(self, subject_id: str, purpose_id: str, scope: Scope, epoch: int) -> bool:
        """Advisory pre-check only. Durable publication must re-check the epoch
        inside its own transaction under the epoch row lock (see
        ``PostgresJobQueue.publish``); this boolean cannot fence a later commit."""
        check = self.check(subject_id, purpose_id, scope)
        return check.allowed and check.epoch == epoch


def _request_event_id(subject_id: str, request_id: str) -> str:
    require_opaque_id(request_id, "request_id")
    return "perm_" + hashlib.sha256(f"{subject_id}\0{request_id}".encode()).hexdigest()[:40]


def replayed(existing: PermissionEvent, candidate: PermissionEvent) -> PermissionEvent:
    """A replay must repeat the same decision; a reused request ID for another one is refused."""
    same = (existing.subject_id, existing.purpose_id, existing.scope, existing.decision, existing.notice_version) == \
        (candidate.subject_id, candidate.purpose_id, candidate.scope, candidate.decision, candidate.notice_version)
    if not same:
        raise Conflict("request_id_reused")
    return existing


@dataclass
class InMemoryPermissionStore:
    history: list[PermissionEvent] = field(default_factory=list)
    epochs: dict[tuple[str, str], int] = field(default_factory=dict)

    def append(self, event: PermissionEvent) -> PermissionEvent:
        for existing in self.history:
            if existing.event_id == event.event_id:
                return replayed(existing, event)
        stored = replace(event, sequence=len(self.history) + 1)
        self.history.append(stored)
        if event.decision is not Decision.GRANT:
            key = (event.subject_id, event.purpose_id)
            self.epochs[key] = self.epochs.get(key, 0) + 1
        return stored

    def events(self, subject_id: str, purpose_id: str) -> list[PermissionEvent]:
        return [e for e in self.history if e.subject_id == subject_id and e.purpose_id == purpose_id]

    def epoch(self, subject_id: str, purpose_id: str) -> int:
        return self.epochs.get((subject_id, purpose_id), 0)
