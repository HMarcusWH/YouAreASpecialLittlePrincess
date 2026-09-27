"""PostgreSQL implementations of the application stores (T02).

Every transaction sets ``princess.principal_id`` (and, during login, the
verified ``princess.auth_issuer``/``princess.auth_subject``) with
transaction-local ``set_config`` so row-level security scopes each query.
The runtime login role must be a member of ``princess_app`` and must not own
the tables, be a superuser or have BYPASSRLS.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterator, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from princess_contracts import ValidatedDocument, canonical_digest, compile_document

from ...application.identity import Principal
from ...application.permissions import replayed
from ...domain.permissions import Decision, PermissionEvent, Scope
from ...domain.reports import check_revision
from ...ports.base import Conflict, InvalidInput, NotAuthorized, NotFound


def make_engine(url: str) -> Engine:
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True, future=True)


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def session(self, principal_id: str | None = None, *, auth: tuple[str, str] | None = None) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            set_context(conn, principal_id, auth)
            yield conn


def set_context(conn: Connection, principal_id: str | None, auth: tuple[str, str] | None = None) -> None:
    issuer, subject = auth or ("", "")
    conn.execute(text("SELECT set_config('princess.principal_id', :p, true), "
                      "set_config('princess.auth_issuer', :i, true), set_config('princess.auth_subject', :s, true)"),
                 {"p": principal_id or "", "i": issuer, "s": subject})


def _principal(row: Mapping[str, Any]) -> Principal:
    return Principal(principal_id=row["principal_id"], kind=row["kind"], created_at=row["created_at"],
                     revoked_before=row.get("revoked_before"), deleted_at=row.get("deleted_at"),
                     transferred_to=row.get("transferred_to"), guest_expires_at=row.get("guest_expires_at"))


PRINCIPAL_COLUMNS = ("principal_id, kind, created_at, revoked_before, deleted_at, transferred_to, "
                     "guest_expires_at")


class PostgresIdentityStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def principal(self, principal_id: str) -> Principal | None:
        with self.db.session(principal_id) as conn:
            row = conn.execute(text(f"SELECT {PRINCIPAL_COLUMNS} FROM app.principal WHERE principal_id = :p"),
                               {"p": principal_id}).mappings().first()
        return _principal(row) if row else None

    def principal_for_binding(self, issuer: str, subject: str) -> Principal | None:
        with self.db.session(auth=(issuer, subject)) as conn:
            pid = conn.execute(text("SELECT principal_id FROM app.identity_binding WHERE issuer = :i AND subject = :s"),
                               {"i": issuer, "s": subject}).scalar()
            if pid is None:
                return None
            set_context(conn, pid, (issuer, subject))
            row = conn.execute(text(f"SELECT {PRINCIPAL_COLUMNS} FROM app.principal WHERE principal_id = :p"),
                               {"p": pid}).mappings().first()
        return _principal(row) if row else None

    def create_account(self, principal_id: str, issuer: str, subject: str, at: datetime) -> Principal:
        try:
            with self.db.session(principal_id, auth=(issuer, subject)) as conn:
                conn.execute(text("INSERT INTO app.principal (principal_id, kind, created_at) VALUES (:p, 'ACCOUNT', :t)"),
                             {"p": principal_id, "t": at})
                conn.execute(text("INSERT INTO app.identity_binding (issuer, subject, principal_id, created_at) "
                                  "VALUES (:i, :s, :p, :t)"), {"i": issuer, "s": subject, "p": principal_id, "t": at})
        except IntegrityError:
            raise Conflict("binding_exists") from None
        return Principal(principal_id, "ACCOUNT", at)

    def create_guest(self, principal_id: str, token_hash: str, expires_at: datetime, at: datetime) -> Principal:
        with self.db.session(principal_id) as conn:
            conn.execute(text("INSERT INTO app.principal (principal_id, kind, created_at, guest_capability_sha256, "
                              "guest_expires_at) VALUES (:p, 'GUEST', :t, :h, :e)"),
                         {"p": principal_id, "t": at, "h": token_hash, "e": expires_at})
        return Principal(principal_id, "GUEST", at, guest_expires_at=expires_at)

    def admit_guest(self, at: datetime, policy) -> bool:
        with self.db.session() as conn:
            return bool(conn.execute(text("SELECT app.admit_guest(:t, :w, :n)"),
                                     {"t": at, "w": policy.window_seconds, "n": policy.limit}).scalar())

    def guest_by_capability(self, token_hash: str) -> Principal | None:
        with self.db.session() as conn:
            row = conn.execute(text("SELECT * FROM app.resolve_guest(:h)"), {"h": token_hash}).mappings().first()
        if row is None:
            return None
        return Principal(row["principal_id"], "GUEST", row["created_at"], deleted_at=row["deleted_at"],
                         revoked_before=row["revoked_before"], guest_expires_at=row["guest_expires_at"])

    def transfer_guest(self, token_hash: str, account_id: str, at: datetime) -> str:
        try:
            with self.db.session(account_id) as conn:
                return conn.execute(text("SELECT app.transfer_guest(:h, :t)"), {"h": token_hash, "t": at}).scalar_one()
        except DBAPIError as exc:
            state = getattr(exc.orig, "sqlstate", None)
            if state == "P0002":
                raise Conflict("guest_not_transferable") from None
            if state == "42501":
                raise NotAuthorized("account_required") from None
            raise

    def revoke_sessions(self, principal_id: str, at: datetime) -> None:
        with self.db.session(principal_id) as conn:
            conn.execute(text("UPDATE app.principal SET revoked_before = greatest(coalesce(revoked_before, :t), :t) "
                              "WHERE principal_id = :p"), {"p": principal_id, "t": at})

    def mark_deleted(self, principal_id: str, at: datetime) -> None:
        with self.db.session(principal_id) as conn:
            updated = conn.execute(text("UPDATE app.principal SET deleted_at = coalesce(deleted_at, :t), "
                                        "revoked_before = greatest(coalesce(revoked_before, :t), :t) "
                                        "WHERE principal_id = :p"), {"p": principal_id, "t": at}).rowcount
            if updated != 1:
                raise NotFound("principal_not_found")
            conn.execute(text("INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, "
                              "dedupe_key, created_at) VALUES (:e, 'account.deletion_requested', :p, :p, '{}'::jsonb, "
                              ":d, :t) ON CONFLICT (dedupe_key) DO NOTHING"),
                         {"e": f"evt.deletion.{principal_id}", "p": principal_id, "d": f"account-deletion:{principal_id}",
                          "t": at})

    def rebind_after_deletion(self, issuer: str, subject: str, new_principal_id: str, at: datetime) -> Principal:
        with self.db.session(auth=(issuer, subject)) as conn:
            old_id = conn.execute(text("SELECT principal_id FROM app.identity_binding WHERE issuer = :i AND subject = :s "
                                       "FOR UPDATE"), {"i": issuer, "s": subject}).scalar()
            if old_id is None:
                raise NotFound("binding_not_found")
            set_context(conn, old_id, (issuer, subject))
            deleted_at = conn.execute(text("SELECT deleted_at FROM app.principal WHERE principal_id = :p"),
                                      {"p": old_id}).scalar()
            if deleted_at is None:
                raise Conflict("binding_not_tombstoned")
            set_context(conn, new_principal_id, (issuer, subject))
            conn.execute(text("INSERT INTO app.principal (principal_id, kind, created_at, revoked_before) "
                              "VALUES (:p, 'ACCOUNT', :t, :r)"), {"p": new_principal_id, "t": at, "r": deleted_at})
            conn.execute(text("UPDATE app.identity_binding SET principal_id = :p WHERE issuer = :i AND subject = :s"),
                         {"p": new_principal_id, "i": issuer, "s": subject})
        return Principal(new_principal_id, "ACCOUNT", at, revoked_before=deleted_at)

    def bindings(self, principal_id: str) -> list[tuple[str, str]]:
        with self.db.session(principal_id) as conn:
            rows = conn.execute(text("SELECT issuer, subject FROM app.identity_binding WHERE principal_id = :p "
                                     "ORDER BY issuer, subject"), {"p": principal_id}).all()
        return [(r[0], r[1]) for r in rows]


class PostgresPermissionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, event: PermissionEvent) -> PermissionEvent:
        with self.db.session(event.subject_id) as conn:
            sequence = conn.execute(text(
                "INSERT INTO app.permission_event (event_id, subject_id, actor_id, purpose_id, purpose_version, "
                "scope_kind, scope_ref, decision, recorded_at, effective_at, notice_version) VALUES "
                "(:e, :s, :a, :p, :v, :k, :r, :d, :rec, :eff, :n) ON CONFLICT (event_id) DO NOTHING "
                "RETURNING sequence"),
                {"e": event.event_id, "s": event.subject_id, "a": event.actor_id, "p": event.purpose_id,
                 "v": event.purpose_version, "k": event.scope.kind, "r": event.scope.ref, "d": event.decision.value,
                 "rec": event.recorded_at, "eff": event.effective_at, "n": event.notice_version}).scalar()
            if sequence is None:  # replayed request: return the recorded event, move no epoch
                prior = [e for e in self._rows(conn, event.subject_id, event.purpose_id) if e.event_id == event.event_id]
                if not prior:
                    raise Conflict("request_id_reused")
                return replayed(prior[0], event)
            if event.decision is not Decision.GRANT:
                conn.execute(text("INSERT INTO app.permission_epoch (subject_id, purpose_id, epoch) VALUES (:s, :p, 1) "
                                  "ON CONFLICT (subject_id, purpose_id) DO UPDATE SET epoch = "
                                  "app.permission_epoch.epoch + 1"), {"s": event.subject_id, "p": event.purpose_id})
        return replace(event, sequence=sequence)

    def events(self, subject_id: str, purpose_id: str) -> list[PermissionEvent]:
        with self.db.session(subject_id) as conn:
            return self._rows(conn, subject_id, purpose_id)

    @staticmethod
    def _rows(conn: Connection, subject_id: str, purpose_id: str) -> list[PermissionEvent]:
        rows = conn.execute(text("SELECT * FROM app.permission_event WHERE subject_id = :s AND purpose_id = :p "
                                 "ORDER BY sequence"), {"s": subject_id, "p": purpose_id}).mappings().all()
        return [PermissionEvent(event_id=r["event_id"], subject_id=r["subject_id"], purpose_id=r["purpose_id"],
                                purpose_version=r["purpose_version"], scope=Scope(r["scope_kind"], r["scope_ref"]),
                                decision=Decision(r["decision"]), recorded_at=r["recorded_at"],
                                effective_at=r["effective_at"], actor_id=r["actor_id"],
                                notice_version=r["notice_version"], sequence=r["sequence"]) for r in rows]

    def epoch(self, subject_id: str, purpose_id: str) -> int:
        with self.db.session(subject_id) as conn:
            return epoch_for(conn, subject_id, purpose_id)


def epoch_for(conn: Connection, subject_id: str, purpose_id: str, *, lock: bool = False) -> int:
    """Current epoch; with ``lock`` the row is share-locked until commit so a
    concurrent withdrawal waits (publication fencing)."""
    if lock:
        conn.execute(text("INSERT INTO app.permission_epoch (subject_id, purpose_id, epoch) VALUES (:s, :p, 0) "
                          "ON CONFLICT DO NOTHING"), {"s": subject_id, "p": purpose_id})
    value = conn.execute(text("SELECT epoch FROM app.permission_epoch WHERE subject_id = :s AND purpose_id = :p"
                              + (" FOR SHARE" if lock else "")), {"s": subject_id, "p": purpose_id}).scalar()
    return int(value or 0)


class PostgresAnalysisStore:
    """Assets and runs. Result JSON and its relational projections commit together."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create_asset(self, owner_id: str, asset_id: str, *, kind: str, sha256: str, media_type: str, size_bytes: int,
                     version_ref: str, at: datetime, parent_asset_id: str | None = None) -> None:
        with self.db.session(owner_id) as conn:
            conn.execute(text("INSERT INTO app.asset (asset_id, owner_id, kind, parent_asset_id, sha256, media_type, "
                              "size_bytes, version_ref, created_at) VALUES (:a, :o, :k, :pa, :h, :m, :s, :v, :t)"),
                         {"a": asset_id, "o": owner_id, "k": kind, "pa": parent_asset_id, "h": sha256, "m": media_type,
                          "s": size_bytes, "v": version_ref, "t": at})

    def create_run(self, owner_id: str, run_id: str, *, asset_id: str, engine_version: str, feature_schema: str,
                   method_manifest: str, analysis_config_sha256: str, input_sha256: str, at: datetime) -> None:
        with self.db.session(owner_id) as conn:
            conn.execute(text("INSERT INTO app.analysis_run (run_id, owner_id, input_asset_id, status, engine_version, "
                              "feature_schema, method_manifest, analysis_config_sha256, input_sha256, created_at) VALUES "
                              "(:r, :o, :a, 'QUEUED', :e, :f, :m, :c, :h, :t)"),
                         {"r": run_id, "o": owner_id, "a": asset_id, "e": engine_version, "f": feature_schema,
                          "m": method_manifest, "c": analysis_config_sha256, "h": input_sha256, "t": at})

    def complete_run(self, owner_id: str, run_id: str, *, result: Mapping[str, Any], processed_sha256: str,
                     at: datetime, evidence: ValidatedDocument | None = None) -> str:
        with self.db.session(owner_id) as conn:
            return write_result(conn, owner_id, run_id, result=result, processed_sha256=processed_sha256, at=at,
                                evidence=evidence)

    def result(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text("SELECT result, result_digest FROM app.analysis_run WHERE run_id = :r "
                                    "AND status = 'SUCCEEDED'"), {"r": run_id}).first()
        if row is None:
            return None
        if canonical_digest(row[0]) != row[1]:
            raise Conflict("stored_result_digest_mismatch")
        return row[0]


def queue_asset_erasure(conn: Connection, owner_id: str, asset_id: str, at: datetime) -> None:
    """Queue verified erasure of one stored asset in the caller's transaction
    (``asset.erasure_requested``, consumed by the erasure worker)."""
    conn.execute(text("INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, "
                      "created_at) VALUES (:e, 'asset.erasure_requested', :o, :a, CAST(:p AS jsonb), :d, :t) "
                      "ON CONFLICT (dedupe_key) DO NOTHING"),
                 {"e": f"evt.asset_erasure.{asset_id}", "o": owner_id, "a": asset_id, "t": at,
                  "p": json.dumps({"asset_id": asset_id}), "d": f"asset-erasure:{asset_id}"})


def lock_live_owner(conn: Connection, owner_id: str) -> None:
    """Deletion fence for owner writes: hold the principal row FOR SHARE so a
    concurrent account deletion waits for this transaction, and refuse once a
    deletion has committed. Background writers cannot rely on session revocation."""
    deleted = conn.execute(text("SELECT deleted_at IS NOT NULL FROM app.principal WHERE principal_id = :p FOR SHARE"),
                           {"p": owner_id}).scalar()
    if deleted is None or deleted:
        raise NotFound("owner_deleted")


def write_result(conn: Connection, owner_id: str, run_id: str, *, result: Mapping[str, Any], processed_sha256: str,
                 at: datetime, evidence: ValidatedDocument | None = None) -> str:
    """Persist canonical result JSON and its projections in the caller's transaction."""
    if (result.get("metadata") or {}).get("input_pixels_sha256") != processed_sha256:
        raise InvalidInput("processed_digest_mismatch")
    lock_live_owner(conn, owner_id)
    measurements = result.get("measurements", {})
    regions = _parent_first(result.get("regions", []))
    digest = canonical_digest(dict(result))
    status = conn.execute(text("SELECT status FROM app.analysis_run WHERE run_id = :r FOR UPDATE"),
                          {"r": run_id}).scalar()
    if status is None:
        raise NotFound("run_not_found")
    if status not in ("QUEUED", "RUNNING"):
        raise Conflict("run_not_open")
    for region in regions:
        x, y, w, h = region["box"]
        conn.execute(text("INSERT INTO app.region (owner_id, run_id, region_id, scope, x, y, width, height, "
                          "parent_region_id) VALUES (:o, :r, :id, :s, :x, :y, :w, :h, :p)"),
                     {"o": owner_id, "r": run_id, "id": region["region_id"], "s": region["scope"], "x": x,
                      "y": y, "w": w, "h": h, "p": region.get("parent_id")})
    for feature_id, m in measurements.items():
        conn.execute(text("INSERT INTO app.measurement (owner_id, run_id, feature_id, value_float, value_json, "
                          "unit, quality, missing_reason, n_observations, method_id, confidence, "
                          "confidence_kind) VALUES (:o, :r, :f, :vf, CAST(:vj AS jsonb), :u, :q, :mr, :n, "
                          ":mid, :c, :ck)"), {"o": owner_id, "r": run_id, "f": feature_id,
                                              **_value_columns(m.get("raw_value")), "u": m.get("unit"),
                                              "q": m.get("quality_flag"), "mr": m.get("missing_reason"),
                                              "n": m.get("n_observations"), "mid": m.get("method_version"),
                                              "c": m.get("confidence"), "ck": m.get("confidence_kind")})
    stored = conn.execute(text("SELECT count(*) FROM app.measurement WHERE run_id = :r"), {"r": run_id}).scalar()
    if stored != len(measurements):
        raise Conflict("projection_count_mismatch")
    if evidence is not None:
        data = evidence.data
        if data["analysis"]["run_id"] != run_id or data["analysis"]["owner_id"] != owner_id:
            raise InvalidInput("evidence_for_another_run")
        conn.execute(text("INSERT INTO app.evidence_bundle (bundle_id, owner_id, run_id, digest, document, "
                          "created_at) VALUES (:b, :o, :r, :d, CAST(:doc AS jsonb), :t)"),
                     {"b": data["bundle_id"], "o": owner_id, "r": run_id, "d": evidence.digest,
                      "doc": json.dumps(evidence.to_dict()), "t": at})
    conn.execute(text("UPDATE app.analysis_run SET status = 'SUCCEEDED', result = CAST(:res AS jsonb), "
                      "result_digest = :d, processed_sha256 = :ph, completed_at = :t, error_code = NULL "
                      "WHERE run_id = :r"),
                 {"res": json.dumps(result, allow_nan=False), "d": digest, "ph": processed_sha256, "t": at,
                  "r": run_id})
    return digest


def insert_first_revision(conn: Connection, owner_id: str, report: ValidatedDocument) -> None:
    data = report.data
    if data["revision"] != 1 or data["analysis"]["owner_id"] != owner_id:
        raise Conflict("not_a_first_revision_for_owner")
    lock_live_owner(conn, owner_id)
    conn.execute(text("INSERT INTO app.report (report_id, owner_id, run_id, kind, created_at) "
                      "VALUES (:r, :o, :run, :k, :t)"),
                 {"r": data["report_id"], "o": owner_id, "run": data["analysis"]["run_id"], "k": data["kind"],
                  "t": data["created_at"]})
    conn.execute(text("INSERT INTO app.report_revision (report_id, revision, owner_id, digest, document, created_at) "
                      "VALUES (:r, 1, :o, :d, CAST(:doc AS jsonb), :t)"),
                 {"r": data["report_id"], "o": owner_id, "d": report.digest, "doc": json.dumps(report.to_dict()),
                  "t": data["created_at"]})


def _value_columns(value: Any) -> dict[str, Any]:
    if value is None:
        return {"vf": None, "vj": None}
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise InvalidInput("nonfinite_measurement")
        return {"vf": float(value), "vj": None}
    return {"vf": None, "vj": json.dumps(value, allow_nan=False)}


MAX_REGION_DEPTH = 64


def _parent_first(regions: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Order regions parents-first; a parent cycle (including a self-parent)
    or a chain deeper than MAX_REGION_DEPTH rejects the whole result before
    any projection row is written."""
    by_id = {r["region_id"]: r for r in regions}
    ordered, done = [], set()
    for region in regions:
        path: list[Mapping[str, Any]] = []
        on_path: set[str] = set()
        node: Mapping[str, Any] | None = region
        while node is not None and node["region_id"] not in done:
            if node["region_id"] in on_path:
                raise InvalidInput("region_parent_cycle")
            if len(path) >= MAX_REGION_DEPTH:
                raise InvalidInput("region_hierarchy_too_deep")
            path.append(node)
            on_path.add(node["region_id"])
            node = by_id.get(node.get("parent_id"))
        for item in reversed(path):
            done.add(item["region_id"])
            ordered.append(item)
    return ordered


class PostgresReportStore:
    """Principal-scoped ReportStore: RLS makes other owners' reports invisible."""

    def __init__(self, db: Database, principal_id: str) -> None:
        self.db = db
        self.principal_id = principal_id

    def latest(self, report_id: str) -> tuple[str, ValidatedDocument] | None:
        with self.db.session(self.principal_id) as conn:
            row = conn.execute(text("SELECT rr.owner_id, rr.document, rr.digest FROM app.report_revision rr "
                                    "JOIN app.report r ON r.report_id = rr.report_id "
                                    "WHERE rr.report_id = :r AND r.deleted_at IS NULL "
                                    "ORDER BY rr.revision DESC LIMIT 1"), {"r": report_id}).first()
        if row is None:
            return None
        compiled = compile_document("ReportDocument", row[1])
        if compiled.value is None or compiled.value.digest != row[2]:
            raise Conflict("stored_report_invalid")
        return row[0], compiled.value

    def append(self, owner_id: str, report: ValidatedDocument) -> None:
        if owner_id != self.principal_id:
            raise NotAuthorized("owner_mismatch")
        data = report.data
        # The snapshot keeps the owner it was produced for; after a guest
        # transfer later revisions are authorized by the relational owner (RLS)
        # and check_revision keeps the analysis block unchanged.
        if data["revision"] == 1 and data["analysis"]["owner_id"] != owner_id:
            raise NotAuthorized("owner_mismatch")
        try:
            with self.db.session(owner_id) as conn:
                lock_live_owner(conn, owner_id)
                if data["revision"] == 1:
                    conn.execute(text("INSERT INTO app.report (report_id, owner_id, run_id, kind, created_at) "
                                      "VALUES (:r, :o, :run, :k, :t)"),
                                 {"r": data["report_id"], "o": owner_id, "run": data["analysis"]["run_id"],
                                  "k": data["kind"], "t": data["created_at"]})
                else:
                    # Serialize appends on the parent row; revisions themselves are append-only.
                    locked = conn.execute(text("SELECT 1 FROM app.report WHERE report_id = :r "
                                               "AND deleted_at IS NULL FOR UPDATE"),
                                          {"r": data["report_id"]}).scalar()
                    if locked is None:
                        raise NotFound("report_not_found")
                    prior = conn.execute(text("SELECT document FROM app.report_revision WHERE report_id = :r "
                                              "AND revision = :v"),
                                         {"r": data["report_id"], "v": data["revision"] - 1}).scalar()
                    previous = compile_document("ReportDocument", prior).value if prior is not None else None
                    if previous is None or check_revision(previous, report):
                        raise Conflict("invalid_revision")
                conn.execute(text("INSERT INTO app.report_revision (report_id, revision, owner_id, digest, document, "
                                  "created_at) VALUES (:r, :v, :o, :d, CAST(:doc AS jsonb), :t)"),
                             {"r": data["report_id"], "v": data["revision"], "o": owner_id, "d": report.digest,
                              "doc": json.dumps(report.to_dict()), "t": data["created_at"]})
        except IntegrityError:
            raise Conflict("revision_exists_or_invalid_link") from None
