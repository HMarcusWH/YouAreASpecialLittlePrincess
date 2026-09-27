"""Report publication and read use cases over a storage seam (T09).

``InMemoryReportStore`` is the fixture-backed seam used until the T02
PostgreSQL repository exists; both honour ``check_revision``. Reads compose
the stored snapshot with an authorization-filtered projection. No model,
provider or renderer is reachable from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from princess_contracts import ValidatedDocument

from ..domain.reports import PremiumAuthorization, ProjectionRequest, check_revision, project_report
from ..ports.base import Clock, Conflict, InvalidInput, NotAuthorized, NotFound, PermanentFailure


class ReportStore(Protocol):
    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None: ...

    def append(self, owner_id: str, report: ValidatedDocument) -> None: ...


@dataclass
class InMemoryReportStore:
    _revisions: dict[str, list[ValidatedDocument]] = field(default_factory=dict)
    _owners: dict[str, str] = field(default_factory=dict)

    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None:
        revisions = self._revisions.get(report_id)
        return (self._owners[report_id], revisions[-1]) if revisions else None

    def append(self, owner_id: str, report: ValidatedDocument) -> None:
        if report.schema_name != "ReportDocument":
            raise InvalidInput("not_a_report")
        data = report.data
        if data["analysis"]["owner_id"] != owner_id:
            raise NotAuthorized("owner_mismatch")
        existing = self._revisions.get(data["report_id"])
        if existing is None:
            if data["revision"] != 1:
                raise Conflict("first_revision_must_be_1")
            self._revisions[data["report_id"]] = [report]
            self._owners[data["report_id"]] = owner_id
            return
        if self._owners[data["report_id"]] != owner_id:
            raise NotAuthorized("owner_mismatch")
        if check_revision(existing[-1], report):
            raise Conflict("invalid_revision")
        existing.append(report)


@dataclass(frozen=True)
class ShareAccess:
    """A verified, unexpired share grant resolved by the sharing use case (T22)."""

    report_id: str
    scope: frozenset[str]
    revoked: bool = False


class ReportReader:
    def __init__(self, store: ReportStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def view(self, *, report_id: str, principal_id: str | None, projection: str,
             premium: PremiumAuthorization | None = None, share: ShareAccess | None = None,
             source_image_available: bool = True, include_source_image: bool = True,
             actions: Mapping[str, str | None] | None = None) -> ValidatedDocument:
        entry = self._store.latest(report_id)
        if entry is None:
            raise NotFound("report_not_found")
        owner_id, report = entry
        if projection == "SHARE":
            if share is None or share.revoked or share.report_id != report_id:
                raise NotFound("report_not_found")
            scope = share.scope
        elif principal_id is None or principal_id != owner_id:
            raise NotFound("report_not_found")  # never reveal another owner's report exists
        else:
            scope = frozenset()
        result = project_report(report, ProjectionRequest(
            projection=projection, generated_at=self._clock.now(), premium=premium,
            source_image_available=source_image_available, include_source_image=include_source_image,
            share_scope=scope, actions=dict(actions or {})))
        if result.value is None:
            codes = {issue.code for issue in result.issues}
            if "PREMIUM_NOT_AUTHORIZED" in codes:
                raise NotAuthorized("premium_not_authorized")
            raise PermanentFailure("projection_invalid", detail=",".join(sorted(codes))[:120])
        return result.value
