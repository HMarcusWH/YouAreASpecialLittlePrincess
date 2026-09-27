"""T24: a database restore cannot resurrect deleted accounts or captures."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from princess_app.adapters.localfs.tombstones import JsonlTombstoneLog
from princess_app.adapters.postgres.stores import PostgresIdentityStore, PostgresReportStore
from princess_app.application.erasure import ErasureWorker
from princess_app.application.tombstones import ACCOUNT_DELETED, CAPTURE_DELETED, Tombstone, replay
from princess_app.ports.base import PermanentFailure
from test_intake import Env, erasure
from test_persistence import T0, account, world  # noqa: F401 - fixture re-export


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

    result = replay(log, identity, env.repo)
    assert (result.reapplied, result.already, result.unknown) == (2, 0, 0)
    assert PostgresReportStore(env.app_db, owner).latest(report_id) is None
    assert identity.principal(leaving).deleted_at is not None
    assert "ERASED" in {o.action for o in erasure(env).run_once()}  # erasure runs again, idempotently
    assert env.store.verify_deletion(capture.asset_id, env.ctx())
    again = replay(log, identity, env.repo)
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


def test_the_log_tolerates_a_torn_tail_but_not_corruption(tmp_path):
    log = JsonlTombstoneLog(tmp_path)
    log.append(Tombstone(ACCOUNT_DELETED, "prn_1", "prn_1", T0))
    log.append(Tombstone(ACCOUNT_DELETED, "prn_1", "prn_1", T0))  # duplicates are harmless
    with open(log.path, "ab") as f:
        f.write(b'{"kind": "CAPTURE_DEL')  # a crash mid-write
    assert [t.owner_id for t in log.entries()] == ["prn_1", "prn_1"]
    with open(log.path, "ab") as f:
        f.write(b"\nnot json\n")
    with pytest.raises(PermanentFailure):
        list(log.entries())
