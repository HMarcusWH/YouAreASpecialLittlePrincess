"""Report publication and read use cases over a storage seam (T09).

``InMemoryReportStore`` is the fixture-backed seam used until the T02
PostgreSQL repository exists; both honour ``check_revision``. Reads compose
the stored snapshot with an authorization-filtered projection. No model,
provider or renderer is reachable from here.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from princess_contracts import ValidatedDocument

from ..domain.reports import PremiumAuthorization, ProjectionRequest, check_revision, project_report
from ..ports.base import Clock, Conflict, InvalidInput, NotAuthorized, NotFound, PermanentFailure


@dataclass(frozen=True)
class ReportHistoryEntry:
    report_id: str
    revision: int
    kind: str
    created_at: datetime
    locale: str


def encode_report_cursor(created_at: datetime, report_id: str) -> str:
    stamp = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = f"{stamp}\n{report_id}".encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_report_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    if not cursor or len(cursor) > 512:
        raise InvalidInput("invalid_report_cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        stamp, report_id = raw.split("\n", 1)
        created_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise InvalidInput("invalid_report_cursor") from None
    if created_at.tzinfo is None or not report_id:
        raise InvalidInput("invalid_report_cursor")
    return created_at, report_id


class ReportStore(Protocol):
    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None: ...

    def append(self, owner_id: str, report: ValidatedDocument) -> None: ...

    def history(self, owner_id: str, *, limit: int,
                before: tuple[datetime, str] | None) -> list[ReportHistoryEntry]: ...

    def evidence(self, report_id: str) -> ValidatedDocument | None: ...


@dataclass
class InMemoryReportStore:
    _revisions: dict[str, list[ValidatedDocument]] = field(default_factory=dict)
    _owners: dict[str, str] = field(default_factory=dict)
    _evidence: dict[str, ValidatedDocument] = field(default_factory=dict)

    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None:
        revisions = self._revisions.get(report_id)
        return (self._owners[report_id], revisions[-1]) if revisions else None

    def append(self, owner_id: str, report: ValidatedDocument) -> None:
        if report.schema_name != "ReportDocument":
            raise InvalidInput("not_a_report")
        data = report.data
        existing = self._revisions.get(data["report_id"])
        if existing is None:
            if data["analysis"]["owner_id"] != owner_id:
                raise NotAuthorized("owner_mismatch")
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

    def history(self, owner_id: str, *, limit: int,
                before: tuple[datetime, str] | None) -> list[ReportHistoryEntry]:
        rows = []
        for report_id, revisions in self._revisions.items():
            if self._owners.get(report_id) != owner_id or not revisions:
                continue
            latest = revisions[-1].data
            created_at = datetime.fromisoformat(str(revisions[0].data["created_at"]).replace("Z", "+00:00"))
            if before is not None and (created_at, report_id) >= before:
                continue
            rows.append(ReportHistoryEntry(
                report_id, int(latest["revision"]), str(latest["kind"]), created_at,
                str(latest["locale"])))
        rows.sort(key=lambda row: (row.created_at, row.report_id), reverse=True)
        return rows[:limit]

    def evidence(self, report_id: str) -> ValidatedDocument | None:
        return self._evidence.get(report_id)

    def bind_evidence(self, report_id: str, evidence: ValidatedDocument) -> None:
        if evidence.schema_name != "EvidenceBundle":
            raise InvalidInput("not_evidence")
        self._evidence[report_id] = evidence


@dataclass(frozen=True)
class ShareAccess:
    """A verified, unexpired share grant resolved by the sharing use case (T22)."""

    report_id: str
    scope: frozenset[str]
    revoked: bool = False


@dataclass(frozen=True)
class ReportAccess:
    """Live state a saved snapshot cannot carry, resolved on every read."""

    source_image_available: bool = True
    premium: PremiumAuthorization | None = None


class ReportAccessResolver(Protocol):
    def resolve(self, owner_id: str, report: ValidatedDocument) -> ReportAccess:
        """Whether the source image still exists, and the saved overlay's access."""
        ...

    def premium_content(self, owner_id: str, overlay_id: str) -> Mapping[str, Any] | None:
        """The validated overlay output and omissions, or None once erased."""
        ...


class ReportReader:
    def __init__(self, store: ReportStore, clock: Clock, access: ReportAccessResolver | None = None) -> None:
        self._store = store
        self._clock = clock
        self._access = access

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
        if self._access is not None:
            resolved = self._access.resolve(owner_id, report)
            source_image_available = source_image_available and resolved.source_image_available
            premium = premium if premium is not None else resolved.premium
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

    def history(self, *, principal_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise InvalidInput("invalid_report_page_size")
        before = decode_report_cursor(cursor)
        rows = self._store.history(principal_id, limit=limit + 1, before=before)
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            tail = page_rows[-1]
            next_cursor = encode_report_cursor(tail.created_at, tail.report_id)
        return {
            "contract_version": "1.0.0",
            "items": [{
                "report_id": row.report_id,
                "revision": row.revision,
                "kind": row.kind,
                "created_at": row.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "locale": row.locale,
            } for row in page_rows],
            "next_cursor": next_cursor,
        }

    def evidence(self, *, report_id: str, principal_id: str) -> dict[str, Any]:
        entry = self._store.latest(report_id)
        if entry is None or entry[0] != principal_id:
            raise NotFound("report_not_found")
        report = entry[1]
        expected_bundle = report.data["evidence_bundle_id"]
        if expected_bundle is None:
            raise NotFound("evidence_not_available")
        evidence = self._store.evidence(report_id)
        if evidence is None:
            raise NotFound("evidence_not_available")
        data = evidence.data
        # Immutable snapshots keep the original analysis owner after a guest
        # transfer. Authorization is the live relational owner above; lineage
        # is therefore bound by IDs/digests that remain immutable.
        if (
            data["bundle_id"] != expected_bundle
            or data["analysis"]["run_id"] != report.data["analysis"]["run_id"]
            or data["analysis"]["analysis_id"] != report.data["analysis"]["analysis_id"]
            or data["analysis"]["input_sha256"] != report.data["analysis"]["input_sha256"]
            or data["analysis"]["processed_sha256"] != report.data["analysis"]["processed_sha256"]
        ):
            raise PermanentFailure("evidence_lineage_invalid")
        return evidence.to_dict()

    def premium_content(self, *, report_id: str, principal_id: str) -> dict[str, Any]:
        """The purchased overlay for the owner's latest revision. Served only
        while the overlay is unlocked; an erased or revoked payload is gone."""
        view = self.view(report_id=report_id, principal_id=principal_id, projection="PREMIUM")
        entry = self._store.latest(report_id)
        overlay_id = entry[1].data["premium_overlay_id"] if entry else None
        content = self._access.premium_content(principal_id, overlay_id) if self._access and overlay_id else None
        if content is None:
            raise NotFound("premium_not_available")
        return {"report_id": report_id, "revision": view.data["source_revision"], "overlay_id": overlay_id,
                "evidence_class": "AI_SYNTHESIS", **content}
