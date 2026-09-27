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
from ..permissions import PermissionService
from ..reports import ReportStore
from .service import PURPOSE, Fenced, PremiumJob, PremiumOverlay


@dataclass
class InMemorySpendBudget:
    """Token budget: reserves the worst case, settles to reported usage."""

    limit_tokens: int
    reserved: dict[str, int] = field(default_factory=dict)
    spent: int = 0

    def reserve(self, attempt_id: str, max_output_tokens: int) -> bool:
        if self.spent + sum(self.reserved.values()) + max_output_tokens > self.limit_tokens:
            return False
        self.reserved[attempt_id] = max_output_tokens
        return True

    def settle(self, attempt_id: str, usage: port.ProviderUsage | None) -> None:
        self.reserved.pop(attempt_id, None)
        if usage is not None:
            self.spent += (usage.input_tokens or 0) + (usage.output_tokens or 0)


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


__all__ = ["InMemoryOverlayPublisher", "InMemorySpendBudget"]
