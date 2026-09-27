"""PostgreSQL commerce ledger, Premium job queue and fenced overlay publisher (T19).

Every ledger mutation for an owner runs in one transaction under a per-owner
advisory lock, so grants, refunds, reservations and releases for the same
account serialize (no double grant, no last-credit race). The financial
identity ``(rail, environment, transaction_ref)`` is unique; a reservation is
unique per intended operation. Ledger entries are insert-only.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from princess_contracts import compile_document

from ...application.commerce import AI_PURPOSE, Balance, GrantResult, PendingCompletion, PremiumRequest
from ...application.premium.service import MAX_ATTEMPTS, AttemptRecord, Fenced, Outcome, PremiumJob, PremiumOverlay
from ...domain.commerce import Platform
from ...domain.reports import check_revision, revise_report
from ...ports.base import Conflict, Environment, IdGenerator, NotAuthorized, NotFound
from ...ports.payments import CatalogProduct, CompletionAction, NormalizedEvent, PaymentRail, TransactionObservation
from ...ports.storage import StoredObject
from .stores import Database, epoch_for, lock_live_owner, set_context

PREMIUM_KIND = "premium"
SERVER_COMPLETIONS = (CompletionAction.SERVER_CONSUME.value, CompletionAction.SERVER_ACKNOWLEDGE.value)


def _owner_lock(conn: Connection, owner_id: str) -> None:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"commerce:{owner_id}"})


def _entry(conn: Connection, owner_id: str, lot_id: str, kind: str, delta: int, at: datetime,
           reservation_id: str | None = None, reason: str | None = None) -> None:
    conn.execute(text("INSERT INTO app.ledger_entry (owner_id, lot_id, reservation_id, kind, delta, reason, "
                      "recorded_at) VALUES (:o, :l, :r, :k, :d, :why, :t)"),
                 {"o": owner_id, "l": lot_id, "r": reservation_id, "k": kind, "d": delta, "why": reason, "t": at})


def release_reservation(conn: Connection, owner_id: str, reservation_id: str, reason: str, at: datetime) -> bool:
    """RESERVED -> RELEASED and return the credit to an active lot (caller's transaction)."""
    lot_id = conn.execute(text("UPDATE app.credit_reservation SET state = 'RELEASED', settled_at = :t "
                               "WHERE reservation_id = :r AND state = 'RESERVED' RETURNING lot_id"),
                          {"t": at, "r": reservation_id}).scalar()
    if lot_id is None:
        return False
    restored = conn.execute(text("UPDATE app.credit_lot SET available = available + 1 WHERE lot_id = :l "
                                 "AND state = 'ACTIVE' RETURNING 1"), {"l": lot_id}).scalar()
    _entry(conn, owner_id, lot_id, "RELEASE", 1 if restored else 0, at, reservation_id,
           reason if restored else f"{reason}:lot_revoked")
    return True


class PostgresLedger:
    """API-side ledger (``princess_app`` login)."""

    def __init__(self, db: Database, ids: IdGenerator) -> None:
        self.db = db
        self._ids = ids

    # --- accounts, intents, inbox -------------------------------------------
    def account_ref(self, owner_id: str, at: datetime) -> str:
        with self.db.session(owner_id) as conn:
            conn.execute(text("INSERT INTO app.payment_account (owner_id, account_ref, created_at) "
                              "VALUES (:o, :a, :t) ON CONFLICT (owner_id) DO NOTHING"),
                         {"o": owner_id, "a": str(uuid.uuid4()), "t": at})
            return conn.execute(text("SELECT account_ref FROM app.payment_account WHERE owner_id = :o"),
                                {"o": owner_id}).scalar_one()

    def record_intent(self, owner_id: str, intent_ref: str, rail: PaymentRail, product_id: str,
                      at: datetime) -> None:
        try:
            with self.db.session(owner_id) as conn:
                lock_live_owner(conn, owner_id)  # a deleted account starts no checkout
                conn.execute(text("INSERT INTO app.purchase_intent (intent_ref, owner_id, rail, product_id, "
                                  "created_at) VALUES (:i, :o, :r, :p, :t) ON CONFLICT (intent_ref) DO NOTHING"),
                             {"i": intent_ref, "o": owner_id, "r": rail.value, "p": product_id, "t": at})
                same = conn.execute(text("SELECT product_id = :p FROM app.purchase_intent WHERE intent_ref = :i"),
                                    {"i": intent_ref, "p": product_id}).scalar()
        except IntegrityError:
            raise Conflict("intent_reused") from None
        if same is None or not same:
            raise Conflict("intent_reused")  # another owner's intent (invisible) or another product

    def record_event(self, event: NormalizedEvent, body_sha256: str, at: datetime) -> bool:
        with self.db.session() as conn:
            return conn.execute(text(
                "INSERT INTO app.provider_event (rail, environment, event_id, event_type, body_sha256, received_at) "
                "VALUES (:r, :e, :i, :ty, :h, :t) ON CONFLICT DO NOTHING RETURNING 1"),
                {"r": event.rail.value, "e": event.environment.value, "i": event.event_id[:256],
                 "ty": event.event_type[:128], "h": body_sha256, "t": at}).scalar() is not None

    def finish_event(self, event: NormalizedEvent, outcome: str, at: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(text("UPDATE app.provider_event SET processed_at = :t, outcome = :o WHERE rail = :r "
                              "AND environment = :e AND event_id = :i AND processed_at IS NULL"),
                         {"t": at, "o": outcome, "r": event.rail.value, "e": event.environment.value,
                          "i": event.event_id[:256]})

    def owner_for_account(self, account_ref: str) -> str | None:
        with self.db.session() as conn:
            return conn.execute(text("SELECT app.resolve_payment_owner(:a)"), {"a": account_ref}).scalar()

    def owner_for_transaction(self, rail: PaymentRail, environment: Environment, ref: str) -> str | None:
        with self.db.session() as conn:
            return conn.execute(text("SELECT app.resolve_transaction_owner(:r, :e, :t)"),
                                {"r": rail.value, "e": environment.value, "t": ref}).scalar()

    # --- grants and refunds ---------------------------------------------------
    def grant(self, owner_id: str, observation: TransactionObservation, product: CatalogProduct,
              at: datetime) -> GrantResult:
        txn_id, lot_id = self._ids.new_id("txn"), self._ids.new_id("lot")
        try:
            with self.db.session(owner_id) as conn:
                _owner_lock(conn, owner_id)
                lock_live_owner(conn, owner_id)
                inserted = conn.execute(text(
                    "INSERT INTO app.financial_transaction (txn_id, owner_id, rail, environment, transaction_ref, "
                    "product_id, quantity, observed_state, completion_action, completed_at, granted_at) VALUES "
                    "(:id, :o, :r, :e, :ref, :p, :q, :s, :a, :done, :t) "
                    "ON CONFLICT (rail, environment, transaction_ref) DO NOTHING RETURNING txn_id"),
                    {"id": txn_id, "o": owner_id, "r": observation.rail.value, "e": observation.environment.value,
                     "ref": observation.transaction_ref, "p": product.product_id, "q": observation.quantity,
                     "s": observation.state.value, "a": observation.completion_action.value,
                     "done": at if observation.completed else None, "t": at}).scalar()
                if inserted is None:
                    existing = conn.execute(text(
                        "SELECT txn_id, completed_at IS NULL AND completion_action = ANY(:c) AS due "
                        "FROM app.financial_transaction WHERE rail = :r AND environment = :e AND transaction_ref = :ref"),
                        {"r": observation.rail.value, "e": observation.environment.value,
                         "ref": observation.transaction_ref, "c": list(SERVER_COMPLETIONS)}).first()
                    if existing is None:
                        raise Conflict("transaction_granted_to_another_account")
                    return GrantResult(existing[0], None, False, bool(existing[1]))
                credits = product.credits * observation.quantity
                conn.execute(text("INSERT INTO app.credit_lot (lot_id, owner_id, txn_id, origin_rail, product_id, "
                                  "credits, available, state, created_at) VALUES (:l, :o, :x, :r, :p, :c, :c, "
                                  "'ACTIVE', :t)"),
                             {"l": lot_id, "o": owner_id, "x": txn_id, "r": observation.rail.value,
                              "p": product.product_id, "c": credits, "t": at})
                _entry(conn, owner_id, lot_id, "GRANT", credits, at, reason=observation.rail.value)
        except IntegrityError:
            raise Conflict("grant_conflict") from None
        due = observation.completion_action.value in SERVER_COMPLETIONS and not observation.completed
        return GrantResult(txn_id, lot_id, True, due)

    def refund(self, owner_id: str, observation: TransactionObservation, at: datetime) -> str:
        with self.db.session(owner_id) as conn:
            _owner_lock(conn, owner_id)
            txn = conn.execute(text("SELECT txn_id, refunded_at FROM app.financial_transaction WHERE rail = :r "
                                    "AND environment = :e AND transaction_ref = :ref FOR UPDATE"),
                               {"r": observation.rail.value, "e": observation.environment.value,
                                "ref": observation.transaction_ref}).first()
            if txn is None:
                return "refund_unmatched"
            if txn[1] is not None:
                return "already_refunded"
            conn.execute(text("UPDATE app.financial_transaction SET observed_state = :s, refunded_at = :t "
                              "WHERE txn_id = :x"), {"s": observation.state.value, "t": at, "x": txn[0]})
            lot = conn.execute(text("SELECT lot_id, available FROM app.credit_lot WHERE txn_id = :x FOR UPDATE"),
                               {"x": txn[0]}).first()
            lot_id, available = lot
            revoked = [r[0] for r in conn.execute(text(
                "UPDATE app.credit_reservation SET state = 'REVOKED', settled_at = :t WHERE lot_id = :l "
                "AND state = 'RESERVED' RETURNING reservation_id"), {"t": at, "l": lot_id}).all()]
            spent = conn.execute(text("SELECT count(*) FROM app.credit_reservation WHERE lot_id = :l "
                                      "AND state = 'SPENT'"), {"l": lot_id}).scalar()
            conn.execute(text("UPDATE app.credit_lot SET available = 0, state = 'REVOKED', revoked_at = :t "
                              "WHERE lot_id = :l"), {"t": at, "l": lot_id})
            if available:
                _entry(conn, owner_id, lot_id, "REVOKE", -available, at, reason="refund_unspent")
            for reservation_id in revoked:
                _entry(conn, owner_id, lot_id, "REVOKE", 0, at, reservation_id, "refund_reserved")
            if revoked:
                # Unstarted work for a refunded credit must not reach the provider;
                # a leased attempt loses its lease and cannot publish.
                conn.execute(text(
                    "UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL, "
                    "last_error = 'credit_refunded', updated_at = :t WHERE kind = :k AND state IN ('QUEUED', 'LEASED') "
                    "AND payload->>'reservation_id' = ANY(:r)"), {"t": at, "k": PREMIUM_KIND, "r": revoked})
            if spent:
                # Delivered Premium stays delivered; access policy after refund is an owner decision.
                _entry(conn, owner_id, lot_id, "REFUND_AFTER_SPEND", 0, at, reason=f"spent:{spent}")
        return "refunded"

    def mark_completed(self, owner_id: str, txn_id: str, at: datetime) -> bool:
        with self.db.session(owner_id) as conn:
            return conn.execute(text("UPDATE app.financial_transaction SET completed_at = coalesce(completed_at, :t) "
                                     "WHERE txn_id = :x"), {"t": at, "x": txn_id}).rowcount == 1

    def pending_completions(self, limit: int) -> list[PendingCompletion]:
        """Worker login only (the completion policy spans owners)."""
        with self.db.session() as conn:
            rows = conn.execute(text(
                "SELECT txn_id, rail, transaction_ref, completion_action, owner_id FROM app.financial_transaction "
                "WHERE completed_at IS NULL AND refunded_at IS NULL AND completion_action = ANY(:c) "
                "ORDER BY granted_at LIMIT :n"), {"c": list(SERVER_COMPLETIONS), "n": limit}).all()
        return [PendingCompletion(r[0], PaymentRail(r[1]), r[2], CompletionAction(r[3]), r[4]) for r in rows]

    # --- credits and Premium jobs -----------------------------------------------
    def balance(self, owner_id: str, rails: Sequence[PaymentRail]) -> Balance:
        with self.db.session(owner_id) as conn:
            available = conn.execute(text("SELECT coalesce(sum(available), 0) FROM app.credit_lot "
                                          "WHERE state = 'ACTIVE' AND origin_rail = ANY(:r)"),
                                     {"r": [r.value for r in rails]}).scalar()
            reserved = conn.execute(text("SELECT count(*) FROM app.credit_reservation r JOIN app.credit_lot l "
                                         "ON l.lot_id = r.lot_id WHERE r.state = 'RESERVED' "
                                         "AND l.origin_rail = ANY(:r)"), {"r": [r.value for r in rails]}).scalar()
        return Balance(int(available), int(reserved))

    def reserve_and_enqueue(self, owner_id: str, *, operation_key: str, rails: Sequence[PaymentRail],
                            report_id: str, revision: int, permission_epoch: int, platform: Platform,
                            job_id: str, reservation_id: str, at: datetime) -> PremiumRequest:
        with self.db.session(owner_id) as conn:
            _owner_lock(conn, owner_id)
            lock_live_owner(conn, owner_id)
            existing = conn.execute(text("SELECT r.reservation_id, j.job_id, r.state, j.state FROM "
                                         "app.credit_reservation r JOIN app.job j ON j.dedupe_key = r.operation_key "
                                         "WHERE r.operation_key = :k"), {"k": operation_key}).first()
            if existing is not None:
                if not (existing[2] in ("RELEASED", "REVOKED") and existing[3] in ("FAILED", "CANCELLED")):
                    return PremiumRequest(existing[1], existing[0], False)  # active or published: converge
                # The earlier operation ended without a deliverable and its credit
                # was returned: retire its keys (history stays) and start afresh.
                conn.execute(text("UPDATE app.credit_reservation SET operation_key = operation_key || '#' || "
                                  "reservation_id WHERE reservation_id = :r"), {"r": existing[0]})
                conn.execute(text("UPDATE app.job SET dedupe_key = dedupe_key || '#' || job_id WHERE job_id = :j"),
                             {"j": existing[1]})
            lot_id = conn.execute(text(
                "SELECT lot_id FROM app.credit_lot WHERE state = 'ACTIVE' AND available > 0 "
                "AND origin_rail = ANY(:r) ORDER BY created_at, lot_id LIMIT 1 FOR UPDATE"),
                {"r": [r.value for r in rails]}).scalar()
            if lot_id is None:
                raise NotAuthorized("no_eligible_credit")
            conn.execute(text("UPDATE app.credit_lot SET available = available - 1 WHERE lot_id = :l"), {"l": lot_id})
            conn.execute(text("INSERT INTO app.credit_reservation (reservation_id, owner_id, lot_id, operation_key, "
                              "state, created_at) VALUES (:r, :o, :l, :k, 'RESERVED', :t)"),
                         {"r": reservation_id, "o": owner_id, "l": lot_id, "k": operation_key, "t": at})
            _entry(conn, owner_id, lot_id, "RESERVE", -1, at, reservation_id, "premium")
            conn.execute(text(
                "INSERT INTO app.job (job_id, kind, owner_id, subject_ref, state, dedupe_key, payload, created_at, "
                "updated_at) VALUES (:j, :k, :o, :s, 'QUEUED', :d, CAST(:p AS jsonb), :t, :t)"),
                {"j": job_id, "k": PREMIUM_KIND, "o": owner_id, "s": report_id, "d": operation_key, "t": at,
                 "p": json.dumps({"report_revision": revision, "reservation_id": reservation_id,
                                  "permission_epoch": permission_epoch, "platform": platform.value})})
        return PremiumRequest(job_id, reservation_id, True)

    def premium_status(self, owner_id: str, job_id: str) -> tuple[str, str | None] | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text("SELECT state, last_error FROM app.job WHERE job_id = :j AND kind = :k"),
                               {"j": job_id, "k": PREMIUM_KIND}).first()
        return (row[0], row[1]) if row else None


class PostgresPremiumQueue:
    """Worker-side claim/finish for Premium jobs (``princess_worker`` login)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> PremiumJob | None:
        with self.db.session() as conn:
            row = conn.execute(text(
                "UPDATE app.job SET state = 'LEASED', lease_owner = :w, lease_expires_at = :exp, "
                "fencing_token = fencing_token + 1, attempts = attempts + 1, updated_at = :now "
                "WHERE job_id = (SELECT job_id FROM app.job WHERE kind = :k AND attempts < :max AND "
                "(state = 'QUEUED' OR (state = 'LEASED' AND lease_expires_at < :now)) "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING job_id, owner_id, subject_ref, fencing_token, attempts, payload"),
                {"w": worker_id, "exp": now + timedelta(seconds=lease_seconds), "now": now,
                 "k": PREMIUM_KIND, "max": MAX_ATTEMPTS}).mappings().first()
        if row is None:
            return None
        payload = row["payload"]
        return PremiumJob(row["job_id"], row["owner_id"], row["subject_ref"], int(payload["report_revision"]),
                          int(payload["permission_epoch"]), int(row["attempts"]),
                          fencing_token=int(row["fencing_token"]), reservation_id=payload["reservation_id"])

    def reap(self, now: datetime, limit: int = 20) -> int:
        """Terminalize jobs whose last permitted attempt lost its lease (a
        crashed worker never reaches ``finish``) and release their credits.
        Such an attempt may still have executed remotely; that cost is ours."""
        with self.db.session() as conn:
            rows = conn.execute(text(
                "UPDATE app.job SET state = 'FAILED', lease_owner = NULL, lease_expires_at = NULL, "
                "last_error = 'attempts_exhausted', updated_at = :now WHERE job_id IN (SELECT job_id FROM app.job "
                "WHERE kind = :k AND state = 'LEASED' AND lease_expires_at < :now AND attempts >= :max "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :n) RETURNING owner_id, payload"),
                {"now": now, "k": PREMIUM_KIND, "max": MAX_ATTEMPTS, "n": limit}).all()
            for owner_id, payload in rows:
                set_context(conn, owner_id)
                release_reservation(conn, owner_id, payload["reservation_id"], "attempts_exhausted", now)
            set_context(conn, None)
        return len(rows)

    def finish(self, job: PremiumJob, record: AttemptRecord, now: datetime) -> str:
        """Settle the job after an attempt. Success was already committed by the
        publisher; anything else requeues (bounded) or fails and releases the credit."""
        if record.outcome is Outcome.SUCCEEDED:
            return "SUCCEEDED"
        retry = record.outcome in (Outcome.RETRYABLE, Outcome.AMBIGUOUS) and job.attempt_number < MAX_ATTEMPTS
        with self.db.session() as conn:
            current = conn.execute(text("SELECT state, fencing_token FROM app.job WHERE job_id = :j FOR UPDATE"),
                                   {"j": job.job_id}).first()
            if current is None or current[1] != job.fencing_token or current[0] != "LEASED":
                return "FENCED"  # another worker owns this job now
            state = "QUEUED" if retry else "FAILED"
            conn.execute(text("UPDATE app.job SET state = :s, lease_owner = NULL, lease_expires_at = NULL, "
                              "last_error = :c, updated_at = :t WHERE job_id = :j"),
                         {"s": state, "c": record.error_code, "t": now, "j": job.job_id})
            if not retry and job.reservation_id:
                set_context(conn, job.owner_id)
                release_reservation(conn, job.owner_id, job.reservation_id, record.error_code or "failed", now)
        return state


class PostgresOverlayPublisher:
    """Publishes a validated overlay and spends its reservation in one fenced transaction."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def publish(self, job: PremiumJob, overlay: PremiumOverlay, now: datetime) -> int:
        with self.db.session() as conn:
            row = conn.execute(text("SELECT state, fencing_token, lease_expires_at FROM app.job WHERE job_id = :j "
                                    "FOR UPDATE"), {"j": job.job_id}).first()
            if row is None or row[1] != job.fencing_token:
                raise Fenced("stale_fencing_token")
            if row[0] != "LEASED" or row[2] <= now:
                raise Fenced("lease_lost")
            set_context(conn, job.owner_id)
            try:
                lock_live_owner(conn, job.owner_id)
            except NotFound:
                raise Fenced("owner_deleted") from None
            if epoch_for(conn, job.owner_id, AI_PURPOSE, lock=True) != job.permission_epoch:
                raise Fenced("permission_changed")
            if conn.execute(text("SELECT 1 FROM app.report WHERE report_id = :r AND deleted_at IS NULL FOR UPDATE"),
                            {"r": job.report_id}).scalar() is None:
                raise Fenced("report_deleted")
            prior = conn.execute(text("SELECT document FROM app.report_revision WHERE report_id = :r "
                                      "ORDER BY revision DESC LIMIT 1"), {"r": job.report_id}).scalar()
            previous = compile_document("ReportDocument", prior).value if prior is not None else None
            if previous is None or previous.data["revision"] != job.report_revision:
                raise Fenced("report_revised")
            spent = conn.execute(text("UPDATE app.credit_reservation SET state = 'SPENT', settled_at = :t "
                                      "WHERE reservation_id = :r AND state = 'RESERVED' RETURNING lot_id"),
                                 {"t": now, "r": job.reservation_id}).scalar()
            if spent is None:
                raise Fenced("reservation_not_active")  # refunded, released or already spent
            revised = revise_report(previous, created_at=now, premium_overlay_id=overlay.overlay_id)
            if revised.value is None or check_revision(previous, revised.value):
                raise Fenced("revision_rejected")
            document = revised.value
            conn.execute(text("INSERT INTO app.report_revision (report_id, revision, owner_id, digest, document, "
                              "created_at) VALUES (:r, :v, :o, :d, CAST(:doc AS jsonb), :t)"),
                         {"r": job.report_id, "v": document.data["revision"], "o": job.owner_id, "d": document.digest,
                          "doc": json.dumps(document.to_dict()), "t": now})
            conn.execute(text(
                "INSERT INTO app.premium_overlay (overlay_id, owner_id, report_id, revision, job_id, reservation_id, "
                "packet_digest, output_digest, packet, output, omissions, model_returned, created_at) VALUES "
                "(:id, :o, :r, :v, :j, :res, :pd, :od, CAST(:p AS jsonb), CAST(:out AS jsonb), CAST(:om AS jsonb), "
                ":m, :t)"),
                {"id": overlay.overlay_id, "o": job.owner_id, "r": job.report_id, "v": document.data["revision"],
                 "j": job.job_id, "res": job.reservation_id, "pd": overlay.packet.digest,
                 "od": overlay.output.digest, "p": json.dumps(overlay.packet.to_dict()),
                 "out": json.dumps(overlay.output.to_dict()),
                 "om": json.dumps([{"item_id": o.item_id, "reason": o.reason, "detail": o.detail}
                                   for o in overlay.omissions]), "m": overlay.model_returned, "t": now})
            _entry(conn, job.owner_id, spent, "SPEND", 0, now, job.reservation_id, "premium_published")
            set_context(conn, None)
            conn.execute(text("UPDATE app.job SET state = 'SUCCEEDED', lease_owner = NULL, lease_expires_at = NULL, "
                              "last_error = NULL, updated_at = :t WHERE job_id = :j"), {"t": now, "j": job.job_id})
        return document.data["revision"]


class PostgresImageSource:
    """The report's source image while its capture exists and the original was retained."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def authorized_image(self, owner_id: str, report) -> StoredObject | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text(
                "SELECT a.asset_id, a.version_ref, a.sha256, a.size_bytes, a.media_type FROM app.analysis_run r "
                "JOIN app.capture c ON c.capture_id = r.capture_id JOIN app.asset a ON a.asset_id = c.asset_id "
                "WHERE r.run_id = :run AND c.deleted_at IS NULL AND a.deleted_at IS NULL"),
                {"run": report.data["analysis"]["run_id"]}).first()
        return StoredObject(*row) if row else None


__all__ = ["PREMIUM_KIND", "PostgresImageSource", "PostgresLedger", "PostgresOverlayPublisher",
           "PostgresPremiumQueue", "release_reservation"]
