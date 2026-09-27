"""Recording and checking purpose-specific permissions at use time (T02).

The store keeps an append-only event history plus a per-(subject, purpose)
*epoch* that increases on every deny/withdraw. Work that starts under a
permission captures the epoch; publication calls :meth:`PermissionService.
still_valid` (the PostgreSQL store does this under a row lock) so a
withdrawal recorded meanwhile blocks publication.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from ..domain.permissions import Decision, PermissionEvent, Scope, current_version, evaluate
from ..ports.base import Clock, IdGenerator, NotAuthorized


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
    def __init__(self, store: PermissionStore, clock: Clock, ids: IdGenerator) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def record(self, *, subject_id: str, actor_id: str, purpose_id: str, scope: Scope, decision: Decision,
               notice_version: str, effective_at: datetime | None = None) -> PermissionEvent:
        now = self._clock.now()
        event = PermissionEvent(
            event_id=self._ids.new_id("perm"), subject_id=subject_id, purpose_id=purpose_id,
            purpose_version=current_version(purpose_id), scope=scope, decision=decision, recorded_at=now,
            effective_at=effective_at or now, actor_id=actor_id, notice_version=notice_version)
        return self._store.append(event)

    def check(self, subject_id: str, purpose_id: str, scope: Scope, at: datetime | None = None) -> PermissionCheck:
        epoch = self._store.epoch(subject_id, purpose_id)
        result = evaluate(self._store.events(subject_id, purpose_id), subject_id=subject_id,
                          purpose_id=purpose_id, scope=scope, at=at or self._clock.now())
        return PermissionCheck(result.allowed, result.reason, epoch)

    def require(self, subject_id: str, purpose_id: str, scope: Scope) -> int:
        check = self.check(subject_id, purpose_id, scope)
        if not check.allowed:
            raise NotAuthorized("permission_not_granted", detail=f"{purpose_id}:{check.reason}")
        return check.epoch

    def still_valid(self, subject_id: str, purpose_id: str, scope: Scope, epoch: int) -> bool:
        check = self.check(subject_id, purpose_id, scope)
        return check.allowed and check.epoch == epoch


@dataclass
class InMemoryPermissionStore:
    history: list[PermissionEvent] = field(default_factory=list)
    epochs: dict[tuple[str, str], int] = field(default_factory=dict)

    def append(self, event: PermissionEvent) -> PermissionEvent:
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
