"""PostgreSQL notification bindings, preferences and delivery records (T24).

Owner operations run as ``princess_app`` in the owner's RLS context and can
never read a device token back. Planning, claiming and completing run as the
notification worker (``princess_worker``); planning switches to each event
owner's context so it sees only that owner's report and principal rows.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ...application.notifications import MAIL, PUSH, REPORT_READY, ClaimedDelivery, Installation, Preferences
from ...ports.base import Environment, InvalidInput, NotAuthorized, PortError
from ...ports.messaging import PushPlatform, PushTarget
from .stores import Database, set_context


def delivery_key(event_id: str, target: str) -> str:
    return "ntf_" + hashlib.sha256(f"{event_id}\0{target}".encode("utf-8")).hexdigest()[:40]


class PostgresNotificationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- owner side -----------------------------------------------------------------
    def bind(self, owner_id: str, installation_id: str, platform: PushPlatform, environment: Environment,
             device_token: str, locale: str, at: datetime, max_installations: int) -> str:
        with self.db.session(owner_id) as conn:
            try:
                return conn.execute(text("SELECT app.bind_push_installation(:i, :p, :e, :t, :l, :a, :m)"),
                                    {"i": installation_id, "p": platform.value, "e": environment.value,
                                     "t": device_token, "l": locale, "a": at, "m": max_installations}).scalar()
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == "42501":  # deleted or transferred principal
                    raise NotAuthorized("principal_required") from None
                raise

    def installations(self, owner_id: str) -> list[Installation]:
        with self.db.session(owner_id) as conn:
            rows = conn.execute(text("SELECT installation_id, platform, app_environment, locale, registered_at "
                                     "FROM app.push_installation ORDER BY registered_at DESC, installation_id"))
            return [Installation(r.installation_id, PushPlatform(r.platform), Environment.parse(r.app_environment),
                                 r.locale, r.registered_at) for r in rows]

    def unbind(self, owner_id: str, installation_id: str) -> bool:
        with self.db.session(owner_id) as conn:
            return conn.execute(text("DELETE FROM app.push_installation WHERE installation_id = :i"),
                                {"i": installation_id}).rowcount == 1

    def unbind_all(self, owner_id: str, registered_before: datetime | None = None) -> int:
        with self.db.session(owner_id) as conn:  # RLS: the owner's bindings only
            if registered_before is None:
                return conn.execute(text("DELETE FROM app.push_installation")).rowcount
            return conn.execute(text("DELETE FROM app.push_installation WHERE registered_at <= :b"),
                                {"b": registered_before}).rowcount

    def preferences(self, owner_id: str) -> Preferences | None:
        with self.db.session(owner_id) as conn:
            row = conn.execute(text("SELECT mail_report_ready, locale FROM app.notification_preference")).first()
        return Preferences(row.mail_report_ready, row.locale) if row else None

    def set_preferences(self, owner_id: str, preferences: Preferences, at: datetime) -> None:
        with self.db.session(owner_id) as conn:
            conn.execute(text(
                "INSERT INTO app.notification_preference (owner_id, mail_report_ready, locale, updated_at) "
                "VALUES (:o, :m, :l, :t) ON CONFLICT (owner_id) DO UPDATE SET mail_report_ready = EXCLUDED."
                "mail_report_ready, locale = EXCLUDED.locale, updated_at = EXCLUDED.updated_at"),
                {"o": owner_id, "m": preferences.mail_report_ready, "l": preferences.locale, "t": at})

    # -- worker side ----------------------------------------------------------------
    def plan(self, topic: str, channels: frozenset[str], environment: Environment, now: datetime,
             limit: int) -> int:
        planned = 0
        with self.db.session() as conn:
            events = conn.execute(text(
                "SELECT event_id, owner_id, aggregate_ref, created_at FROM app.outbox_event "
                "WHERE topic = :t AND dispatched_at IS NULL ORDER BY created_at LIMIT :n FOR UPDATE SKIP LOCKED"),
                {"t": topic, "n": limit}).all()
            for event in events:
                if event.owner_id is not None:
                    planned += self._plan_event(conn, event, channels, environment, now)
            if events:
                set_context(conn, None)
                conn.execute(text("UPDATE app.outbox_event SET dispatched_at = :n WHERE event_id = ANY(:e)"),
                             {"n": now, "e": [e.event_id for e in events]})
        return planned

    def _plan_event(self, conn, event, channels: frozenset[str], environment: Environment, now: datetime) -> int:
        set_context(conn, event.owner_id)  # the owner's report and principal rows only
        live = conn.execute(text(
            "SELECT p.kind FROM app.principal p JOIN app.report r ON r.owner_id = p.principal_id "
            "AND r.report_id = :r WHERE p.principal_id = :o AND p.deleted_at IS NULL AND p.transferred_to IS NULL"),
            {"o": event.owner_id, "r": event.aggregate_ref}).scalar()
        if live is None:
            return 0  # the report or its owner is already gone
        targets: list[tuple[str, str | None]] = []
        if PUSH in channels:
            targets += [(PUSH, i) for i in conn.execute(text(
                "SELECT installation_id FROM app.push_installation WHERE owner_id = :o AND app_environment = :e "
                "ORDER BY installation_id"), {"o": event.owner_id, "e": environment.value}).scalars()]
        if MAIL in channels and live == "ACCOUNT" and conn.execute(text(
                "SELECT mail_report_ready FROM app.notification_preference WHERE owner_id = :o"),
                {"o": event.owner_id}).scalar():
            targets.append((MAIL, None))
        planned = 0
        for channel, installation_id in targets:
            planned += conn.execute(text(
                "INSERT INTO app.notification_delivery (delivery_key, owner_id, report_id, channel, kind, "
                "installation_id, state, not_before, created_at) VALUES (:k, :o, :r, :c, :kind, :i, 'PENDING', :n, "
                ":created) ON CONFLICT (delivery_key) DO NOTHING"),
                {"k": delivery_key(event.event_id, installation_id or "mail"), "o": event.owner_id,
                 "r": event.aggregate_ref, "c": channel, "kind": REPORT_READY, "i": installation_id, "n": now,
                 "created": event.created_at}).rowcount
        return planned

    def claim(self, now: datetime, lease_until: datetime, limit: int) -> list[ClaimedDelivery]:
        with self.db.session() as conn:
            rows = conn.execute(text(
                "WITH due AS (SELECT delivery_key FROM app.notification_delivery WHERE state = 'PENDING' "
                "AND not_before <= :n AND (lease_until IS NULL OR lease_until <= :n) ORDER BY not_before "
                "LIMIT :m FOR UPDATE SKIP LOCKED) "
                "UPDATE app.notification_delivery d SET lease_until = :l, attempts = d.attempts + 1 FROM due "
                "WHERE d.delivery_key = due.delivery_key RETURNING d.delivery_key, d.owner_id, d.report_id, "
                "d.channel, d.kind, d.installation_id, d.attempts, d.created_at"),
                {"n": now, "l": lease_until, "m": limit}).all()
            return [self._facts(conn, row) for row in rows]

    def _facts(self, conn, row) -> ClaimedDelivery:
        set_context(conn, row.owner_id)
        kind = conn.execute(text("SELECT kind FROM app.principal WHERE principal_id = :o AND deleted_at IS NULL "
                                 "AND transferred_to IS NULL"), {"o": row.owner_id}).scalar()
        base = dict(delivery_key=row.delivery_key, owner_id=row.owner_id, report_id=row.report_id,
                    channel=row.channel, kind=row.kind, attempts=row.attempts, created_at=row.created_at,
                    owner_kind=kind)
        if row.channel == PUSH:
            device = conn.execute(text(
                "SELECT owner_id, platform, app_environment, device_token, locale FROM app.push_installation "
                "WHERE installation_id = :i"), {"i": row.installation_id}).first()
            target = None
            if device is not None and device.owner_id == row.owner_id:
                try:
                    target = PushTarget(device.device_token, PushPlatform(device.platform),
                                        Environment.parse(device.app_environment))
                except (PortError, ValueError):
                    target = None
            return ClaimedDelivery(**base, locale=device.locale if device else "en", target=target,
                                   installation_id=row.installation_id)
        preference = conn.execute(text("SELECT mail_report_ready, locale FROM app.notification_preference "
                                       "WHERE owner_id = :o"), {"o": row.owner_id}).first()
        suppressed = conn.execute(text("SELECT 1 FROM app.mail_suppression WHERE recipient_ref = :o"),
                                  {"o": row.owner_id}).first() is not None
        return ClaimedDelivery(**base, locale=preference.locale if preference else "en",
                               mail_opt_in=bool(preference and preference.mail_report_ready), suppressed=suppressed)

    def complete(self, delivery_key: str, state: str, outcome: str, provider_ref: str | None,
                 at: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(text(
                "UPDATE app.notification_delivery SET state = :s, outcome = :o, provider_message_ref = :p, "
                "completed_at = :t, lease_until = NULL WHERE delivery_key = :k AND state = 'PENDING'"),
                {"s": state, "o": outcome, "p": provider_ref, "t": at, "k": delivery_key})

    def retry(self, delivery_key: str, not_before: datetime, outcome: str) -> None:
        with self.db.session() as conn:
            conn.execute(text(
                "UPDATE app.notification_delivery SET not_before = :n, outcome = :o, lease_until = NULL "
                "WHERE delivery_key = :k AND state = 'PENDING'"), {"n": not_before, "o": outcome, "k": delivery_key})

    def retire_installation(self, installation_id: str) -> None:
        with self.db.session() as conn:
            conn.execute(text("DELETE FROM app.push_installation WHERE installation_id = :i"), {"i": installation_id})

    def suppress(self, recipient_ref: str, reason: str, at: datetime) -> None:
        if reason not in ("BOUNCE", "COMPLAINT", "PROVIDER", "MANUAL"):
            raise InvalidInput("unknown_suppression_reason")
        with self.db.session() as conn:
            conn.execute(text(
                "INSERT INTO app.mail_suppression (recipient_ref, reason, recorded_at) VALUES (:r, :why, :t) "
                "ON CONFLICT (recipient_ref) DO NOTHING"), {"r": recipient_ref, "why": reason, "t": at})

    def unsuppress(self, recipient_ref: str) -> bool:
        with self.db.session() as conn:
            return conn.execute(text("DELETE FROM app.mail_suppression WHERE recipient_ref = :r"),
                                {"r": recipient_ref}).rowcount == 1

    def expire(self, completed_before: datetime, limit: int) -> int:
        with self.db.session() as conn:
            return conn.execute(text(
                "DELETE FROM app.notification_delivery WHERE delivery_key IN (SELECT delivery_key FROM "
                "app.notification_delivery WHERE state <> 'PENDING' AND completed_at < :t ORDER BY completed_at "
                "LIMIT :n)"), {"t": completed_before, "n": limit}).rowcount


__all__ = ["PostgresNotificationRepository", "delivery_key"]
