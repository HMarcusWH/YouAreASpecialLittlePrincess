"""PostgreSQL export records and export job queue (T21).

API-side calls (``request``, ``get``, ``revoke``) run in the owner's context.
Worker-side calls (``claim``, ``publish``, ``fail``) need a ``princess_worker``
login for the job table and switch to the owner's context for owner rows.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...application.exports import MAX_ATTEMPTS, TEMPLATE_VERSION, ClaimedExport, ExportRow
from ...ports.base import NotFound, RateLimited
from ...ports.storage import StoredObject
from .stores import Database, lock_live_owner, queue_asset_erasure, set_context

EXPORT_KIND = "export"
MAX_PENDING_EXPORTS = 5

_SELECT = ("SELECT e.export_id, e.owner_id, e.report_id, e.revision, e.layout, e.params, e.cache_key, e.state, "
           "e.created_at, e.asset_id, e.media_type, e.size_bytes, e.sha256, a.version_ref, e.error_code, "
           "e.completed_at FROM app.report_export e LEFT JOIN app.asset a ON a.asset_id = e.asset_id ")


def _row(r: Mapping[str, Any] | None) -> ExportRow | None:
    if r is None:
        return None
    return ExportRow(export_id=r["export_id"], owner_id=r["owner_id"], report_id=r["report_id"],
                     revision=r["revision"], layout=r["layout"], sections=tuple(r["params"]["sections"]),
                     cache_key=r["cache_key"], state=r["state"], created_at=r["created_at"], asset_id=r["asset_id"],
                     media_type=r["media_type"], size_bytes=r["size_bytes"], sha256=r["sha256"],
                     version_ref=r["version_ref"], error_code=r["error_code"], completed_at=r["completed_at"])


def _enqueue(conn: Connection, owner_id: str, export_id: str, job_id: str, at: datetime) -> None:
    conn.execute(text("INSERT INTO app.job (job_id, kind, owner_id, subject_ref, state, dedupe_key, created_at, "
                      "updated_at) VALUES (:j, :k, :o, :e, 'QUEUED', :d, :t, :t)"),
                 {"j": job_id, "k": EXPORT_KIND, "o": owner_id, "e": export_id, "d": f"export:{job_id}", "t": at})


class PostgresExportRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- API side ---------------------------------------------------------------
    def request(self, row: ExportRow, job_id: str) -> ExportRow:
        owner = row.owner_id
        with self.db.session(owner) as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"export:{owner}"})
            existing = _row(conn.execute(text(_SELECT + "WHERE e.cache_key = :k"),
                                         {"k": row.cache_key}).mappings().first())
            if existing is not None and existing.state in ("QUEUED", "READY"):
                return existing
            pending = conn.execute(text("SELECT count(*) FROM app.report_export WHERE state = 'QUEUED'")).scalar()
            if pending >= MAX_PENDING_EXPORTS:
                raise RateLimited("too_many_pending_exports", retry_after_s=30)
            if existing is not None:  # FAILED or REVOKED: try again under the same identity
                conn.execute(text("UPDATE app.report_export SET state = 'QUEUED', error_code = NULL, asset_id = NULL, "
                                  "media_type = NULL, size_bytes = NULL, sha256 = NULL, completed_at = NULL "
                                  "WHERE export_id = :e"), {"e": existing.export_id})
                _enqueue(conn, owner, existing.export_id, job_id, row.created_at)
                export_id = existing.export_id
            else:
                conn.execute(text(
                    "INSERT INTO app.report_export (export_id, owner_id, report_id, revision, projection, layout, "
                    "params, template_version, cache_key, state, created_at) VALUES (:e, :o, :r, :v, :p, :l, "
                    "CAST(:params AS jsonb), :tv, :k, 'QUEUED', :t)"),
                    {"e": row.export_id, "o": owner, "r": row.report_id, "v": row.revision,
                     "p": row.request().projection, "l": row.layout, "params": json.dumps(row.request().params()),
                     "tv": TEMPLATE_VERSION, "k": row.cache_key, "t": row.created_at})
                _enqueue(conn, owner, row.export_id, job_id, row.created_at)
                export_id = row.export_id
            return _row(conn.execute(text(_SELECT + "WHERE e.export_id = :e"), {"e": export_id}).mappings().first())

    def get(self, owner_id: str, export_id: str) -> ExportRow | None:
        with self.db.session(owner_id) as conn:
            return _row(conn.execute(text(_SELECT + "WHERE e.export_id = :e"), {"e": export_id}).mappings().first())

    def revoke(self, owner_id: str, export_id: str, reason: str, at: datetime) -> None:
        with self.db.session(owner_id) as conn:
            asset_id = conn.execute(text("UPDATE app.report_export SET state = 'REVOKED', error_code = :c "
                                         "WHERE export_id = :e AND state = 'READY' RETURNING asset_id"),
                                    {"c": reason, "e": export_id}).scalar()
            if asset_id is not None:
                queue_asset_erasure(conn, owner_id, asset_id, at)

    # --- worker side --------------------------------------------------------------
    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> ClaimedExport | None:
        with self.db.session() as conn:
            exhausted = conn.execute(text(
                "UPDATE app.job SET state = 'FAILED', lease_owner = NULL, lease_expires_at = NULL, "
                "last_error = 'attempts_exhausted', updated_at = :now WHERE kind = :k AND state = 'LEASED' "
                "AND lease_expires_at < :now AND attempts >= :max RETURNING owner_id, subject_ref"),
                {"now": now, "k": EXPORT_KIND, "max": MAX_ATTEMPTS}).all()
            for owner_id, export_id in exhausted:
                set_context(conn, owner_id)
                conn.execute(text("UPDATE app.report_export SET state = 'FAILED', error_code = 'attempts_exhausted' "
                                  "WHERE export_id = :e AND state = 'QUEUED'"), {"e": export_id})
            set_context(conn, None)
            job = conn.execute(text(
                "UPDATE app.job SET state = 'LEASED', lease_owner = :w, lease_expires_at = :exp, "
                "fencing_token = fencing_token + 1, attempts = attempts + 1, updated_at = :now "
                "WHERE job_id = (SELECT job_id FROM app.job WHERE kind = :k AND attempts < :max AND "
                "(state = 'QUEUED' OR (state = 'LEASED' AND lease_expires_at < :now)) ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING job_id, owner_id, subject_ref, fencing_token, attempts"),
                {"w": worker_id, "exp": now + timedelta(seconds=lease_seconds), "now": now, "k": EXPORT_KIND,
                 "max": MAX_ATTEMPTS}).mappings().first()
            if job is None:
                return None
            set_context(conn, job["owner_id"])
            row = _row(conn.execute(text(_SELECT + "WHERE e.export_id = :e"),
                                    {"e": job["subject_ref"]}).mappings().first())
            if row is None or row.state != "QUEUED":
                set_context(conn, None)  # revoked or deleted meanwhile: nothing to render
                conn.execute(text("UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, "
                                  "lease_expires_at = NULL, last_error = 'export_not_queued', updated_at = :now "
                                  "WHERE job_id = :j"), {"now": now, "j": job["job_id"]})
                return None
        return ClaimedExport(job["job_id"], int(job["fencing_token"]), int(job["attempts"]), row)

    def _leased(self, conn: Connection, claim: ClaimedExport, now: datetime) -> bool:
        current = conn.execute(text("SELECT state, fencing_token, lease_expires_at FROM app.job WHERE job_id = :j "
                                    "FOR UPDATE"), {"j": claim.job_id}).first()
        return (current is not None and current[0] == "LEASED" and current[1] == claim.fencing_token
                and current[2] > now)

    def publish(self, claim: ClaimedExport, stored: StoredObject, now: datetime) -> bool:
        row = claim.row
        with self.db.session() as conn:
            if not self._leased(conn, claim, now):
                return False
            set_context(conn, row.owner_id)
            try:
                lock_live_owner(conn, row.owner_id)
            except NotFound:
                return False
            if conn.execute(text("SELECT 1 FROM app.report WHERE report_id = :r AND deleted_at IS NULL FOR UPDATE"),
                            {"r": row.report_id}).scalar() is None:
                return False
            if conn.execute(text("SELECT 1 FROM app.report_export WHERE export_id = :e AND state = 'QUEUED' "
                                 "FOR UPDATE"), {"e": row.export_id}).scalar() is None:
                return False
            conn.execute(text("INSERT INTO app.asset (asset_id, owner_id, kind, sha256, media_type, size_bytes, "
                              "version_ref, created_at) VALUES (:a, :o, 'EXPORT', :h, :m, :n, :v, :t)"),
                         {"a": stored.asset_id, "o": row.owner_id, "h": stored.sha256, "m": stored.media_type,
                          "n": stored.size_bytes, "v": stored.version_ref, "t": now})
            conn.execute(text("UPDATE app.report_export SET state = 'READY', asset_id = :a, media_type = :m, "
                              "size_bytes = :n, sha256 = :h, completed_at = :t, error_code = NULL "
                              "WHERE export_id = :e"),
                         {"a": stored.asset_id, "m": stored.media_type, "n": stored.size_bytes, "h": stored.sha256,
                          "t": now, "e": row.export_id})
            set_context(conn, None)
            conn.execute(text("UPDATE app.job SET state = 'SUCCEEDED', lease_owner = NULL, lease_expires_at = NULL, "
                              "last_error = NULL, updated_at = :t WHERE job_id = :j"), {"t": now, "j": claim.job_id})
        return True

    def fail(self, claim: ClaimedExport, code: str, now: datetime, *, retry: bool,
             orphan_asset_id: str | None = None) -> str:
        row = claim.row
        with self.db.session() as conn:
            leased = self._leased(conn, claim, now)
            state = ("QUEUED" if retry else "FAILED") if leased else "FENCED"
            if leased:
                conn.execute(text("UPDATE app.job SET state = :s, lease_owner = NULL, lease_expires_at = NULL, "
                                  "last_error = :c, updated_at = :t WHERE job_id = :j"),
                             {"s": state, "c": code, "t": now, "j": claim.job_id})
            set_context(conn, row.owner_id)
            if leased and not retry:
                conn.execute(text("UPDATE app.report_export SET state = 'FAILED', error_code = :c "
                                  "WHERE export_id = :e AND state = 'QUEUED'"), {"c": code, "e": row.export_id})
            if orphan_asset_id is not None:
                queue_asset_erasure(conn, row.owner_id, orphan_asset_id, now)
        return state


__all__ = ["EXPORT_KIND", "MAX_PENDING_EXPORTS", "PostgresExportRepository"]
