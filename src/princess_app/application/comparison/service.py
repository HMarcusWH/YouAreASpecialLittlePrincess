"""Application orchestration for deterministic comparisons (T18).

This layer authorizes saved report inputs and delegates comparison semantics to
the pure domain builder. No HTTP route, persistence schema, renderer or partner
permission implementation lives here.
"""
from __future__ import annotations

from typing import Protocol, Sequence

from princess_contracts import ValidatedDocument

from ...domain.comparison import build_comparison
from ...ports.base import Clock, InvalidInput, NotFound, PermanentFailure, require_opaque_id


class ComparisonReportSource(Protocol):
    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None: ...


class PartnerComparisonAccess(Protocol):
    """T22 supplies an implementation for separately granted partner inputs."""

    def allowed(self, *, principal_id: str, owner_id: str, report_id: str) -> bool: ...


class ComparisonService:
    def __init__(self, reports: ComparisonReportSource, clock: Clock,
                 partner_access: PartnerComparisonAccess | None = None) -> None:
        self._reports = reports
        self._clock = clock
        self._partner_access = partner_access

    def create(self, *, comparison_id: str, principal_id: str, report_ids: Sequence[str],
               kind: str) -> ValidatedDocument:
        require_opaque_id(comparison_id, "comparison_id")
        require_opaque_id(principal_id, "principal_id")
        if kind == "PAIR" and len(report_ids) != 2:
            raise InvalidInput("pair_requires_two_reports")
        if kind == "HISTORY" and not 2 <= len(report_ids) <= 16:
            raise InvalidInput("history_requires_2_to_16_reports")
        if kind not in {"PAIR", "HISTORY"}:
            raise InvalidInput("unknown_comparison_kind")
        if len(set(report_ids)) != len(report_ids):
            raise InvalidInput("duplicate_comparison_input")

        reports: list[ValidatedDocument] = []
        for report_id in report_ids:
            require_opaque_id(report_id, "report_id")
            entry = self._reports.latest(report_id)
            if entry is None:
                raise NotFound("report_not_found")
            owner_id, report = entry
            if owner_id != principal_id:
                allowed = self._partner_access is not None and self._partner_access.allowed(
                    principal_id=principal_id, owner_id=owner_id, report_id=report_id
                )
                if not allowed:
                    raise NotFound("report_not_found")
            reports.append(report)

        outcome = build_comparison(comparison_id=comparison_id, kind=kind, reports=reports,
                                   created_at=self._clock.now())
        if outcome.value is None:
            codes = ".".join(sorted({issue.code for issue in outcome.issues}))
            raise PermanentFailure("comparison_invalid", detail=codes[:64] or None)
        return outcome.value
