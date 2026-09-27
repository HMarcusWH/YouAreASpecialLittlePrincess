"""Premium worker entry point (T15/T19).

Claims leased Premium jobs, runs one bounded attempt through the configured
model port and publishes a validated overlay while spending the reserved
credit in the same fenced transaction. Only the fake model composes today:
the OpenAI adapter needs the ``api_access_spend_before_live_calls`` gate. The
local fake answers every question NOT_ASSESSABLE, so nothing it publishes can
be mistaken for an interpretation.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.adapters.fakes import FakePremiumModel  # noqa: E402
from princess_app.adapters.postgres.commerce import (  # noqa: E402
    PostgresImageSource,
    PostgresOverlayPublisher,
    PostgresPremiumQueue,
)
from princess_app.adapters.postgres.stores import Database, PostgresPermissionStore, PostgresReportStore, make_engine  # noqa: E402,E501
from princess_app.application.permissions import PermissionService  # noqa: E402
from princess_app.application.premium import InMemorySpendBudget, PremiumRunner, load_interpretation_database  # noqa: E402,E501
from princess_app.application.premium.worker import PremiumWorker  # noqa: E402
from princess_app.config import load_runtime_config  # noqa: E402
from princess_app.ports.base import CallContext, Environment, ProviderMode, SystemClock, Unsupported  # noqa: E402

DAILY_TOKEN_BUDGET = int(os.environ.get("PRINCESS_PREMIUM_TOKEN_BUDGET", "200000"))


class UuidIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"


def unassessed(request):
    """Local stand-in model: honest non-answers only."""
    packet = request.packet
    return {"contract_version": "1.0.0", "packet_id": packet["packet_id"],
            "output_schema_version": packet["output_schema_version"],
            "answers": [{"question_id": q["question_id"], "answer_state": "NOT_ASSESSABLE",
                         "selected_candidate_ids": [], "support_fact_ids": [], "prose": None}
                        for q in packet["questions"]],
            "soft_fields": []}


def main() -> int:
    config = load_runtime_config(os.environ, ROOT)
    if config.component != "premium_worker":
        raise SystemExit("PRINCESS_COMPONENT must be premium_worker")
    if config.provider_mode("PremiumModelProvider") is not ProviderMode.FAKE:
        raise Unsupported("premium_model_not_approved", detail="api_access_spend_before_live_calls")
    clock = SystemClock()
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    local = config.environment in (Environment.LOCAL, Environment.TEST)
    permissions = PermissionService(PostgresPermissionStore(db), clock, UuidIds(), allow_draft_policy=local)

    def context() -> CallContext:
        return CallContext(uuid.uuid4().hex, config.environment, clock.now() + timedelta(seconds=60))

    runner = PremiumRunner(
        reports=lambda owner: PostgresReportStore(db, owner), permissions=permissions,
        images=PostgresImageSource(db), model=FakePremiumModel(unassessed, clock=clock, environment=config.environment),
        budget=InMemorySpendBudget(DAILY_TOKEN_BUDGET), publisher=PostgresOverlayPublisher(db),
        database=load_interpretation_database(), clock=clock, ids=UuidIds(), context=context,
        # Reviewed T26 content stays inactive until its owner activation gate;
        # only local/test composition may exercise it against the fake model.
        allow_inactive_content=local)
    worker = PremiumWorker(queue=PostgresPremiumQueue(db), runner=runner, clock=clock,
                           worker_id=f"premium-{uuid.uuid4().hex[:8]}")
    while True:  # pragma: no cover - long-running loop
        if worker.run_once() is None:
            time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
