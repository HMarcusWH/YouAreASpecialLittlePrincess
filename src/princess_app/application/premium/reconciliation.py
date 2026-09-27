"""Fail-safe reconciliation of open Premium work after a database restore.

Run before Premium workers resume. Deterministic attempt IDs let a capable
provider prove whether work existed outside the restored database. A remote
execution is never regenerated automatically: the restored job fails and its
credit is released, preserving Free and preventing duplicate model execution.
Providers without authoritative lookup also fail restored work closed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from ...ports import model as port
from ...ports.base import CallContext, Clock, PortError, Unsupported
from .packet import NotApplicable
from .service import (
    AttemptJournal,
    Fenced,
    MAX_ATTEMPTS,
    PremiumJob,
    PremiumRunner,
    ProviderAttemptState,
)


class RestoreQueue(Protocol):
    def pending_restore(self, now, limit: int = 100) -> list[PremiumJob]: ...

    def fail_restored(self, job: PremiumJob, reason: str, now) -> bool: ...


@dataclass(frozen=True)
class RestoreReconciliation:
    checked: int = 0
    safe_to_resume: int = 0
    remote_execution_found: int = 0
    failed_closed: int = 0


class PremiumRestoreReconciler:
    def __init__(self, *, queue: RestoreQueue, runner: PremiumRunner, model: port.PremiumModelProvider,
                 attempts: AttemptJournal, clock: Clock, context: Callable[[], CallContext]) -> None:
        self._queue = queue
        self._runner = runner
        self._model = model
        self._attempts = attempts
        self._clock = clock
        self._context = context

    def run(self, limit: int = 100) -> RestoreReconciliation:
        checked = safe = found = failed = 0
        for job in self._queue.pending_restore(self._clock.now(), limit):
            checked += 1
            if port.ATTEMPT_LOOKUP not in self._model.profile.capabilities:
                self._queue.fail_restored(job, "restore_lookup_unsupported", self._clock.now())
                failed += 1
                continue

            remote = False
            unresolved = False
            for attempt_number in range(1, MAX_ATTEMPTS + 1):
                probe = replace(job, attempt_number=attempt_number)
                try:
                    request = self._runner.reconciliation_request(probe, attempt_number)
                    result = self._model.lookup_attempt(request, self._context())
                except (Fenced, NotApplicable, Unsupported, PortError):
                    unresolved = True
                    break
                if result is None:
                    continue
                # Recreate the sanitized attempt row if the restored backup
                # predates it. Output/private packet content is not persisted.
                self._attempts.start_attempt(probe, request, self._clock.now())
                self._attempts.finish_attempt(
                    request.attempt_id, ProviderAttemptState(result.state.value),
                    None, result, self._clock.now(),
                )
                remote = True
                break

            if remote:
                self._queue.fail_restored(job, "restored_provider_attempt_detected", self._clock.now())
                found += 1
            elif unresolved:
                self._queue.fail_restored(job, "restore_lookup_unresolved", self._clock.now())
                failed += 1
            else:
                safe += 1
        return RestoreReconciliation(checked, safe, found, failed)


__all__ = ["PremiumRestoreReconciler", "RestoreQueue", "RestoreReconciliation"]
