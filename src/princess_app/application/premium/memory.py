"""In-memory budget and publisher for tests and local composition.

The durable publisher (T19) performs the same checks inside one database
transaction under the permission-epoch and principal row locks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ...domain.permissions import Scope
from ...domain.reports import revise_report
from ...ports import model as port
from ...ports.base import InvalidInput
from ..permissions import PermissionService
from ..reports import ReportStore
from .service import PURPOSE, Fenced, PremiumJob, PremiumOverlay, ProviderAttemptState


@dataclass
class InMemorySpendBudget:
    """Token budget: reserves the worst case, settles to reported usage."""

    limit_tokens: int
    reserved: dict[str, int] = field(default_factory=dict)
    spent: int = 0

    def reserve(self, attempt_id: str, max_billable_tokens: int) -> bool:
        if self.spent + sum(self.reserved.values()) + max_billable_tokens > self.limit_tokens:
            return False
        self.reserved[attempt_id] = max_billable_tokens
        return True

    def settle(self, attempt_id: str, usage: port.ProviderUsage | None) -> None:
        self.reserved.pop(attempt_id, None)
        if usage is not None:
            self.spent += (usage.input_tokens or 0) + (usage.output_tokens or 0)


@dataclass
class InMemoryAttemptJournal:
    """Sanitized provider-attempt journal for tests and local composition."""

    rows: dict[str, dict] = field(default_factory=dict)
    fail_start: bool = False

    def start_attempt(self, job: PremiumJob, request: port.GenerationRequest, at: datetime) -> None:
        if self.fail_start:
            raise RuntimeError("attempt_journal_unavailable")
        expected = {
            "attempt_id": request.attempt_id, "job_id": job.job_id,
            "attempt_number": job.attempt_number, "packet_digest": request.packet_digest,
            "policy_version": request.policy_version, "state": ProviderAttemptState.STARTED.value,
            "created_at": at,
        }
        prior = self.rows.get(request.attempt_id)
        if prior is not None:
            keys = ("job_id", "attempt_number", "packet_digest", "policy_version")
            if any(prior[k] != expected[k] for k in keys):
                raise InvalidInput("provider_attempt_mismatch")
            return
        self.rows[request.attempt_id] = expected

    def finish_attempt(self, attempt_id: str, state: ProviderAttemptState, error_code: str | None,
                       result: port.ProviderGenerationResult | None, at: datetime) -> None:
        row = self.rows[attempt_id]
        row.update({
            "state": state.value, "error_code": error_code,
            "provider_request_id": result.provider_request_id if result else None,
            "model_requested": result.model_requested if result else None,
            "model_returned": result.model_returned if result else None,
            "usage_input_tokens": result.usage.input_tokens if result else None,
            "usage_output_tokens": result.usage.output_tokens if result else None,
            "completed_at": at,
        })

@dataclass
class InMemoryOverlayPublisher:
    reports: Callable[[str], ReportStore]
    permissions: PermissionService
    owner_deleted: Callable[[str], bool] = lambda owner_id: False
    overlays: dict[str, PremiumOverlay] = field(default_factory=dict)

    def publish(self, job: PremiumJob, overlay: PremiumOverlay, now: datetime) -> int:
        if self.owner_deleted(job.owner_id):
            raise Fenced("owner_deleted")
        if not self.permissions.still_valid(job.owner_id, PURPOSE, Scope("REPORT", job.report_id),
                                            job.permission_epoch):
            raise Fenced("permission_changed")
        store = self.reports(job.owner_id)
        latest = store.latest(job.report_id)
        if latest is None or latest[1].data["revision"] != job.report_revision:
            raise Fenced("report_revised")
        revised = revise_report(latest[1], created_at=now, premium_overlay_id=overlay.overlay_id)
        if revised.value is None:
            raise Fenced("revision_rejected")
        store.append(job.owner_id, revised.value)
        self.overlays[overlay.overlay_id] = overlay
        return revised.value.data["revision"]


__all__ = ["InMemoryAttemptJournal", "InMemoryOverlayPublisher", "InMemorySpendBudget"]
