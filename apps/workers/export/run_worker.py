"""Export worker entry point (T21).

Claims export jobs, derives the authorized projection from the saved report
(database access) and hands only that projection to the sandboxed renderer
child (``render_worker``: no database, no secrets, offline Chromium). It then
stores the bytes as an ``EXPORT`` asset and publishes the export, fenced on the
job lease, a live owner and report, and an unchanged projection.
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

from princess_app.adapters.localfs import LocalObjectStore  # noqa: E402
from princess_app.adapters.postgres.access import PostgresReportAccess  # noqa: E402
from princess_app.adapters.postgres.exports import PostgresExportRepository  # noqa: E402
from princess_app.adapters.postgres.stores import (  # noqa: E402
    Database,
    PostgresPermissionStore,
    PostgresReportStore,
    make_engine,
)
from princess_app.adapters.render import DEFAULT_BUNDLE, SubprocessRenderer  # noqa: E402
from princess_app.adapters.render.assets import clean_source_raster  # noqa: E402
from princess_app.adapters.postgres.intake import PostgresIntakeRepository  # noqa: E402
from princess_graphology import __version__ as ENGINE_VERSION  # noqa: E402
from princess_app.application.exports import ExportService, ExportWorker  # noqa: E402
from princess_app.application.permissions import PermissionService  # noqa: E402
from princess_app.config import load_runtime_config  # noqa: E402
from princess_app.ports.base import (  # noqa: E402
    CallContext, Environment, InvalidInput, ProviderMode, SystemClock, Unsupported,
)


class UuidIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"


def main() -> int:
    config = load_runtime_config(os.environ, ROOT)
    if config.component != "export_worker":
        raise SystemExit("PRINCESS_COMPONENT must be export_worker")
    if config.provider_mode("ObjectStore") is not ProviderMode.FAKE:
        raise Unsupported("object_store_adapter_not_configured", detail="ADR-004 provider pending")
    v3_flag = os.environ.get("PRINCESS_RENDER_V3_RESEARCH_OPT_IN", "0")
    if v3_flag not in ("0", "1"):
        raise InvalidInput("render_v3_opt_in_invalid")
    if v3_flag == "1" and (
            config.environment not in (Environment.LOCAL, Environment.TEST)
            or (config.environment is Environment.TEST
                and os.environ.get("PRINCESS_TEST_PUBLIC_GUEST_ONLY") == "1")):
        raise Unsupported("render_v3_private_only")
    private_v3 = v3_flag == "1"
    if not DEFAULT_BUNDLE.exists():
        raise SystemExit("build the renderer first: pnpm --filter @princess/render run build")
    clock = SystemClock()
    store = LocalObjectStore(Path(os.environ.get("PRINCESS_LOCAL_STORAGE_DIR", str(ROOT / ".local-storage"))),
                             signing_key=config.secret("PRINCESS_STORAGE_READ_KEY").encode(), clock=clock,
                             environment=config.environment)
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    permissions = PermissionService(PostgresPermissionStore(db), clock, UuidIds(),
                                    allow_draft_policy=config.environment in (Environment.LOCAL, Environment.TEST))
    service = ExportService(reports=lambda owner: PostgresReportStore(db, owner), access=PostgresReportAccess(db),
                            repo=PostgresExportRepository(db), store=store, clock=clock, ids=UuidIds(),
                            permissions=permissions, private_v3_enabled=private_v3,
                            source_capture=(PostgresIntakeRepository(db).capture_for_asset if private_v3 else None),
                            source_sanitizer=clean_source_raster if private_v3 else None)
    worker = ExportWorker(
        service=service, renderer=SubprocessRenderer(chromium=os.environ.get("PRINCESS_CHROMIUM")),
        worker_id=f"export-{uuid.uuid4().hex[:8]}",
        context=lambda: CallContext(uuid.uuid4().hex, config.environment, clock.now() + timedelta(seconds=60)))
    while True:  # pragma: no cover - long-running loop
        if worker.run_once() is None:
            time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
