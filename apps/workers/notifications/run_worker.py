"""Notification worker entry point (T24).

The only component with mail/push provider credentials and egress; the API
records bindings and preferences but never calls a provider. Plans
report-ready notices from the outbox and delivers them best effort, so a
provider outage delays notices and never business state::

    PRINCESS_COMPONENT=notification_worker ... python apps/workers/notifications/run_worker.py run
    ... run_worker.py once                                   # one pass; prints counts
    ... run_worker.py suppress --recipient <principal_id> --reason MANUAL
    ... run_worker.py unsuppress --recipient <principal_id>  # after support review

Only fake adapters compose today: live mail waits on the ADR-007 provider
decision, APNs/FCM on native signing accounts (T29-T31). With the
``notifications`` kill switch off, pending events are consumed without
sending, so switching it back on does not flush late notices.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.adapters.fakes import FakeMailer, FakePushProvider  # noqa: E402
from princess_app.adapters.postgres.notifications import PostgresNotificationRepository  # noqa: E402
from princess_app.adapters.postgres.stores import Database, make_engine  # noqa: E402
from princess_app.application.notifications import SEND_DEADLINE, NotificationWorker  # noqa: E402
from princess_app.config import load_runtime_config  # noqa: E402
from princess_app.ports.base import CallContext, ProviderMode, SystemClock, Unsupported  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notification-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="poll and deliver until stopped")
    sub.add_parser("once", help="one planning and delivery pass")
    suppress = sub.add_parser("suppress", help="stop mail to a recipient (bounce, complaint or support request)")
    suppress.add_argument("--recipient", required=True)
    suppress.add_argument("--reason", choices=["BOUNCE", "COMPLAINT", "MANUAL"], required=True)
    unsuppress = sub.add_parser("unsuppress", help="lift a suppression after review")
    unsuppress.add_argument("--recipient", required=True)
    args = parser.parse_args(argv)

    config = load_runtime_config(os.environ, ROOT)
    if config.component != "notification_worker":
        raise SystemExit("PRINCESS_COMPONENT must be notification_worker")
    clock = SystemClock()
    repo = PostgresNotificationRepository(Database(make_engine(config.secret("PRINCESS_DATABASE_URL"))))
    if args.command == "suppress":
        repo.suppress(args.recipient, args.reason, clock.now())
        return _print({"command": "suppress", "recorded": True})
    if args.command == "unsuppress":
        return _print({"command": "unsuppress", "removed": repo.unsuppress(args.recipient)})

    if (config.provider_mode("TransactionalMailer") is not ProviderMode.FAKE
            or config.provider_mode("PushProvider") is not ProviderMode.FAKE):
        raise Unsupported("notification_adapters_not_configured", detail="ADR-007 provider pending")
    worker = NotificationWorker(
        repo=repo, clock=clock, environment=config.environment,
        context=lambda key: CallContext(uuid.uuid4().hex, config.environment, clock.now() + SEND_DEADLINE,
                                        operation_key=key),
        mailer=FakeMailer(clock=clock, environment=config.environment, accept_any_recipient=True),
        push=FakePushProvider(clock=clock, environment=config.environment),
        enabled=lambda: config.enabled("notifications"))
    if args.command == "once":
        outcomes = worker.run_once()
        return _print({"command": "once", "outcomes": dict(Counter(f"{o.channel}:{o.state}" for o in outcomes))})
    while True:  # pragma: no cover - long-running loop
        if not worker.run_once():
            time.sleep(timedelta(seconds=2).total_seconds())


def _print(result: dict) -> int:
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
