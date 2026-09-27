"""PostgreSQL report feedback (T24), in the owner's RLS context."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from ...application.feedback import FeedbackRecord
from ...ports.base import Conflict, RateLimited
from .stores import Database

_COLUMNS = ("feedback_id, owner_id, report_id, revision, category, target_kind, target_ref, comment, created_at, "
            "expires_at, contract_version")
_SAME = ("report_id", "category", "target_kind", "target_ref", "comment")


class PostgresFeedbackRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def submit(self, record: FeedbackRecord, max_per_report: int) -> FeedbackRecord:
        with self.db.session(record.owner_id) as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                         {"k": f"feedback:{record.owner_id}:{record.report_id}"})
            existing = conn.execute(text(f"SELECT {_COLUMNS} FROM app.report_feedback WHERE feedback_id = :f"),
                                    {"f": record.feedback_id}).mappings().first()
            if existing is not None:
                stored = FeedbackRecord(**dict(existing))
                if any(getattr(stored, k) != getattr(record, k) for k in _SAME):
                    raise Conflict("request_id_reused")
                return stored  # a retried submission converges
            count = conn.execute(text("SELECT count(*) FROM app.report_feedback WHERE report_id = :r"),
                                 {"r": record.report_id}).scalar()
            if count >= max_per_report:
                raise RateLimited("feedback_limit_reached")
            conn.execute(text(f"INSERT INTO app.report_feedback ({_COLUMNS}) VALUES (:feedback_id, :owner_id, "
                              ":report_id, :revision, :category, :target_kind, :target_ref, :comment, :created_at, "
                              ":expires_at, :contract_version)"), record.__dict__)
        return record

    def delete(self, owner_id: str, feedback_id: str) -> bool:
        with self.db.session(owner_id) as conn:
            return conn.execute(text("DELETE FROM app.report_feedback WHERE feedback_id = :f"),
                                {"f": feedback_id}).rowcount == 1

    def expire(self, now: datetime, limit: int = 500) -> int:
        with self.db.session() as conn:
            return int(conn.execute(text("SELECT app.expire_feedback(:t, :n)"), {"t": now, "n": limit}).scalar())


__all__ = ["PostgresFeedbackRepository"]
