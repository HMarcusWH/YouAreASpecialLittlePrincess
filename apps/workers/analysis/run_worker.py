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
from princess_app.adapters.postgres.intake import PostgresJobQueue  # noqa: E402
from princess_app.adapters.postgres.stores import Database, make_engine  # noqa: E402
from princess_app.application.analysis_worker import AnalysisWorker  # noqa: E402
from princess_app.config import load_runtime_config  # noqa: E402
from princess_app.ports.base import CallContext, ProviderMode, SystemClock, Unsupported  # noqa: E402
from princess_graphology import GraphologyEngine, __version__  # noqa: E402

MEMORY_LIMIT_BYTES = 3 * 1024 ** 3
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
    worker = AnalysisWorker(
        queue=PostgresJobQueue(Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))), store=store,
        decode=decode_image, engine=GraphologyEngine(), clock=clock,
        context=lambda: CallContext(uuid.uuid4().hex, config.environment, clock.now() + timedelta(seconds=60)),
        worker_id=f"analysis-{uuid.uuid4().hex[:8]}", engine_version=__version__)
    poll(worker)
    return 0


def poll(worker: AnalysisWorker, idle_seconds: float = 1.0) -> None:  # pragma: no cover - long-running loop
    apply_limits()
    while True:
        if worker.run_once() is None:
            time.sleep(idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
