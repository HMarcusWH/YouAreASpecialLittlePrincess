"""T24 provider-neutral operational posture: aggregation, privacy and alert policy."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from princess_api import ops
from princess_app.adapters.postgres.operations import PostgresOperationalRepository
from princess_app.application.operations import (
    CAPABILITY_NAMES,
    AlertRule,
    OperationalObservation,
    build_snapshot,
    evaluate_alerts,
    load_alert_policy,
)
from princess_app.config import KILL_SWITCHES
from princess_app.ports.base import Environment, InvalidInput
from test_persistence import T0, account, world  # noqa: F401 - fixture re-export

ROOT = Path(__file__).resolve().parents[1]


def insert_job(db, owner: str, job_id: str, kind: str, created_at) -> None:
    with db.session(owner) as conn:
        conn.execute(text(
            "INSERT INTO app.job (job_id, kind, owner_id, subject_ref, state, dedupe_key, created_at, updated_at) "
            "VALUES (:j, :k, :o, :s, 'QUEUED', :d, :t, :t)"
        ), {"j": job_id, "k": kind, "o": owner, "s": "subject_ops", "d": "dedupe_" + job_id, "t": created_at})


def test_operational_function_aggregates_across_rls_without_granting_raw_cross_tenant_reads(
        app_db, world):  # noqa: F811
    alice = account(world, "ops-alice")
    bob = account(world, "ops-bob")
    insert_job(app_db, alice.principal_id, "job_ops_alice", "analysis", T0)
    insert_job(app_db, bob.principal_id, "job_ops_bob", "future-user-text-kind", T0)

    with app_db.session(alice.principal_id) as conn:
        conn.execute(text(
            "INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, created_at) "
            "VALUES ('evt_ops_unknown', 'user.free.text?token=secret', :o, 'agg_ops', '{}'::jsonb, "
            "'ops-unknown-topic', :t)"
        ), {"o": alice.principal_id, "t": T0})

    # No principal context still obeys RLS: the runtime role cannot enumerate tenant rows.
    with app_db.session() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.job")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM app.outbox_event")).scalar_one() == 0

    repo = PostgresOperationalRepository(app_db)
    rows = repo.observations(T0 + timedelta(seconds=120))
    found = {(r.source, r.category, r.state): r for r in rows}
    assert found[("jobs", "analysis", "queued")].count == 1
    assert found[("jobs", "analysis", "queued")].oldest_age_s == 120
    assert found[("jobs", "other", "queued")].count == 1
    assert found[("outbox", "other", "pending")].count == 1
    rendered = json.dumps([row.to_dict() for row in rows], sort_keys=True)
    assert "ops-alice" not in rendered and "ops-bob" not in rendered
    assert "future-user-text-kind" not in rendered
    assert "user.free.text" not in rendered and "secret" not in rendered


def test_snapshot_has_fixed_capabilities_and_privacy_observations():
    assert CAPABILITY_NAMES == KILL_SWITCHES
    snapshot = build_snapshot(
        environment=Environment.TEST,
        observed_at=T0,
        schema_revision="0011_operational_snapshot",
        capabilities={
            "premium_generation": False, "commerce": False, "uploads": True,
            "sharing": True, "notifications": True,
        },
        database_observations=(OperationalObservation("jobs", "analysis", "queued", 2, 12, 1),),
        tombstone_entries=4,
        tombstone_unreadable=1,
        tombstone_store_present=False,
    )
    doc = snapshot.to_dict()
    assert doc["version"] == "operational-snapshot/1"
    privacy = {(o["source"], o["category"], o["state"]): o for o in doc["observations"]}
    assert privacy[("privacy", "tombstone", "missing")]["count"] == 1
    assert privacy[("privacy", "tombstone", "unreadable")]["count"] == 1
    assert doc["privacy"] == {
        "tombstone_store_present": False, "tombstone_entries": 4, "tombstone_unreadable": 1,
    }


def test_alert_policy_is_fixed_dimension_and_fail_closed(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({
        "version": "operational-alert-policy/1",
        "environment": "test",
        "rules": [{
            "alert_code": "test.queue",
            "source": "jobs", "category": "analysis", "state": "queued",
            "measure": "oldest_age_s", "operator": "gt", "threshold": 60,
        }],
    }))
    policy = load_alert_policy(policy_path, expected_environment=Environment.TEST)
    snapshot = build_snapshot(
        environment=Environment.TEST, observed_at=T0,
        schema_revision="0011_operational_snapshot",
        capabilities={name: False for name in CAPABILITY_NAMES},
        database_observations=(OperationalObservation("jobs", "analysis", "queued", 1, 61, 1),),
        tombstone_entries=0, tombstone_unreadable=0, tombstone_store_present=True,
    )
    [alert] = evaluate_alerts(snapshot, policy)
    assert alert.alert_code == "test.queue" and alert.actual == 61
    with pytest.raises(InvalidInput):
        AlertRule("test.bad", "jobs", "user-controlled-kind", "queued", "count", "gt", 0)

    bad = json.loads(policy_path.read_text())
    bad["rules"][0]["measure"] = "raw_payload"
    policy_path.write_text(json.dumps(bad))
    with pytest.raises(InvalidInput):
        load_alert_policy(policy_path, expected_environment=Environment.TEST)


def test_snapshot_and_policy_json_schemas_match_runtime_contracts():
    snapshot = json.loads((ROOT / "infra/operations/operational-snapshot.schema.json").read_text())
    policy = json.loads((ROOT / "infra/operations/alert-policy.schema.json").read_text())
    assert snapshot["properties"]["version"]["const"] == "operational-snapshot/1"
    assert set(snapshot["properties"]["capabilities"]["required"]) == set(CAPABILITY_NAMES)
    assert policy["properties"]["version"]["const"] == "operational-alert-policy/1"
    assert set(policy["properties"]["rules"]["items"]["required"]) == {
        "alert_code", "source", "category", "state", "measure", "operator", "threshold",
    }


def _ops_env(monkeypatch):
    values = {
        "PRINCESS_ENV": "test",
        "PRINCESS_COMPONENT": "api",
        "PRINCESS_DATABASE_URL": "postgresql://ops:test-only@db:5432/princess_test",
        "PRINCESS_SESSION_SECRET": "test-ops-session",
        "PRINCESS_IDENTITY_AUDIENCE": "princess-test",
        "PRINCESS_STORAGE_SIGNING_KEY": "test-ops-storage",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_verify_disabled_is_read_only_and_exit_status_is_actionable(monkeypatch, capsys):
    _ops_env(monkeypatch)
    assert ops.main(["verify-disabled", "--switch", "commerce", "--switch", "premium_generation"]) == 0
    passed = json.loads(capsys.readouterr().out)
    assert passed == {
        "command": "verify-disabled",
        "disabled": ["commerce", "premium_generation"],
        "enabled": [],
        "result": "PASS",
    }
    assert ops.main(["verify-disabled", "--switch", "uploads"]) == 2
    failed = json.loads(capsys.readouterr().out)
    assert failed["result"] == "FAIL" and failed["enabled"] == ["uploads"]
