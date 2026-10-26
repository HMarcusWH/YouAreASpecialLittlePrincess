"""Live read-time state for saved report snapshots (T09 over T04/T19).

A snapshot is immutable, but whether its source image still exists and
whether its Premium overlay may still be served change afterwards: the
original can be erased, and a payload is erased when third-party AI
processing is withdrawn. Both are resolved here, in the owner's context, on
every read.
"""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import text

from princess_contracts import ValidatedDocument

from ...application.reports import ReportAccess
from ...domain.reports import PremiumAccess, PremiumAuthorization
from ...domain.reports.suitability import STORY_TEMPLATE_VERSION
from .stores import Database


class PostgresReportAccess:
    def __init__(self, db: Database) -> None:
        self.db = db

    def resolve(self, owner_id: str, report: ValidatedDocument) -> ReportAccess:
        data = report.data
        overlay_id = data["premium_overlay_id"]
        is_story = data["analysis"]["versions"]["template"] == STORY_TEMPLATE_VERSION
        with self.db.session(owner_id) as conn:
            if is_story:
                # A report's saved measurements survive original-image
                # erasure, but the image capability must bind to a *current*
                # retained original and a non-deleted matching capture.
                # Absence, an unexpected asset kind, or changed source bytes
                # all fail closed. Keep the historical /1–/3 predicate intact.
                image = conn.execute(text(
                    "SELECT a.deleted_at IS NULL AND a.kind = 'ORIGINAL' "
                    "AND a.sha256 = :h AND EXISTS ("
                    "SELECT 1 FROM app.capture c WHERE c.asset_id = a.asset_id "
                    "AND c.owner_id = :owner AND c.deleted_at IS NULL AND c.sha256 = :h) "
                    "FROM app.asset a WHERE a.asset_id = :a AND a.owner_id = :owner"),
                    {"a": data["analysis"]["input_asset_id"],
                     "owner": owner_id, "h": data["analysis"]["input_sha256"]}).scalar()
            else:
                image = conn.execute(text(
                    "SELECT a.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM app.capture c "
                    "WHERE c.asset_id = a.asset_id AND c.deleted_at IS NOT NULL) "
                    "FROM app.asset a WHERE a.asset_id = :a"),
                    {"a": data["analysis"]["input_asset_id"]}).scalar()
            erased = conn.execute(text("SELECT erased_at IS NOT NULL FROM app.premium_overlay "
                                       "WHERE overlay_id = :o AND report_id = :r"),
                                  {"o": overlay_id, "r": data["report_id"]}).scalar() if overlay_id else None
        premium = None
        if overlay_id is not None and erased is not None:
            premium = PremiumAuthorization(data["report_id"], overlay_id,
                                           PremiumAccess.REVOKED if erased else PremiumAccess.UNLOCKED)
        return ReportAccess(source_image_available=bool(image), premium=premium)

    def premium_content(self, owner_id: str, overlay_id: str) -> Mapping[str, Any] | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text("SELECT output, omissions FROM app.premium_overlay WHERE overlay_id = :o "
                                    "AND erased_at IS NULL"), {"o": overlay_id}).first()
        if row is None:
            return None
        output, omissions = row
        return {"answers": output["answers"], "soft_fields": output["soft_fields"], "omissions": omissions}


__all__ = ["PostgresReportAccess"]
