"""Analysis worker entry point (T04).

Composes the fenced job queue with the worker database role, the object
store and the zero-AI engine, then polls. CPU/memory limits are applied to the
process before any image is decoded; the component has no model credentials
by manifest (docs/roadmap/15-environments-deployment-and-secrets.md).
"""
from __future__ import annotations

import os
import resource
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.adapters.imaging import decode_image  # noqa: E402
from princess_app.adapters.localfs import LocalObjectStore  # noqa: E402
from princess_app.adapters.postgres.intake import PostgresIntakeRepository, PostgresJobQueue  # noqa: E402
from princess_app.adapters.postgres.outbox import PostgresErasureOutbox  # noqa: E402
from princess_app.adapters.postgres.stores import Database, PostgresPermissionStore, make_engine  # noqa: E402
from princess_app.application.analysis_worker import AnalysisWorker  # noqa: E402
from princess_app.application.erasure import ErasureWorker  # noqa: E402
from princess_app.application.intake import propagate_withdrawal  # noqa: E402
from princess_app.application.permissions import PermissionService  # noqa: E402
from princess_app.config import load_runtime_config  # noqa: E402
from princess_app.ports.base import CallContext, Environment, ProviderMode, SystemClock, Unsupported  # noqa: E402
from princess_graphology import GraphologyEngine, __version__  # noqa: E402

MEMORY_LIMIT_BYTES = 3 * 1024 ** 3


class UuidIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

CPU_SECONDS_PER_PROCESS = 3600


def apply_limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    limit = CPU_SECONDS_PER_PROCESS if hard == resource.RLIM_INFINITY else min(CPU_SECONDS_PER_PROCESS, hard)
    resource.setrlimit(resource.RLIMIT_CPU, (limit, hard))


def main() -> int:
    config = load_runtime_config(os.environ, ROOT)
    if config.component != "analysis_worker":
        raise SystemExit("PRINCESS_COMPONENT must be analysis_worker")
    if config.provider_mode("ObjectStore") is not ProviderMode.FAKE:
        raise Unsupported("object_store_adapter_not_configured", detail="ADR-004 provider pending")
    clock = SystemClock()
    store = LocalObjectStore(Path(os.environ.get("PRINCESS_LOCAL_STORAGE_DIR", str(ROOT / ".local-storage"))),
                             signing_key=config.secret("PRINCESS_STORAGE_READ_KEY").encode(), clock=clock,
                             environment=config.environment)
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))

    def context() -> CallContext:
        return CallContext(uuid.uuid4().hex, config.environment, clock.now() + timedelta(seconds=60))

    local = config.environment in (Environment.LOCAL, Environment.TEST)
    worker = AnalysisWorker(
        queue=PostgresJobQueue(db, allow_draft_policy=local), store=store, decode=decode_image, engine=GraphologyEngine(), clock=clock,
        context=context, worker_id=f"analysis-{uuid.uuid4().hex[:8]}", engine_version=__version__)
    permissions = PermissionService(PostgresPermissionStore(db), clock, UuidIds(), allow_draft_policy=local)
    repo = PostgresIntakeRepository(db, engine_version=__version__)
    erasure = ErasureWorker(outbox=PostgresErasureOutbox(db), store=store, permissions=permissions, clock=clock,
                            context=context,
                            propagate=lambda owner, purpose, scope, decision: propagate_withdrawal(
                                repo, permissions, owner, purpose, scope, decision, clock.now()))
    poll(worker, erasure)
    return 0


def poll(worker: AnalysisWorker, erasure: ErasureWorker,
         idle_seconds: float = 1.0) -> None:  # pragma: no cover - long-running loop
    apply_limits()
    while True:
        erasure.run_once()
        if worker.run_once() is None:
            time.sleep(idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
