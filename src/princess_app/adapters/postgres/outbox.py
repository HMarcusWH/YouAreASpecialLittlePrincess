"""Worker-side outbox reads for the erasure/retention consumer (T04).

Connect as a ``princess_worker`` member: the worker outbox policy exposes all
pending events; asset and capture rows are read and updated in the event
owner's principal context.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from ...application.erasure import RETENTION_REVIEW, CaptureAsset, OutboxEvent
from ...application.intake import ANALYSIS_KIND
from .stores import Database


class PostgresErasureOutbox:
    def __init__(self, db: Database) -> None:
        self.db = db

    def pending(self, topics: tuple[str, ...], limit: int) -> list[OutboxEvent]:
        """Explicit erasure first; then retention reviews whose capture has no
        active analysis. A review that must still wait is never fetched, so a
        backlog of waiting reviews cannot starve deletions or other reviews."""
        urgent = [t for t in topics if t != RETENTION_REVIEW]
        with self.db.session() as conn:
            rows = list(conn.execute(text(
                "SELECT event_id, topic, owner_id, aggregate_ref, payload FROM app.outbox_event "
                "WHERE dispatched_at IS NULL AND topic = ANY(:t) ORDER BY created_at LIMIT :n"),
                {"t": urgent, "n": limit}).mappings().all())
            if RETENTION_REVIEW in topics and len(rows) < limit:
                rows += conn.execute(text(
                    "SELECT o.event_id, o.topic, o.owner_id, o.aggregate_ref, o.payload FROM app.outbox_event o "
                    "WHERE o.dispatched_at IS NULL AND o.topic = :t AND NOT EXISTS (SELECT 1 FROM app.job j "
                    "WHERE j.kind = :k AND j.state IN ('QUEUED', 'LEASED') AND j.payload->>'capture_id' = "
                    "o.aggregate_ref) ORDER BY o.created_at LIMIT :n"),
                    {"t": RETENTION_REVIEW, "k": ANALYSIS_KIND, "n": limit - len(rows)}).mappings().all()
        return [OutboxEvent(r["event_id"], r["topic"], r["owner_id"], r["aggregate_ref"], r["payload"] or {})
                for r in rows]

    def capture_asset(self, owner_id: str, capture_id: str) -> CaptureAsset | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text(
                "SELECT c.asset_id, (c.deleted_at IS NOT NULL) AS capture_deleted, (a.deleted_at IS NOT NULL) AS erased, "
                "(SELECT count(*) FROM app.job j JOIN app.analysis_run r ON r.run_id = j.subject_ref "
                " WHERE r.capture_id = c.capture_id AND j.kind = :k AND j.state IN ('QUEUED', 'LEASED')) AS active "
                "FROM app.capture c JOIN app.asset a ON a.asset_id = c.asset_id WHERE c.capture_id = :c"),
                {"c": capture_id, "k": ANALYSIS_KIND}).mappings().first()
        if row is None:
            return None
        return CaptureAsset(row["asset_id"], row["capture_deleted"], row["erased"], int(row["active"]))

    def mark_erased(self, owner_id: str, asset_id: str, at: datetime) -> None:
        with self.db.session(owner_id) as conn:
            conn.execute(text("UPDATE app.asset SET deleted_at = coalesce(deleted_at, :t) WHERE asset_id = :a"),
                         {"a": asset_id, "t": at})

    def unerased_assets(self, owner_id: str) -> list[str]:
        with self.db.session(owner_id) as conn:
            return list(conn.execute(text("SELECT asset_id FROM app.asset WHERE deleted_at IS NULL "
                                          "ORDER BY created_at, asset_id")).scalars())

    def erase_account_records(self, owner_id: str, at: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(text("SELECT app.erase_deleted_account(:o, :t)"), {"o": owner_id, "t": at})

    def erase_capture_records(self, owner_id: str, capture_id: str, at: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(text("SELECT app.erase_capture_records(:o, :c, :t)"),
                         {"o": owner_id, "c": capture_id, "t": at})

    def expire_upload_slots(self, now: datetime, limit: int) -> int:
        with self.db.session() as conn:
            return int(conn.execute(text("SELECT app.expire_upload_slots(:t, :n)"), {"t": now, "n": limit}).scalar())

    def dispatched(self, event_id: str, at: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(text("UPDATE app.outbox_event SET dispatched_at = :t WHERE event_id = :e "
                              "AND dispatched_at IS NULL"), {"t": at, "e": event_id})


__all__ = ["PostgresErasureOutbox"]
