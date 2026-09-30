"""PostgreSQL adapter for the fixed T24 operational aggregate functions."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ...application.operations import OperationalObservation
from ...ports.base import TransientUnavailable
from .stores import Database


class PostgresOperationalRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def observations(self, now: datetime) -> tuple[OperationalObservation, ...]:
        try:
            with self.db.session() as conn:
                rows = conn.execute(text(
                    "SELECT source, category, state, item_count, oldest_age_s, max_attempts "
                    "FROM app.operational_snapshot(:now)"
                ), {"now": now}).mappings().all()
            return tuple(OperationalObservation(
                source=str(row["source"]),
                category=str(row["category"]),
                state=str(row["state"]),
                count=int(row["item_count"]),
                oldest_age_s=int(row["oldest_age_s"]) if row["oldest_age_s"] is not None else None,
                max_attempts=int(row["max_attempts"]) if row["max_attempts"] is not None else None,
            ) for row in rows)
        except SQLAlchemyError:
            raise TransientUnavailable("operational_snapshot_unavailable") from None

    def schema_revision(self) -> str:
        try:
            with self.db.session() as conn:
                value = conn.execute(text("SELECT app.operational_schema_revision()")).scalar_one()
            return str(value)
        except SQLAlchemyError:
            raise TransientUnavailable("operational_snapshot_unavailable") from None


__all__ = ["PostgresOperationalRepository"]
