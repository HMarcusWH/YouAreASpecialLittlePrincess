"""T02 PostgreSQL persistence: RLS with a real non-owner role, composite
ownership keys, append-only facts, identity lifecycle and permission fencing."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, SequentialIds
from princess_app.adapters.postgres import migrate
from princess_app.adapters.postgres.stores import (
    PostgresAnalysisStore,
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
    epoch_for,
)
from princess_app.application.identity import IdentityService
from princess_app.application.permissions import PermissionService
from princess_app.application.reports import ReportReader
from princess_app.domain.analysis import analysis_reference
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.permissions import SUBJECT_WIDE, Decision, Scope
from princess_app.domain.reports import assemble_report, revise_report
from princess_app.ports.base import CallContext, Conflict, Environment, NotFound, Unauthenticated

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "reports" / "source"
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
AUD = "princess-api"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def world(app_db):
    clock = FakeClock(T0)
    provider = FakeIdentityProvider(clock=clock)
    identity = IdentityService(provider, PostgresIdentityStore(app_db), clock, SequentialIds(), AUD)
    return clock, provider, identity


def ctx(clock):
    return CallContext("corr-1", Environment.TEST, clock.now() + timedelta(seconds=30))


def account(world, subject):
    clock, provider, identity = world
    return identity.authenticate(provider.issue_token(subject, AUD), ctx(clock))


def seed_run(app_db, owner_id, run_id="run_1", asset_id="asset_1"):
    store = PostgresAnalysisStore(app_db)
    ref = load("analysis-reference.synthetic.json")
    store.create_asset(owner_id, asset_id, kind="ORIGINAL", sha256=ref["input_sha256"], media_type="image/png",
                       size_bytes=1234, version_ref="ver_1", at=T0)
    store.create_run(owner_id, run_id, asset_id=asset_id, engine_version=ref["versions"]["engine"],
                     feature_schema=ref["versions"]["feature_schema"],
                     method_manifest=ref["versions"]["method_manifest"],
                     analysis_config_sha256=ref["versions"]["analysis_config"], input_sha256=ref["input_sha256"],
                     at=T0)
    return store


def reference_for(owner_id, run_id="run_1", asset_id="asset_1"):
    ref = load("analysis-reference.synthetic.json")
    return analysis_reference(analysis_id=f"analysis_{run_id}", run_id=run_id, owner_id=owner_id,
                              input_asset_id=asset_id, input_sha256=ref["input_sha256"],
                              processed_sha256=ref["processed_sha256"], created_at=T0,
                              engine_version=ref["versions"]["engine"],
                              analysis_config_sha256=ref["versions"]["analysis_config"])


def publish_report(app_db, owner_id, run_id="run_1"):
    store = seed_run(app_db, owner_id, run_id=run_id, asset_id=f"asset_{run_id}")
    reference = reference_for(owner_id, run_id, f"asset_{run_id}")
    evidence = build_evidence_bundle(load("evidence-payload.synthetic.json"), reference, f"evidence_{run_id}").value
    result = load("engine-result.synthetic.json")
    store.complete_run(owner_id, run_id, result=result, processed_sha256=reference["processed_sha256"], at=T0,
                       evidence=evidence)
    report = assemble_report(report_id=f"report_{run_id}", analysis=reference, result=result, created_at=T0,
                             locale="en", evidence=evidence).value
    PostgresReportStore(app_db, owner_id).append(owner_id, report)
    return report


def test_migration_refuses_to_drop_populated_schema_and_round_trips_empty(admin_engine, app_db, world):
    account(world, "sub-a")
    url = admin_engine.url.render_as_string(hide_password=False)
    with pytest.raises(DBAPIError):
        migrate.downgrade(url, "base")
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.principal")).scalar() == 1
        conn.execute(text("TRUNCATE app.principal CASCADE"))
    migrate.downgrade(url, "base")
    migrate.upgrade(url)
    with admin_engine.begin() as conn:
        assert conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar() == "0001_product_plane"


def test_runtime_role_is_not_privileged(app_db):
    with app_db.session() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert row == (False, False)
        owner = conn.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname = 'app' "
                                  "AND tablename = 'report'")).scalar()
        assert owner != conn.execute(text("SELECT current_user")).scalar()


def test_rls_hides_other_owners_rows_even_with_raw_sql(app_db, world):
    alice, bob = account(world, "sub-a"), account(world, "sub-b")
    report = publish_report(app_db, alice.principal_id)
    with app_db.session(bob.principal_id) as conn:
        for table in ("report", "report_revision", "analysis_run", "measurement", "region", "evidence_bundle",
                      "asset"):
            assert conn.execute(text(f"SELECT count(*) FROM app.{table}")).scalar() == 0, table
        assert conn.execute(text("SELECT count(*) FROM app.principal")).scalar() == 1
    with app_db.session(None) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report")).scalar() == 0
    reader = ReportReader(PostgresReportStore(app_db, bob.principal_id), FakeClock(T0))
    with pytest.raises(NotFound):
        reader.view(report_id=report.data["report_id"], principal_id=bob.principal_id, projection="OWNER")
    own = ReportReader(PostgresReportStore(app_db, alice.principal_id), FakeClock(T0))
    assert own.view(report_id=report.data["report_id"], principal_id=alice.principal_id,
                    projection="FREE").data["source_digest"] == report.data["document_digest"]


def test_rls_rejects_writes_for_another_owner(app_db, world):
    alice, bob = account(world, "sub-a"), account(world, "sub-b")
    with pytest.raises(ProgrammingError):
        with app_db.session(alice.principal_id) as conn:
            conn.execute(text("INSERT INTO app.asset (asset_id, owner_id, kind, sha256, media_type, size_bytes, "
                              "version_ref, created_at) VALUES ('a_x', :o, 'ORIGINAL', :h, 'image/png', 1, 'v', now())"),
                         {"o": bob.principal_id, "h": "0" * 64})


def test_result_and_projections_commit_atomically_and_reject_duplicates(app_db, world):
    alice = account(world, "sub-a")
    publish_report(app_db, alice.principal_id)
    store = PostgresAnalysisStore(app_db)
    assert store.result(alice.principal_id, "run_1")["metadata"]["schema_version"]
    with app_db.session(alice.principal_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.measurement WHERE run_id = 'run_1'")).scalar() == 64
        missing = conn.execute(text("SELECT count(*) FROM app.measurement WHERE quality = 'MISSING' "
                                    "AND value_float IS NOT NULL")).scalar()
        assert missing == 0
    with pytest.raises(Conflict):
        store.complete_run(alice.principal_id, "run_1", result=load("engine-result.synthetic.json"),
                           processed_sha256="1" * 64, at=T0)
    with pytest.raises(IntegrityError):
        with app_db.session(alice.principal_id) as conn:
            conn.execute(text("INSERT INTO app.measurement (owner_id, run_id, feature_id, value_float, quality, "
                              "n_observations, method_id, confidence_kind) VALUES (:o, 'run_1', 'SLANT_ANGLE_MEAN', "
                              "1.0, 'EXPERIMENTAL', 1, 'm', 'UNCALIBRATED')"), {"o": alice.principal_id})


def test_failed_projection_leaves_no_partial_rows(app_db, world):
    alice = account(world, "sub-a")
    store = seed_run(app_db, alice.principal_id)
    bad = load("engine-result.synthetic.json")
    bad["measurements"]["SLANT_ANGLE_MEAN"]["raw_value"] = 1.0
    bad["measurements"]["SLANT_ANGLE_MEAN"]["quality_flag"] = "MISSING"  # value with MISSING violates a CHECK
    bad["measurements"]["SLANT_ANGLE_MEAN"]["missing_reason"] = "x"
    with pytest.raises(IntegrityError):
        store.complete_run(alice.principal_id, "run_1", result=bad, processed_sha256="1" * 64, at=T0)
    with app_db.session(alice.principal_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.measurement")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM app.region")).scalar() == 0
        assert conn.execute(text("SELECT status FROM app.analysis_run")).scalar() == "QUEUED"


def test_forged_region_parent_from_another_run_is_rejected(app_db, world):
    alice = account(world, "sub-a")
    seed_run(app_db, alice.principal_id, "run_1", "asset_1")
    seed_run(app_db, alice.principal_id, "run_2", "asset_2")
    with pytest.raises(IntegrityError):
        with app_db.session(alice.principal_id) as conn:
            conn.execute(text("INSERT INTO app.region (owner_id, run_id, region_id, scope, x, y, width, height) "
                              "VALUES (:o, 'run_1', 'page_0', 'PAGE', 0, 0, 10, 10)"), {"o": alice.principal_id})
            conn.execute(text("INSERT INTO app.region (owner_id, run_id, region_id, scope, x, y, width, height, "
                              "parent_region_id) VALUES (:o, 'run_2', 'line_0', 'LINE', 0, 0, 5, 5, 'page_0')"),
                         {"o": alice.principal_id})


def test_run_cannot_reference_another_owners_asset(app_db, world):
    alice, bob = account(world, "sub-a"), account(world, "sub-b")
    seed_run(app_db, alice.principal_id)
    with pytest.raises((IntegrityError, ProgrammingError)):
        PostgresAnalysisStore(app_db).create_run(
            bob.principal_id, "run_b", asset_id="asset_1", engine_version="0.1.0", feature_schema="x",
            method_manifest="0" * 64, analysis_config_sha256="0" * 64, input_sha256="0" * 64, at=T0)


def test_immutable_rows_cannot_be_updated_by_the_runtime_role(app_db, world):
    alice = account(world, "sub-a")
    publish_report(app_db, alice.principal_id)
    PermissionService(PostgresPermissionStore(app_db), FakeClock(T0), SequentialIds()).record(
        subject_id=alice.principal_id, actor_id=alice.principal_id, purpose_id="product_analytics",
        scope=SUBJECT_WIDE, decision=Decision.GRANT, notice_version="n1")
    for statement in ("UPDATE app.report_revision SET digest = digest", "UPDATE app.permission_event SET actor_id = 'x'",
                      "UPDATE app.measurement SET value_float = 0", "DELETE FROM app.permission_event"):
        with pytest.raises(ProgrammingError):
            with app_db.session(alice.principal_id) as conn:
                conn.execute(text(statement))


def test_report_revisions_append_in_order_and_reject_mutations(app_db, world):
    alice = account(world, "sub-a")
    first = publish_report(app_db, alice.principal_id)
    store = PostgresReportStore(app_db, alice.principal_id)
    second = revise_report(first, created_at=T0 + timedelta(minutes=1), premium_overlay_id="overlay_1").value
    store.append(alice.principal_id, second)
    assert store.latest(first.data["report_id"])[1].data["revision"] == 2
    with pytest.raises(Conflict):
        store.append(alice.principal_id, second)


def test_identity_lifecycle_on_postgres(world, app_db):
    clock, provider, identity = world
    token = provider.issue_token("sub-a", AUD)
    principal = identity.authenticate(token, ctx(clock))
    assert identity.authenticate(provider.issue_token("sub-a", AUD), ctx(clock)).principal_id == principal.principal_id
    clock.advance(5)
    identity.delete_account(principal, ctx(clock))
    with pytest.raises(Unauthenticated):
        identity.authenticate(token, ctx(clock))
    clock.advance(1)
    fresh = identity.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    assert fresh.principal_id != principal.principal_id
    with pytest.raises(Unauthenticated):
        identity.authenticate(token, ctx(clock))
    with app_db.session(principal.principal_id) as conn:
        assert conn.execute(text("SELECT topic FROM app.outbox_event")).scalar() == "account.deletion_requested"


def test_concurrent_first_login_converges_on_one_principal(world):
    clock, provider, identity = world
    tokens = [provider.issue_token("sub-race", AUD) for _ in range(6)]
    results, errors = [], []

    def login(tok):
        try:
            results.append(identity.authenticate(tok, ctx(clock)).principal_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=login, args=(t,)) for t in tokens]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(set(results)) == 1


def test_guest_transfer_moves_ownership_once_under_concurrency(world, app_db):
    clock, provider, identity = world
    guest, token = identity.create_guest()
    publish_report(app_db, guest.principal_id)
    PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds()).record(
        subject_id=guest.principal_id, actor_id=guest.principal_id, purpose_id="service_processing",
        scope=Scope("SPECIMEN", "asset_run_1"), decision=Decision.GRANT, notice_version="n1")
    accounts = [account(world, f"sub-{i}") for i in range(4)]
    outcomes = []

    def transfer(acct):
        try:
            outcomes.append(("ok", acct.principal_id, identity.transfer_guest(acct, token)))
        except Conflict:
            outcomes.append(("conflict", acct.principal_id, None))

    threads = [threading.Thread(target=transfer, args=(a,)) for a in accounts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [o for o in outcomes if o[0] == "ok"]
    assert len(winners) == 1 and len(outcomes) == 4
    winner = winners[0][1]
    with app_db.session(winner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report_revision")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM app.measurement")).scalar() == 64
        assert conn.execute(text("SELECT count(*) FROM app.permission_event")).scalar() == 1
    with app_db.session(guest.principal_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report")).scalar() == 0
    with pytest.raises(Unauthenticated):
        identity.authenticate(token, ctx(clock))


def test_permission_ledger_and_publication_fence_on_postgres(app_db, world):
    alice = account(world, "sub-a")
    clock = FakeClock(T0)
    svc = PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds())
    scope = Scope("REPORT", "report_1")
    svc.record(subject_id=alice.principal_id, actor_id=alice.principal_id, purpose_id="third_party_ai_processing",
               scope=scope, decision=Decision.GRANT, notice_version="n1")
    epoch = svc.require(alice.principal_id, "third_party_ai_processing", scope)
    # A publisher holds the epoch row; a concurrent withdrawal must wait for it.
    publisher = app_db.engine.connect()
    tx = publisher.begin()
    from princess_app.adapters.postgres.stores import set_context
    set_context(publisher, alice.principal_id)
    assert epoch_for(publisher, alice.principal_id, "third_party_ai_processing", lock=True) == epoch
    done = threading.Event()

    def withdraw():
        clock.advance(1)
        svc.record(subject_id=alice.principal_id, actor_id=alice.principal_id,
                   purpose_id="third_party_ai_processing", scope=SUBJECT_WIDE, decision=Decision.WITHDRAW,
                   notice_version="n1")
        done.set()

    worker = threading.Thread(target=withdraw)
    worker.start()
    assert not done.wait(0.5), "withdrawal must wait for the in-flight publication"
    tx.commit()
    publisher.close()
    worker.join(5)
    assert done.is_set()
    assert not svc.still_valid(alice.principal_id, "third_party_ai_processing", scope, epoch)


def test_guest_capability_is_stored_only_as_a_hash(world, admin_engine):
    _, _, identity = world
    guest, token = identity.create_guest()
    with admin_engine.begin() as conn:
        stored = conn.execute(text("SELECT guest_capability_sha256 FROM app.principal WHERE principal_id = :p"),
                              {"p": guest.principal_id}).scalar()
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored
