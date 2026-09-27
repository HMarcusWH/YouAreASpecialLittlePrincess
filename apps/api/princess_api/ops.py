"""Operator commands for the scheduled loops (T24).

Run with the API component's environment (it alone holds payment-server
credentials), e.g. from a scheduler every few minutes::

    PRINCESS_COMPONENT=api ... python -m princess_api.ops complete-pending
    PRINCESS_COMPONENT=api ... python -m princess_api.ops reconcile --rail stripe --since-hours 48
    PRINCESS_COMPONENT=api ... python -m princess_api.ops expire-feedback

Each prints one JSON line of counts and outcome codes, never personal data.
Every command is idempotent: a repeated or overlapping run converges.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from datetime import timedelta
from typing import Sequence

from princess_app.adapters.postgres.feedback import PostgresFeedbackRepository
from princess_app.adapters.postgres.stores import Database, make_engine
from princess_app.config import load_runtime_config
from princess_app.ports.base import CallContext
from princess_app.ports.payments import PaymentRail

from .compose import ROOT, compose


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="princess_api.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("complete-pending", help="retry server-side consume/acknowledge of durable grants")
    reconcile = sub.add_parser("reconcile", help="re-read authoritative provider state (missed webhooks, refunds)")
    reconcile.add_argument("--rail", choices=[r.value for r in PaymentRail], required=True)
    reconcile.add_argument("--since-hours", type=int, default=48)
    sub.add_parser("expire-feedback", help="delete report feedback past its retention")
    args = parser.parse_args(argv)

    config = load_runtime_config(os.environ, ROOT)
    services = compose(config)
    ctx = CallContext(f"ops-{uuid.uuid4().hex[:12]}", services.environment,
                      services.clock.now() + timedelta(seconds=300))
    if args.command == "complete-pending":
        result = {"completed": services.commerce.complete_pending(ctx)}
    elif args.command == "reconcile":
        since = services.clock.now() - timedelta(hours=args.since_hours)
        outcomes = services.commerce.reconcile(PaymentRail(args.rail), since, ctx)
        result = {"rail": args.rail, "outcomes": dict(Counter(outcomes))}
    else:
        db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
        result = {"expired": PostgresFeedbackRepository(db).expire(services.clock.now())}
    sys.stdout.write(json.dumps({"command": args.command, **result}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
