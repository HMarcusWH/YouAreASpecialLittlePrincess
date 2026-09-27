"""Report feedback use cases (T24).

Submission is authenticated, owner- and report-bound and idempotent per
client ``request_id``. Rows expire after a retention period that is a draft
until the owner approves it, go with their report (and so with capture or
account erasure), and can be withdrawn by their author at any time.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from ...domain.feedback import (
    CONTRACT_VERSION,
    MAX_PER_REPORT,
    FeedbackSubmission,
    check_submission,
    screen_comment,
)
from ...ports.base import Clock, NotFound
from ..reports import ReportStore

DRAFT_RETENTION = timedelta(days=180)  # pending the owner's retention decision


@dataclass(frozen=True)
class FeedbackRecord:
    feedback_id: str
    owner_id: str
    report_id: str
    revision: int
    category: str
    target_kind: str
    target_ref: str | None
    comment: str | None
    created_at: datetime
    expires_at: datetime
    contract_version: str = CONTRACT_VERSION


class FeedbackRepository(Protocol):
    def submit(self, record: FeedbackRecord, max_per_report: int) -> FeedbackRecord:
        """Insert, or return the stored record for the same ``feedback_id``.
        ``Conflict`` if that ID was used for different feedback;
        ``RateLimited`` when the report already has ``max_per_report`` items."""
        ...

    def delete(self, owner_id: str, feedback_id: str, at: datetime) -> bool: ...

    def forget_feedback(self, owner_id: str, feedback_id: str, created_before: datetime) -> bool: ...


def feedback_id(owner_id: str, request_id: str) -> str:
    return "fb_" + hashlib.sha256(f"{owner_id}\0{request_id}".encode()).hexdigest()[:40]


class FeedbackService:
    def __init__(self, *, reports: Callable[[str], ReportStore], repo: FeedbackRepository, clock: Clock,
                 retention: timedelta = DRAFT_RETENTION) -> None:
        self._reports = reports
        self._repo = repo
        self._clock = clock
        self._retention = retention

    def submit(self, owner_id: str, submission: FeedbackSubmission) -> FeedbackRecord:
        latest = self._reports(owner_id).latest(submission.report_id)
        if latest is None or latest[0] != owner_id:
            raise NotFound("report_not_found")  # never reveal another owner's report
        report = latest[1].data
        check_submission(submission, report)
        now = self._clock.now()
        record = FeedbackRecord(
            feedback_id=feedback_id(owner_id, submission.request_id), owner_id=owner_id,
            report_id=submission.report_id, revision=report["revision"], category=submission.category,
            target_kind=submission.target_kind, target_ref=submission.target_ref,
            comment=screen_comment(submission.comment), created_at=now, expires_at=now + self._retention)
        return self._repo.submit(record, MAX_PER_REPORT)

    def withdraw(self, owner_id: str, feedback_id: str) -> datetime:
        at = self._clock.now()
        if not self._repo.delete(owner_id, feedback_id, at):
            raise NotFound("feedback_not_found")
        return at

    def forget_feedback(self, owner_id: str, feedback_id: str, created_before: datetime) -> bool:
        """Restore replay removes only feedback that existed at withdrawal time."""
        return self._repo.forget_feedback(owner_id, feedback_id, created_before)


__all__ = ["DRAFT_RETENTION", "FeedbackRecord", "FeedbackRepository", "FeedbackService", "feedback_id"]
