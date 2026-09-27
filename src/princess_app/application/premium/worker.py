"""Leased Premium job loop: claim, one bounded attempt, settle (T15 + T19)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ...ports.base import Clock
from .service import AttemptRecord, PremiumJob, PremiumRunner


class PremiumJobQueue(Protocol):
    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> PremiumJob | None: ...

    def finish(self, job: PremiumJob, record: AttemptRecord, now: datetime) -> str:
        """Requeue a bounded retry, or fail the job and release its reservation."""
        ...

    def reap(self, now: datetime) -> int:
        """Fail jobs whose final attempt lost its lease; release their credits."""
        ...


@dataclass(frozen=True)
class PremiumWorkOutcome:
    job_id: str
    record: AttemptRecord
    job_state: str


class PremiumWorker:
    def __init__(self, *, queue: PremiumJobQueue, runner: PremiumRunner, clock: Clock, worker_id: str,
                 lease_seconds: int = 180) -> None:
        self._queue = queue
        self._runner = runner
        self._clock = clock
        self._worker_id = worker_id
        self._lease = lease_seconds

    def run_once(self) -> PremiumWorkOutcome | None:
        self._queue.reap(self._clock.now())
        job = self._queue.claim(self._worker_id, self._lease, self._clock.now())
        if job is None:
            return None
        record = self._runner.run(job)
        return PremiumWorkOutcome(job.job_id, record, self._queue.finish(job, record, self._clock.now()))


__all__ = ["PremiumJobQueue", "PremiumWorkOutcome", "PremiumWorker"]
