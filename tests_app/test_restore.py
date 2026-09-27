"""T24: a database restore cannot undo deletions, withdrawals or "log out everywhere"."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from princess_app.adapters.fakes import SequentialIds
from princess_app.adapters.localfs.tombstones import JsonlTombstoneLog
from princess_app.adapters.postgres.notifications import PostgresNotificationRepository
from princess_app.adapters.postgres.stores import PostgresIdentityStore, PostgresReportStore
from princess_app.application.erasure import ErasureWorker
from princess_app.application.notifications import NotificationService
from princess_app.application.tombstones import (
    ACCOUNT_DELETED,
    CAPTURE_DELETED,
    PERMISSION_WITHDRAWN,
    SESSIONS_REVOKED,
    Tombstone,
    merged_expansion,
    replay,
)
from princess_app.domain.permissions import Decision, Scope
from princess_app.ports.base import Environment
from test_intake import NOTICE, Env, erasure
from test_persistence import T0, account, world  # noqa: F401 - fixture re-export

AI = "third_party_ai_processing"


@pytest.fixture
def env(app_db, worker_db):
    return Env(app_db, worker_db)


def restore_to_before_the_deletions(admin_engine, owner, capture_id, report_id, deleted_account):
    """What a backup taken just before the deletions looks like once restored."""
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE app.capture SET deleted_at = NULL WHERE capture_id = :c"), {"c": capture_id})
        conn.execute(text("UPDATE app.report SET deleted_at = NULL WHERE report_id = :r"), {"r": report_id})
        conn.execute(text("UPDATE app.principal SET deleted_at = NULL, revoked_before = NULL "
                          "WHERE principal_id = :p"), {"p": deleted_account})
        conn.execute(text("DELETE FROM app.outbox_event WHERE topic IN ('capture.deletion_requested', "
                          "'account.deletion_requested')"))


def test_replaying_tombstones_after_a_restore_deletes_again(env, world, admin_engine, tmp_path):  # noqa: F811
    log = JsonlTombstoneLog(tmp_path)
    identity = PostgresIdentityStore(env.app_db)
    owner = account(world, "sub-a").principal_id
    capture, run_id = env.analysis(owner)
    assert env.worker().run_once().outcome == "SUCCEEDED"
    report_id = env.intake.status(owner, run_id).report_id
    leaving = account(world, "sub-b").principal_id
    # The API commits each deletion and records its tombstone outside the database.
    env.intake.delete_capture(owner, capture.capture_id)
    log.append(Tombstone(CAPTURE_DELETED, owner, capture.capture_id, env.clock.now()))
    identity.mark_deleted(leaving, env.clock.now())
    log.append(Tombstone(ACCOUNT_DELETED, leaving, leaving, env.clock.now()))

    restore_to_before_the_deletions(admin_engine, owner, capture.capture_id, report_id, leaving)
    assert PostgresReportStore(env.app_db, owner).latest(report_id) is not None  # resurrected by the restore
    assert identity.principal(leaving).deleted_at is None

    result = replay(log, identity, env.repo, env.permissions)
    assert (result.reapplied, result.already, result.unknown) == (2, 0, 0)
    assert PostgresReportStore(env.app_db, owner).latest(report_id) is None
    assert identity.principal(leaving).deleted_at is not None
    assert "ERASED" in {o.action for o in erasure(env).run_once()}  # erasure runs again, idempotently
    assert env.store.verify_deletion(capture.asset_id, env.ctx())
    again = replay(log, identity, env.repo, env.permissions)
    assert (again.reapplied, again.already) == (0, 2)


def test_the_erasure_worker_records_tombstones_before_erasing(env, world, tmp_path):  # noqa: F811
    log = JsonlTombstoneLog(tmp_path)
    owner = account(world, "sub-a").principal_id
    capture = env.capture(owner)
    env.intake.delete_capture(owner, capture.capture_id)  # the API's own append "failed"
    base = erasure(env)
    worker = ErasureWorker(outbox=base._outbox, store=env.store, permissions=base._permissions,
                           clock=env.clock, context=env.ctx, tombstones=log)
    assert "ERASED" in {o.action for o in worker.run_once()}
    assert [(t.kind, t.ref) for t in log.entries()] == [(CAPTURE_DELETED, capture.capture_id)]

    class Unwritable:
        def append(self, tombstone):
            raise OSError("disk full")

    broken = ErasureWorker(outbox=base._outbox, store=env.store, permissions=base._permissions,
                           clock=env.clock, context=env.ctx, tombstones=Unwritable())
    other = env.capture(owner)
    env.intake.delete_capture(owner, other.capture_id)
    # The log cannot be written, so the event stays pending and nothing is erased yet.
    assert {o.action for o in broken.run_once()} == {"UNVERIFIED"}
    assert not env.store.verify_deletion(other.asset_id, env.ctx())
    assert "ERASED" in {o.action for o in worker.run_once()}  # retried once the log is writable


def recording(env, log):
    """The erasure worker as deployed: propagation and the tombstone log composed."""
    base = erasure(env)
    return ErasureWorker(outbox=base._outbox, store=env.store, permissions=base._permissions, clock=env.clock,
                         context=env.ctx, propagate=base._propagate, tombstones=log)


def test_a_torn_write_costs_one_line_and_never_blocks_the_replay(tmp_path):
    log = JsonlTombstoneLog(tmp_path)
    log.append(Tombstone(ACCOUNT_DELETED, "prn_1", "prn_1", T0))
    log.append(Tombstone(ACCOUNT_DELETED, "prn_1", "prn_1", T0))  # duplicates are harmless
    with open(log.path, "ab") as f:
        f.write(b'\n{"kind": "CAPTURE_DEL')  # a crash mid-write
    assert [t.owner_id for t in log.read().tombstones] == ["prn_1", "prn_1"]
    assert log.read().unreadable == 0  # an unfinished final line is not an error
    log.append(Tombstone(CAPTURE_DELETED, "prn_2", "cap_2", T0))  # the next write after the crash
    contents = log.read()
    assert [t.owner_id for t in contents.tombstones] == ["prn_1", "prn_1", "prn_2"]
    assert contents.unreadable == 1  # reported, not silently dropped, and nothing after it is lost


def test_merged_guests_are_tombstoned_so_a_pre_merge_backup_cannot_bring_them_back(env, world, tmp_path):  # noqa: F811
    clock, _, identity = world
    store = PostgresIdentityStore(env.app_db)
    log = JsonlTombstoneLog(tmp_path)
    guest, token = identity.create_guest()
    capture = env.capture(guest.principal_id)
    owner = account(world, "sub-merge")
    identity.transfer_guest(owner, token)
    env.intake.delete_capture(owner.principal_id, capture.capture_id)
    store.mark_deleted(owner.principal_id, env.clock.now())
    recording(env, log).run_once()
    written = {(t.kind, t.owner_id, t.ref) for t in log.read().tombstones}
    assert {(CAPTURE_DELETED, guest.principal_id, capture.capture_id),
            (ACCOUNT_DELETED, guest.principal_id, guest.principal_id)} <= written
    # Against the current database the guest's copy was merged away already.
    now = replay(log, store, env.repo, env.permissions)
    assert now.reapplied == 0 and now.unreadable == 0

    # A restore from before the merge holds the guest and its capture untouched.
    unmerged, _ = identity.create_guest()
    kept = env.capture(unmerged.principal_id)
    old_log = JsonlTombstoneLog(tmp_path / "pre-merge")
    for t in (merged_expansion(CAPTURE_DELETED, "prn_account", kept.capture_id, env.clock.now(),
                               [unmerged.principal_id])
              + merged_expansion(ACCOUNT_DELETED, "prn_account", "prn_account", env.clock.now(),
                                 [unmerged.principal_id])):
        old_log.append(t)
    result = replay(old_log, store, env.repo, env.permissions)
    assert (result.reapplied, result.unknown) == (2, 2)  # the account itself is not in this backup
    assert store.principal(unmerged.principal_id).deleted_at is not None
    assert env.repo.capture(unmerged.principal_id, kept.capture_id).deleted


def test_a_withdrawal_survives_a_restore_but_a_newer_grant_is_respected(env, world, admin_engine, tmp_path):  # noqa: F811
    log = JsonlTombstoneLog(tmp_path)
    store = PostgresIdentityStore(env.app_db)
    owner = account(world, "sub-consent").principal_id
    scope = Scope("REPORT", "report_consent")

    def decide(decision):
        env.clock.advance(1)
        return env.permissions.record(subject_id=owner, actor_id=owner, purpose_id=AI, scope=scope,
                                      decision=decision, notice_version=NOTICE)

    decide(Decision.GRANT)
    withdrawal = decide(Decision.WITHDRAW)
    assert "PROPAGATED" in {o.action for o in recording(env, log).run_once()}
    [t] = [t for t in log.read().tombstones if t.kind == PERMISSION_WITHDRAWN]
    assert (t.ref, t.purpose_id, t.scope_ref, t.recorded_at) == (withdrawal.event_id, AI, "report_consent",
                                                                  withdrawal.recorded_at)

    with admin_engine.begin() as conn:  # the backup predates the withdrawal
        conn.execute(text("DELETE FROM app.permission_event WHERE event_id = :e"), {"e": withdrawal.event_id})
    assert env.permissions.check(owner, AI, scope).allowed  # resurrected by the restore
    result = replay(log, store, env.repo, env.permissions)
    assert result.reapplied == 1 and not env.permissions.check(owner, AI, scope).allowed
    assert replay(log, store, env.repo, env.permissions).reapplied == 0  # idempotent

    decide(Decision.GRANT)  # the owner grants again after the withdrawal
    assert replay(log, store, env.repo, env.permissions).reapplied == 0
    assert env.permissions.check(owner, AI, scope).allowed  # a newer choice is never undone


def test_log_out_everywhere_survives_a_restore(env, world, admin_engine, tmp_path):  # noqa: F811
    clock, _, identity = world
    log = JsonlTombstoneLog(tmp_path)
    store = PostgresIdentityStore(env.app_db)
    devices = NotificationService(repo=PostgresNotificationRepository(env.app_db), clock=env.clock,
                                  ids=SequentialIds(), environment=Environment.TEST)
    who = account(world, "sub-lost-phone")
    devices.register(who, "a" * 64, "apns", "test", "en")
    env.clock.advance(5)
    store.revoke_sessions(who.principal_id, env.clock.now())
    assert "RECORDED" in {o.action for o in recording(env, log).run_once()}
    [t] = [t for t in log.read().tombstones if t.kind == SESSIONS_REVOKED]
    assert t.recorded_at == env.clock.now()
    env.clock.advance(5)
    devices.register(who, "b" * 64, "fcm", "test", "en")  # a device signed in after the revocation

    with admin_engine.begin() as conn:  # the backup predates the revocation
        conn.execute(text("UPDATE app.principal SET revoked_before = NULL WHERE principal_id = :p"),
                     {"p": who.principal_id})
    result = replay(log, store, env.repo, env.permissions, devices)
    assert result.reapplied == 1 and store.principal(who.principal_id).revoked_before == t.recorded_at
    assert [i.platform.value for i in devices.installations(who.principal_id)] == ["fcm"]
    assert replay(log, store, env.repo, env.permissions, devices).reapplied == 0
