"""PostgreSQL intake repository and fenced analysis job queue (T04).

The API uses :class:`PostgresIntakeRepository` with a ``princess_app`` login.
Workers use :class:`PostgresJobQueue` with a ``princess_worker`` login: it may
claim any job, then acts in the job owner's principal context. Claims take a
short lease and increment a fencing token; publication re-checks the token,
lease, cancellation, capture deletion and permission epoch under locks.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from princess_contracts import ValidatedDocument
from princess_contracts import generated as g

from ...application.analysis_worker import MAX_ATTEMPTS, ClaimedJob, Fenced
from ...application.intake import (
    ANALYSIS_CONFIG_SHA256,
    ANALYSIS_KIND,
    SERVICE_PURPOSE,
    CaptureRow,
    RunStatus,
    UploadRow,
)
from ...ports.base import Conflict, NotFound
from .stores import Database, epoch_for, insert_first_revision, set_context, write_result

TERMINAL_FENCES = frozenset({"capture_deleted", "permission_changed"})
CAPTURE_SELECT = ("SELECT c.capture_id, c.owner_id, c.upload_id, c.asset_id, c.media_type, c.width, c.height, "
                  "c.exif_orientation, c.sha256, a.version_ref, a.size_bytes, (c.deleted_at IS NOT NULL) AS deleted "
                  "FROM app.capture c JOIN app.asset a ON a.asset_id = c.asset_id ")


def _capture(row: Mapping[str, Any] | None) -> CaptureRow | None:
    return CaptureRow(**dict(row)) if row is not None else None


class PostgresIntakeRepository:
    def __init__(self, db: Database, *, engine_version: str) -> None:
        self.db = db
        self.engine_version = engine_version

    def count_uploads_since(self, owner_id: str, since: datetime) -> int:
        with self.db.session(owner_id) as conn:
            return int(conn.execute(text("SELECT count(*) FROM app.upload WHERE created_at >= :s"),
                                    {"s": since}).scalar())

    def create_upload(self, row: UploadRow, created_at: datetime) -> None:
        with self.db.session(row.owner_id) as conn:
            conn.execute(text("INSERT INTO app.upload (upload_id, owner_id, asset_id, media_type, max_bytes, state, "
                              "created_at, expires_at) VALUES (:u, :o, :a, :m, :b, 'RESERVED', :c, :e)"),
                         {"u": row.upload_id, "o": row.owner_id, "a": row.asset_id, "m": row.media_type,
                          "b": row.max_bytes, "c": created_at, "e": row.expires_at})

    def upload(self, owner_id: str, upload_id: str) -> UploadRow | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text("SELECT upload_id, owner_id, asset_id, media_type, max_bytes, state, expires_at "
                                    "FROM app.upload WHERE upload_id = :u"), {"u": upload_id}).mappings().first()
        return UploadRow(**dict(row)) if row else None

    def capture_for_upload(self, owner_id: str, upload_id: str) -> CaptureRow | None:
        with self.db.session(owner_id) as conn:
            return _capture(conn.execute(text(CAPTURE_SELECT + "WHERE c.upload_id = :u"),
                                         {"u": upload_id}).mappings().first())

    def record_capture(self, capture: CaptureRow, at: datetime) -> CaptureRow:
        with self.db.session(capture.owner_id) as conn:
            state = conn.execute(text("SELECT state FROM app.upload WHERE upload_id = :u FOR UPDATE"),
                                 {"u": capture.upload_id}).scalar()
            if state is None:
                raise NotFound("upload_not_found")
            existing = _capture(conn.execute(text(CAPTURE_SELECT + "WHERE c.upload_id = :u"),
                                             {"u": capture.upload_id}).mappings().first())
            if existing is not None:
                return existing
            if state != "RESERVED":
                raise Conflict("upload_not_open")
            conn.execute(text("INSERT INTO app.asset (asset_id, owner_id, kind, sha256, media_type, size_bytes, "
                              "version_ref, created_at) VALUES (:a, :o, 'ORIGINAL', :h, :m, :s, :v, :t)"),
                         {"a": capture.asset_id, "o": capture.owner_id, "h": capture.sha256, "m": capture.media_type,
                          "s": capture.size_bytes, "v": capture.version_ref, "t": at})
            conn.execute(text("INSERT INTO app.capture (capture_id, owner_id, upload_id, asset_id, media_type, width, "
                              "height, exif_orientation, sha256, created_at) VALUES (:c, :o, :u, :a, :m, :w, :h, :x, "
                              ":s, :t)"),
                         {"c": capture.capture_id, "o": capture.owner_id, "u": capture.upload_id, "a": capture.asset_id,
                          "m": capture.media_type, "w": capture.width, "h": capture.height,
                          "x": capture.exif_orientation, "s": capture.sha256, "t": at})
            conn.execute(text("UPDATE app.upload SET state = 'COMPLETED', completed_at = :t WHERE upload_id = :u"),
                         {"t": at, "u": capture.upload_id})
        return capture

    def capture(self, owner_id: str, capture_id: str) -> CaptureRow | None:
        with self.db.session(owner_id) as conn:
            return _capture(conn.execute(text(CAPTURE_SELECT + "WHERE c.capture_id = :c"),
                                         {"c": capture_id}).mappings().first())

    def count_active_jobs(self, owner_id: str) -> int:
        with self.db.session(owner_id) as conn:
            return int(conn.execute(text("SELECT count(*) FROM app.job WHERE state IN ('QUEUED', 'LEASED')")).scalar())

    def create_analysis(self, capture: CaptureRow, *, run_id: str, job_id: str, dedupe_key: str,
                        permission_epoch: int, at: datetime) -> str:
        owner = capture.owner_id
        try:
            with self.db.session(owner) as conn:
                existing = conn.execute(text("SELECT subject_ref FROM app.job WHERE dedupe_key = :k"),
                                        {"k": dedupe_key}).scalar()
                if existing is not None:
                    return existing
                conn.execute(text(
                    "INSERT INTO app.analysis_run (run_id, owner_id, input_asset_id, capture_id, status, engine_version, "
                    "feature_schema, method_manifest, analysis_config_sha256, input_sha256, created_at) VALUES "
                    "(:r, :o, :a, :c, 'QUEUED', :e, :f, :m, :cfg, :h, :t)"),
                    {"r": run_id, "o": owner, "a": capture.asset_id, "c": capture.capture_id, "e": self.engine_version,
                     "f": g.FEATURE_SCHEMA_VERSION, "m": g.METHOD_MANIFEST_SHA256, "cfg": ANALYSIS_CONFIG_SHA256,
                     "h": capture.sha256, "t": at})
                conn.execute(text(
                    "INSERT INTO app.job (job_id, kind, owner_id, subject_ref, state, dedupe_key, payload, created_at, "
                    "updated_at) VALUES (:j, :k, :o, :r, 'QUEUED', :d, CAST(:p AS jsonb), :t, :t)"),
                    {"j": job_id, "k": ANALYSIS_KIND, "o": owner, "r": run_id, "d": dedupe_key, "t": at,
                     "p": json.dumps({"capture_id": capture.capture_id, "permission_epoch": permission_epoch})})
            return run_id
        except IntegrityError:
            # A concurrent submission won the unique dedupe key; converge on its run.
            with self.db.session(owner) as conn:
                existing = conn.execute(text("SELECT subject_ref FROM app.job WHERE dedupe_key = :k"),
                                        {"k": dedupe_key}).scalar()
            if existing is None:
                raise
            return existing

    def run_status(self, owner_id: str, run_id: str) -> RunStatus | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text(
                "SELECT r.run_id, r.status, r.error_code, j.state AS job_state, "
                "(SELECT report_id FROM app.report WHERE run_id = r.run_id AND deleted_at IS NULL) AS report_id "
                "FROM app.analysis_run r LEFT JOIN app.job j ON j.subject_ref = r.run_id AND j.kind = :k "
                "WHERE r.run_id = :r"), {"r": run_id, "k": ANALYSIS_KIND}).mappings().first()
        if row is None:
            return None
        state = row["status"]
        if state == "QUEUED" and row["job_state"] == "LEASED":
            state = "RUNNING"
        return RunStatus(row["run_id"], state, row["report_id"], row["error_code"])

    def cancel_run(self, owner_id: str, run_id: str, at: datetime) -> bool:
        with self.db.session(owner_id) as conn:
            found = conn.execute(text("SELECT 1 FROM app.analysis_run WHERE run_id = :r FOR UPDATE"),
                                 {"r": run_id}).scalar()
            if found is None:
                return False
            conn.execute(text("UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL, "
                              "updated_at = :t WHERE subject_ref = :r AND state IN ('QUEUED', 'LEASED')"),
                         {"r": run_id, "t": at})
            conn.execute(text("UPDATE app.analysis_run SET status = 'CANCELLED', completed_at = :t "
                              "WHERE run_id = :r AND status IN ('QUEUED', 'RUNNING')"), {"r": run_id, "t": at})
        return True

    def delete_capture(self, owner_id: str, capture_id: str, at: datetime) -> None:
        with self.db.session(owner_id) as conn:
            asset = conn.execute(text("UPDATE app.capture SET deleted_at = coalesce(deleted_at, :t) "
                                      "WHERE capture_id = :c RETURNING asset_id"), {"c": capture_id, "t": at}).scalar()
            if asset is None:
                raise NotFound("capture_not_found")
            conn.execute(text("UPDATE app.asset SET deleted_at = coalesce(deleted_at, :t) WHERE asset_id = :a"),
                         {"a": asset, "t": at})
            runs = [r[0] for r in conn.execute(text("SELECT run_id FROM app.analysis_run WHERE capture_id = :c"),
                                               {"c": capture_id}).all()]
            for run_id in runs:
                conn.execute(text("UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL, "
                                  "updated_at = :t WHERE subject_ref = :r AND state IN ('QUEUED', 'LEASED')"),
                             {"r": run_id, "t": at})
                conn.execute(text("UPDATE app.analysis_run SET status = 'CANCELLED', completed_at = :t "
                                  "WHERE run_id = :r AND status IN ('QUEUED', 'RUNNING')"), {"r": run_id, "t": at})
            conn.execute(text("UPDATE app.report SET deleted_at = coalesce(deleted_at, :t) "
                              "WHERE run_id = ANY(:runs)"), {"t": at, "runs": runs})
            conn.execute(text("INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, "
                              "dedupe_key, created_at) VALUES (:e, 'capture.deletion_requested', :o, :c, "
                              "CAST(:p AS jsonb), :d, :t) ON CONFLICT (dedupe_key) DO NOTHING"),
                         {"e": f"evt.capture_deletion.{capture_id}", "o": owner_id, "c": capture_id, "t": at,
                          "p": json.dumps({"asset_id": asset}), "d": f"capture-deletion:{capture_id}"})


class PostgresJobQueue:
    """Worker-side queue; ``db`` must connect as a ``princess_worker`` member."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> ClaimedJob | None:
        with self.db.session() as conn:
            # Workers that crash repeatedly must not reclaim a poison job forever.
            conn.execute(text("UPDATE app.job SET state = 'FAILED', lease_owner = NULL, lease_expires_at = NULL, "
                              "last_error = 'attempts_exhausted', updated_at = :now WHERE kind = :k "
                              "AND state = 'LEASED' AND lease_expires_at < :now AND attempts >= :max"),
                         {"now": now, "k": ANALYSIS_KIND, "max": MAX_ATTEMPTS + 1})
            row = conn.execute(text(
                "UPDATE app.job SET state = 'LEASED', lease_owner = :w, lease_expires_at = :exp, "
                "fencing_token = fencing_token + 1, attempts = attempts + 1, updated_at = :now "
                "WHERE job_id = (SELECT job_id FROM app.job WHERE kind = :k AND (state = 'QUEUED' OR "
                "(state = 'LEASED' AND lease_expires_at < :now)) ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING job_id, owner_id, subject_ref, fencing_token, attempts, payload"),
                {"w": worker_id, "exp": now + timedelta(seconds=lease_seconds), "now": now,
                 "k": ANALYSIS_KIND}).mappings().first()
            if row is None:
                return None
            conn.execute(text("INSERT INTO app.job_attempt (job_id, fencing_token, worker_id, started_at) "
                              "VALUES (:j, :f, :w, :t)"),
                         {"j": row["job_id"], "f": row["fencing_token"], "w": worker_id, "t": now})
        payload = row["payload"]
        return ClaimedJob(row["job_id"], row["owner_id"], row["subject_ref"], payload["capture_id"],
                          int(row["fencing_token"]), int(row["attempts"]), int(payload["permission_epoch"]))

    def capture(self, job: ClaimedJob) -> CaptureRow | None:
        with self.db.session(job.owner_id) as conn:
            return _capture(conn.execute(text(CAPTURE_SELECT + "WHERE c.capture_id = :c"),
                                         {"c": job.capture_id}).mappings().first())

    def _lock(self, conn: Connection, job: ClaimedJob, now: datetime) -> None:
        row = conn.execute(text("SELECT state, fencing_token, lease_expires_at FROM app.job WHERE job_id = :j "
                                "FOR UPDATE"), {"j": job.job_id}).mappings().first()
        if row is None or row["fencing_token"] != job.fencing_token:
            raise Fenced("stale_fencing_token")
        if row["state"] != "LEASED":
            raise Fenced("job_cancelled" if row["state"] == "CANCELLED" else "job_not_leased")
        if row["lease_expires_at"] <= now:
            raise Fenced("lease_expired")

    def _finish_attempt(self, conn: Connection, job: ClaimedJob, outcome: str, code: str | None,
                        now: datetime) -> None:
        conn.execute(text("UPDATE app.job_attempt SET finished_at = :t, outcome = :o, error_code = :c "
                          "WHERE job_id = :j AND fencing_token = :f"),
                     {"t": now, "o": outcome, "c": code, "j": job.job_id, "f": job.fencing_token})

    def fail(self, job: ClaimedJob, error_code: str, *, retry: bool, now: datetime) -> None:
        with self.db.session() as conn:
            try:
                self._lock(conn, job, now)
            except Fenced:
                self._finish_attempt(conn, job, "FENCED", error_code, now)
                return
            final = not retry or job.attempts >= MAX_ATTEMPTS
            conn.execute(text("UPDATE app.job SET state = :s, lease_owner = NULL, lease_expires_at = NULL, "
                              "last_error = :c, updated_at = :t WHERE job_id = :j"),
                         {"s": "FAILED" if final else "QUEUED", "c": error_code, "t": now, "j": job.job_id})
            self._finish_attempt(conn, job, "FAILED" if final else "RETRY", error_code, now)
            if final:
                set_context(conn, job.owner_id)
                conn.execute(text("UPDATE app.analysis_run SET status = 'FAILED', error_code = :c, completed_at = :t "
                                  "WHERE run_id = :r AND status IN ('QUEUED', 'RUNNING')"),
                             {"c": error_code, "t": now, "r": job.run_id})

    def publish(self, job: ClaimedJob, *, result: Mapping[str, Any], evidence: ValidatedDocument,
                report: ValidatedDocument, processed_sha256: str, now: datetime) -> None:
        try:
            with self.db.session() as conn:
                self._lock(conn, job, now)
                set_context(conn, job.owner_id)
                deleted = conn.execute(text("SELECT deleted_at IS NOT NULL FROM app.capture WHERE capture_id = :c "
                                            "FOR SHARE"), {"c": job.capture_id}).scalar()
                if deleted is None or deleted:
                    raise Fenced("capture_deleted")
                if epoch_for(conn, job.owner_id, SERVICE_PURPOSE, lock=True) != job.permission_epoch:
                    raise Fenced("permission_changed")
                write_result(conn, job.owner_id, job.run_id, result=result, processed_sha256=processed_sha256,
                             at=now, evidence=evidence)
                insert_first_revision(conn, job.owner_id, report)
                report_id = report.data["report_id"]
                conn.execute(text("INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, "
                                  "dedupe_key, created_at) VALUES (:e, 'report.ready', :o, :r, '{}'::jsonb, :d, :t)"),
                             {"e": f"evt.report_ready.{report_id}", "o": job.owner_id, "r": report_id,
                              "d": f"report-ready:{report_id}", "t": now})
                set_context(conn, None)
                conn.execute(text("UPDATE app.job SET state = 'SUCCEEDED', lease_owner = NULL, lease_expires_at = NULL, "
                                  "updated_at = :t WHERE job_id = :j"), {"t": now, "j": job.job_id})
                self._finish_attempt(conn, job, "SUCCEEDED", None, now)
        except Fenced as fenced:
            with self.db.session() as conn:
                self._finish_attempt(conn, job, "FENCED", fenced.reason, now)
                if fenced.reason in TERMINAL_FENCES:
                    # This worker still holds the lease: end the job instead of letting it be reclaimed.
                    ended = conn.execute(text("UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, "
                                              "lease_expires_at = NULL, last_error = :c, updated_at = :t "
                                              "WHERE job_id = :j AND fencing_token = :f AND state = 'LEASED'"),
                                         {"c": fenced.reason, "t": now, "j": job.job_id,
                                          "f": job.fencing_token}).rowcount
                    if ended:
                        set_context(conn, job.owner_id)
                        conn.execute(text("UPDATE app.analysis_run SET status = 'CANCELLED', error_code = :c, "
                                          "completed_at = :t WHERE run_id = :r AND status IN ('QUEUED', 'RUNNING')"),
                                     {"c": fenced.reason, "t": now, "r": job.run_id})
            raise
