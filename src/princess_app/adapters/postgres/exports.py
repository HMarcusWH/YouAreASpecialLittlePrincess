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

from ...application.exports import (
    MAX_ATTEMPTS, TEMPLATE_VERSION, V3_FONT_IDENTITY, V3_TEMPLATE_VERSION,
    ClaimedExport, ExportRow, render_asset_id,
)
from ...ports.base import InvalidInput, NotFound, RateLimited
from ...ports.storage import StoredObject
from .stores import Database, epoch_for, lock_live_owner, queue_asset_erasure, set_context

EXPORT_KIND = "export"
MAX_PENDING_EXPORTS = 5
MAX_EXPORTS_PER_DAY = 20  # renders an owner may start per rolling day, completed ones included

_SELECT = ("SELECT e.export_id, e.owner_id, e.report_id, e.revision, e.layout, e.params, e.cache_key, e.state, "
           "e.created_at, e.asset_id, e.media_type, e.size_bytes, e.sha256, a.version_ref, e.error_code, "
           "e.completed_at, e.template_version FROM app.report_export e "
           "LEFT JOIN app.asset a ON a.asset_id = e.asset_id ")


def _row(r: Mapping[str, Any] | None) -> ExportRow | None:
    if r is None:
        return None
    params = r["params"]
    template = r["template_version"]
    if template not in (TEMPLATE_VERSION, V3_TEMPLATE_VERSION) or not isinstance(params, dict):
        raise InvalidInput("export_stored_template_invalid")
    if (not isinstance(params.get("sections"), list)
            or type(params.get("include_image")) is not bool):
        raise InvalidInput("export_stored_params_invalid")
    detail = "FULL"
    image = False
    report_digest = raster_sha = evidence_digest = None
    retention_epoch = None
    if template == V3_TEMPLATE_VERSION:
        detail = params.get("detail")
        image = params["include_image"]
        report_digest = params.get("source_report_digest")
        raster_sha = params.get("raster_sha256")
        evidence_digest = params.get("evidence_digest")
        retention_epoch = params.get("image_retention_epoch")
        if (detail not in ("SUMMARY", "FULL") or params.get("font_identity") != V3_FONT_IDENTITY
                or params.get("render_policy_version") != "render-policy/3"
                or not isinstance(report_digest, str) or len(report_digest) != 64
                or (image and (not isinstance(raster_sha, str) or len(raster_sha) != 64))
                or (not image and raster_sha is not None)
                or (image and (type(retention_epoch) is not int or retention_epoch < 0))
                or (not image and retention_epoch is not None)
                or (evidence_digest is not None and
                    (not isinstance(evidence_digest, str) or len(evidence_digest) != 64))
                or r["layout"] not in ("A4", "LETTER") or params["sections"]
                or params.get("share_grant_ref") is not None):
            raise InvalidInput("export_stored_params_invalid")
    return ExportRow(
        export_id=r["export_id"], owner_id=r["owner_id"], report_id=r["report_id"],
        revision=r["revision"], layout=r["layout"], sections=tuple(params["sections"]),
        share_grant_ref=params.get("share_grant_ref"),
        cache_key=r["cache_key"], state=r["state"], created_at=r["created_at"], asset_id=r["asset_id"],
        media_type=r["media_type"], size_bytes=r["size_bytes"], sha256=r["sha256"],
        version_ref=r["version_ref"], error_code=r["error_code"], completed_at=r["completed_at"],
        renderer_version=template, detail=detail, include_image=image,
        source_report_digest=report_digest, raster_sha256=raster_sha,
        evidence_digest=evidence_digest, image_retention_epoch=retention_epoch,
    )


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
            # Completed renders count too: a finished batch does not free the budget.
            started = conn.execute(text("SELECT count(*) FROM app.job WHERE kind = :k AND created_at > :since"),
                                   {"k": EXPORT_KIND, "since": row.created_at - timedelta(days=1)}).scalar()
            if started >= MAX_EXPORTS_PER_DAY:
                raise RateLimited("export_daily_limit", retry_after_s=3600)
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
                     "tv": row.renderer_version, "k": row.cache_key, "t": row.created_at})
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
                "AND lease_expires_at < :now AND attempts >= :max RETURNING owner_id, subject_ref, fencing_token"),
                {"now": now, "k": EXPORT_KIND, "max": MAX_ATTEMPTS}).all()
            for owner_id, export_id, token in exhausted:
                set_context(conn, owner_id)
                conn.execute(text("UPDATE app.report_export SET state = 'FAILED', error_code = 'attempts_exhausted' "
                                  "WHERE export_id = :e AND state = 'QUEUED'"), {"e": export_id})
                # The last attempt died mid-render: whatever it wrote is erased.
                queue_asset_erasure(conn, owner_id, render_asset_id(export_id, token), now)
            set_context(conn, None)
            candidate = conn.execute(text(
                "SELECT job_id, owner_id, subject_ref, state, fencing_token FROM app.job WHERE kind = :k "
                "AND attempts < :max AND (state = 'QUEUED' OR (state = 'LEASED' AND lease_expires_at < :now)) "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"),
                {"k": EXPORT_KIND, "max": MAX_ATTEMPTS, "now": now}).mappings().first()
            if candidate is None:
                return None
            if candidate["state"] == "LEASED":
                # A worker died after (perhaps) writing bytes it never recorded:
                # its attempt's asset ID is derivable, so erasure is queued now.
                set_context(conn, candidate["owner_id"])
                queue_asset_erasure(conn, candidate["owner_id"],
                                    render_asset_id(candidate["subject_ref"], candidate["fencing_token"]), now)
                set_context(conn, None)
            job = conn.execute(text(
                "UPDATE app.job SET state = 'LEASED', lease_owner = :w, lease_expires_at = :exp, "
                "fencing_token = fencing_token + 1, attempts = attempts + 1, updated_at = :now WHERE job_id = :j "
                "RETURNING job_id, owner_id, subject_ref, fencing_token, attempts"),
                {"w": worker_id, "exp": now + timedelta(seconds=lease_seconds), "now": now,
                 "j": candidate["job_id"]}).mappings().first()
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
            if row.renderer_version == V3_TEMPLATE_VERSION:
                # Same transaction as the artifact grant: parent row is FOR
                # UPDATE and serializes appending/deleting saved revisions.
                latest = conn.execute(text(
                    "SELECT rr.revision, rr.document->>'document_digest' AS digest, "
                    "rr.document#>>'{analysis,input_asset_id}' AS source_id, "
                    "rr.document#>>'{analysis,input_sha256}' AS source_sha "
                    "FROM app.report_revision rr WHERE rr.report_id = :r "
                    "ORDER BY rr.revision DESC LIMIT 1"),
                    {"r": row.report_id}).mappings().first()
                if (latest is None or latest["revision"] != row.revision
                        or latest["digest"] != row.source_report_digest):
                    return False
                if row.include_image:
                    # A subject-wide withdrawal increments the epoch under
                    # the same row this transaction share-locks. Revocation
                    # before publication is refused, and one that starts
                    # concurrently cannot commit until this publication does.
                    if (type(row.image_retention_epoch) is not int
                            or epoch_for(conn, row.owner_id, "image_retention", lock=True)
                            != row.image_retention_epoch):
                        return False
                    # The original asset/capture cannot be deleted, relinked
                    # or replaced during publication. Only current owner
                    # source bytes authorized by the saved report are usable.
                    active = conn.execute(text(
                        "SELECT 1 FROM app.asset a "
                        "JOIN app.capture c ON c.asset_id = a.asset_id "
                        "WHERE a.asset_id = :a AND a.owner_id = :o AND "
                        "a.deleted_at IS NULL AND a.kind = 'ORIGINAL' "
                        "AND a.sha256 = :h AND c.owner_id = :o "
                        "AND c.deleted_at IS NULL AND c.sha256 = :h LIMIT 1 FOR SHARE OF a,c"),
                        {"a": latest["source_id"], "o": row.owner_id,
                         "h": latest["source_sha"]}).scalar()
                    if active is None:
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
