"""Operator commands for scheduled loops and read-only posture checks (T24).

Commands print one JSON document with bounded counts/outcome codes only. The
operational snapshot/check commands deliberately avoid full provider
composition so they remain usable during a provider incident.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from princess_app.adapters.postgres.feedback import PostgresFeedbackRepository
from princess_app.adapters.postgres.intake import PostgresIntakeRepository
from princess_app.adapters.postgres.operations import PostgresOperationalRepository
from princess_app.adapters.postgres.stores import Database, PostgresIdentityStore, make_engine
from princess_app.application.operations import (
    CAPABILITY_NAMES,
    build_snapshot,
    evaluate_alerts,
    load_alert_policy,
    verify_disabled,
)
from princess_app.application.tombstones import replay
from princess_app.config import load_runtime_config
from princess_app.ports.base import CallContext, SystemClock
from princess_app.ports.payments import PaymentRail

from princess_graphology import __version__ as ENGINE_VERSION

from .compose import ROOT, compose, tombstone_log


def _operational_snapshot(config):
    clock = SystemClock()
    now = clock.now()
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    repo = PostgresOperationalRepository(db)
    log = tombstone_log()
    contents = log.read()
    return build_snapshot(
        environment=config.environment,
        observed_at=now,
        schema_revision=repo.schema_revision(),
        capabilities=config.manifest.kill_switches,
        database_observations=repo.observations(now),
        tombstone_entries=len(contents.tombstones),
        tombstone_unreadable=contents.unreadable,
        tombstone_store_present=log.path.parent.exists(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="princess_api.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("complete-pending", help="retry server-side consume/acknowledge of durable grants")
    reconcile = sub.add_parser("reconcile", help="re-read authoritative provider state (missed webhooks, refunds)")
    reconcile.add_argument("--rail", choices=[r.value for r in PaymentRail], required=True)
    reconcile.add_argument("--since-hours", type=int, default=48)
    sub.add_parser("expire-feedback", help="delete report feedback past its retention")
    sub.add_parser("replay-tombstones",
                   help="after a database restore, before serving traffic: re-apply recorded deletions")
    sub.add_parser("snapshot", help="emit operational-snapshot/1 without provider calls")
    check = sub.add_parser("check", help="evaluate a reviewed alert policy against one operational snapshot")
    check.add_argument("--policy", type=Path, required=True)
    disabled = sub.add_parser("verify-disabled", help="prove reviewed manifest switches are disabled; never mutates")
    disabled.add_argument("--switch", action="append", choices=CAPABILITY_NAMES, required=True)
    args = parser.parse_args(argv)

    config = load_runtime_config(os.environ, ROOT)

    # Incident diagnostics deliberately do not call compose(): a broken live
    # provider must not make the diagnostic surface unavailable.
    if args.command == "verify-disabled":
        off, on = verify_disabled(config.manifest.kill_switches, args.switch)
        result = {"command": "verify-disabled", "disabled": list(off), "enabled": list(on),
                  "result": "PASS" if not on else "FAIL"}
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0 if not on else 2

    if args.command in ("snapshot", "check"):
        snapshot = _operational_snapshot(config)
        if args.command == "snapshot":
            sys.stdout.write(json.dumps(snapshot.to_dict(), sort_keys=True) + "\n")
            return 0
        policy = load_alert_policy(args.policy, expected_environment=config.environment)
        alerts = evaluate_alerts(snapshot, policy)
        result = {
            "command": "check",
            "policy_version": "operational-alert-policy/1",
            "snapshot_version": "operational-snapshot/1",
            "result": "ALERT" if alerts else "PASS",
            "alerts": [alert.to_dict() for alert in alerts],
        }
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 2 if alerts else 0

    services = compose(config)
    ctx = CallContext(f"ops-{uuid.uuid4().hex[:12]}", services.environment,
                      services.clock.now() + timedelta(seconds=300))
    if args.command == "complete-pending":
        result = {"completed": services.commerce.complete_pending(ctx)}
    elif args.command == "reconcile":
        since = services.clock.now() - timedelta(hours=args.since_hours)
        outcomes = services.commerce.reconcile(PaymentRail(args.rail), since, ctx)
        result = {"rail": args.rail, "outcomes": dict(Counter(outcomes))}
    elif args.command == "replay-tombstones":
        db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
        replayed = replay(tombstone_log(), PostgresIdentityStore(db),
                          PostgresIntakeRepository(db, engine_version=ENGINE_VERSION), services.permissions,
                          services.notifications, services.feedback)
        result = {"reapplied": replayed.reapplied, "already": replayed.already, "unknown": replayed.unknown,
                  "unreadable": replayed.unreadable}
    else:
        db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
        result = {"expired": PostgresFeedbackRepository(db).expire(services.clock.now())}
    sys.stdout.write(json.dumps({"command": args.command, **result}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
