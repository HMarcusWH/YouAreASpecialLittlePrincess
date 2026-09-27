"""T24 notifications: outbox-planned, best-effort delivery that never touches business state."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from princess_app.adapters.fakes import FakeMailer, FakePushProvider, SequentialIds
from princess_app.adapters.postgres.notifications import PostgresNotificationRepository
from princess_app.application.notifications import (
    MAIL,
    MAX_ATTEMPTS,
    MAX_INSTALLATIONS,
    PUSH,
    REPORT_READY_TOPIC,
    NotificationService,
    NotificationWorker,
)
from princess_app.ports.base import (
    AmbiguousOutcome,
    CallContext,
    Environment,
    InvalidInput,
    NotAuthorized,
    TransientUnavailable,
    Unauthenticated,
)
from test_intake import Env, erasure
from test_persistence import account, ctx, world  # noqa: F401 - fixture re-export

TOKEN_A, TOKEN_B = "a" * 64, "fcm-token:" + "b" * 60


class Rig:
    def __init__(self, app_db, worker_db, world):  # noqa: F811
        self.env = env = Env(app_db, worker_db)
        self.world = world
        self.service = NotificationService(repo=PostgresNotificationRepository(app_db), clock=env.clock,
                                           ids=SequentialIds(), environment=Environment.TEST)
        self.repo = PostgresNotificationRepository(worker_db)
        self.mailer = FakeMailer(clock=env.clock, accept_any_recipient=True)
        self.push = FakePushProvider(clock=env.clock)
        self.enabled = True
        self.worker = NotificationWorker(
            repo=self.repo, clock=env.clock, environment=Environment.TEST,
            context=lambda key: CallContext("corr-n", Environment.TEST, env.clock.now() + timedelta(seconds=30),
                                            operation_key=key),
            mailer=self.mailer, push=self.push, enabled=lambda: self.enabled)

    def principal(self, subject):
        return account(self.world, subject)

    def report(self, owner_id):
        capture, run_id = self.env.analysis(owner_id)
        assert self.env.worker().run_once().outcome == "SUCCEEDED"
        return capture, self.env.intake.status(owner_id, run_id).report_id

    def register(self, who, token=TOKEN_A, platform="apns"):
        return self.service.register(who, token, platform, "test", "sv-SE")

    def plan(self):
        return self.repo.plan(REPORT_READY_TOPIC, frozenset({MAIL, PUSH}), Environment.TEST, self.env.clock.now(), 20)

    def rows(self, sql, **params):
        with self.env.worker_db.session() as conn:
            return conn.execute(text(sql), params).all()


@pytest.fixture
def rig(app_db, worker_db, world):  # noqa: F811
    return Rig(app_db, worker_db, world)


def test_report_ready_reaches_bound_devices_and_opted_in_mail_exactly_once(rig):
    who = rig.principal("sub-n1")
    rig.register(who)
    rig.register(who, TOKEN_B, "fcm")
    rig.service.set_preferences(who, True, "sv-SE")
    _, report_id = rig.report(who.principal_id)

    outcomes = rig.worker.run_once()
    assert sorted((o.channel, o.state) for o in outcomes) == [(MAIL, "ACCEPTED"), (PUSH, "ACCEPTED"),
                                                              (PUSH, "ACCEPTED")]
    assert {m.object_ref for _, m in rig.push.delivered} == {report_id}
    assert {m.kind for _, m in rig.push.delivered} == {"report_ready"}
    [mail] = rig.mailer.sent
    assert (mail.recipient_ref, mail.locale, dict(mail.safe_variables)) == (
        who.principal_id, "sv-SE", {"app_link": f"app://reports/{report_id}"})

    # A replayed event (restore, crash before dispatch) plans nothing new.
    rig.rows("UPDATE app.outbox_event SET dispatched_at = NULL WHERE topic = 'report.ready' RETURNING 1")
    assert rig.worker.run_once() == []
    assert len(rig.push.delivered) == 2 and len(rig.mailer.sent) == 1


def test_tokens_are_worker_only_and_bindings_owner_scoped(rig):
    who, other = rig.principal("sub-n2"), rig.principal("sub-n3")
    first = rig.register(who)
    assert rig.register(who) == first  # a relaunch re-registers the same binding
    with rig.env.app_db.session(who.principal_id) as conn:
        with pytest.raises(ProgrammingError):
            conn.execute(text("SELECT device_token FROM app.push_installation"))
    assert [i.installation_id for i in rig.service.installations(who.principal_id)] == [first]
    assert rig.service.installations(other.principal_id) == []
    rig.service.unregister(other.principal_id, first)  # someone else's binding is untouched
    assert len(rig.service.installations(who.principal_id)) == 1
    for i in range(MAX_INSTALLATIONS + 1):
        rig.env.clock.advance(1)
        rig.register(who, f"token-{i:04d}-" + "c" * 40, "fcm")
    kept = rig.service.installations(who.principal_id)
    assert len(kept) == MAX_INSTALLATIONS and first not in {i.installation_id for i in kept}


@pytest.mark.parametrize("token,platform,environment,locale", [
    ("short", "apns", "test", "en"), (TOKEN_A, "mpns", "test", "en"),
    (TOKEN_A, "apns", "production", "en"), (TOKEN_A, "apns", "test", "english"),
])
def test_registration_rejects_malformed_or_wrong_environment_devices(rig, token, platform, environment, locale):
    with pytest.raises(InvalidInput):
        rig.service.register(rig.principal("sub-n4"), token, platform, environment, locale)


def test_logout_account_switch_and_deleted_report_drop_queued_notices(rig):
    alice, bob = rig.principal("sub-n5"), rig.principal("sub-n6")
    installation = rig.register(alice)
    capture, _ = rig.report(alice.principal_id)
    assert rig.plan() == 1
    rig.service.unregister(alice.principal_id, installation)  # logout on the device
    assert rig.worker.run_once() == [] and rig.push.delivered == []

    rig.register(alice)
    rig.report(alice.principal_id)
    assert rig.plan() == 1
    rig.register(bob)  # the same device signs in as someone else
    assert rig.service.installations(alice.principal_id) == []
    assert rig.worker.run_once() == [] and rig.push.delivered == []  # alice's notice never reaches bob's device

    rig.service.set_preferences(alice, True, "en")
    rig.register(alice, TOKEN_B, "fcm")
    capture, _ = rig.report(alice.principal_id)
    assert rig.plan() == 2
    rig.env.intake.delete_capture(alice.principal_id, capture.capture_id)
    assert "ERASED" in {o.action for o in erasure(rig.env).run_once()}
    assert rig.worker.run_once() == []  # the report went, and its notices with it
    assert rig.mailer.sent == [] and rig.push.delivered == []


def test_outages_retry_with_backoff_and_give_up_without_touching_state(rig):
    who = rig.principal("sub-n7")
    rig.register(who)
    rig.service.set_preferences(who, True, "en")
    rig.push.faults.inject("send", TransientUnavailable("apns_unavailable"))
    rig.mailer.faults.inject("send", Unauthenticated("key_revoked"), times=MAX_ATTEMPTS)
    rig.report(who.principal_id)

    outcomes = {o.channel: o for o in rig.worker.run_once()}
    assert (outcomes[PUSH].state, outcomes[PUSH].outcome) == ("RETRY", "apns_unavailable")
    assert (outcomes[MAIL].state, outcomes[MAIL].outcome) == ("RETRY", "provider_auth")
    assert rig.worker.run_once() == []  # backing off
    rig.env.clock.advance(31)
    states = {o.channel: o.state for o in rig.worker.run_once()}
    assert states == {PUSH: "ACCEPTED", MAIL: "RETRY"}
    for delay in (60, 120, 240):
        rig.env.clock.advance(delay + 1)
        [outcome] = rig.worker.run_once()
    assert (outcome.state, outcome.outcome) == ("FAILED", "attempts_exhausted")
    assert rig.mailer.sent == [] and len(rig.push.delivered) == 1
    assert rig.env.repo.captures(who.principal_id)  # business state untouched


def test_ambiguous_mail_retries_on_the_same_key_but_ambiguous_push_does_not(rig):
    who = rig.principal("sub-n8")
    rig.register(who)
    rig.service.set_preferences(who, True, "en")
    rig.mailer.faults.inject("send", AmbiguousOutcome("timeout_after_send"), after_effect=True)
    rig.push.faults.inject("send", AmbiguousOutcome("timeout_after_send"), after_effect=True)
    rig.report(who.principal_id)
    outcomes = {o.channel: (o.state, o.outcome) for o in rig.worker.run_once()}
    assert outcomes == {MAIL: ("RETRY", "ambiguous"), PUSH: ("FAILED", "ambiguous")}
    rig.env.clock.advance(31)
    [retry] = rig.worker.run_once()
    assert retry.state == "ACCEPTED" and len(rig.mailer.sent) == 1  # provider deduplicated the key
    assert len(rig.push.delivered) == 1  # sent once, never repeated


def test_stale_notices_are_dropped_and_the_kill_switch_consumes_without_sending(rig):
    who = rig.principal("sub-n9")
    rig.register(who)
    rig.report(who.principal_id)
    assert rig.plan() == 1
    rig.env.clock.advance(25 * 3600)
    assert [(o.state, o.outcome) for o in rig.worker.run_once()] == [("SKIPPED", "stale")]

    rig.enabled = False
    rig.report(who.principal_id)
    assert rig.worker.run_once() == []
    rig.enabled = True
    assert rig.worker.run_once() == [] and rig.push.delivered == []  # no backlog of late notices
    assert not rig.rows("SELECT 1 FROM app.outbox_event WHERE topic = 'report.ready' AND dispatched_at IS NULL")


def test_unregistered_tokens_retire_and_suppressed_recipients_are_not_mailed(rig):
    who = rig.principal("sub-n10")
    rig.register(who)
    rig.service.set_preferences(who, True, "en")
    rig.push.invalidate_token(TOKEN_A)
    rig.mailer.suppressed.add(who.principal_id)
    rig.report(who.principal_id)
    outcomes = {o.channel: (o.state, o.outcome) for o in rig.worker.run_once()}
    assert outcomes == {PUSH: ("FAILED", "unregistered"), MAIL: ("SUPPRESSED", "provider_suppressed")}
    assert rig.service.installations(who.principal_id) == []
    calls = len(rig.mailer.calls)
    rig.report(who.principal_id)
    assert [(o.state, o.outcome) for o in rig.worker.run_once()] == [("SUPPRESSED", "suppressed")]
    assert len(rig.mailer.calls) == calls  # our own record stops the call
    assert rig.repo.unsuppress(who.principal_id)


def test_guests_get_push_but_not_mail_and_withdrawn_opt_in_stops_mail(rig):
    clock, _, identity = rig.world
    guest, _ = identity.create_guest()
    with pytest.raises(NotAuthorized):
        rig.service.set_preferences(guest, True, "en")
    assert rig.register(guest)
    who = rig.principal("sub-n11")
    rig.service.set_preferences(who, True, "en")
    rig.report(who.principal_id)
    assert rig.plan() == 1
    rig.service.set_preferences(who, False, "en")
    assert [(o.state, o.outcome) for o in rig.worker.run_once()] == [("SKIPPED", "not_opted_in")]


def test_account_deletion_skips_queued_notices_and_erasure_removes_every_record(rig):
    clock, _, identity = rig.world
    who = rig.principal("sub-n12")
    rig.register(who)
    rig.service.set_preferences(who, True, "en")
    rig.report(who.principal_id)
    assert rig.plan() == 2
    identity.delete_account(who, ctx(clock))
    assert {(o.state, o.outcome) for o in rig.worker.run_once()} == {("SKIPPED", "owner_gone")}
    assert "ERASED" in {o.action for o in erasure(rig.env).run_once()}
    for table, column in (("push_installation", "owner_id"), ("notification_delivery", "owner_id"),
                          ("notification_preference", "owner_id"), ("mail_suppression", "recipient_ref")):
        assert not rig.rows(f"SELECT 1 FROM app.{table} WHERE {column} = :o", o=who.principal_id), table
    assert rig.mailer.sent == [] and rig.push.delivered == []


def test_guest_devices_follow_the_sign_in_and_are_erased_with_the_account(rig):
    clock, _, identity = rig.world
    guest, token = identity.create_guest()
    installation = rig.register(guest)
    who = rig.principal("sub-n13")
    identity.transfer_guest(who, token)
    assert [i.installation_id for i in rig.service.installations(who.principal_id)] == [installation]
    assert rig.service.installations(guest.principal_id) == []
    rig.report(who.principal_id)
    assert [(o.channel, o.state) for o in rig.worker.run_once()] == [(PUSH, "ACCEPTED")]
    identity.delete_account(who, ctx(clock))
    assert "ERASED" in {o.action for o in erasure(rig.env).run_once()}
    assert not rig.rows("SELECT 1 FROM app.push_installation WHERE installation_id = :i", i=installation)
