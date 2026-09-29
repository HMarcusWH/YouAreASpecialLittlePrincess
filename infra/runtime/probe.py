#!/usr/bin/env python3
"""Low-cardinality startup/database probes for T24 runtime roles."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "apps" / "api"), str(Path(__file__).resolve().parent)]

from princess_app.adapters.postgres.stores import Database, make_engine  # noqa: E402
from princess_app.ports.base import PortError  # noqa: E402
from runtime_policy import preflight  # noqa: E402

DATABASE_COMPONENTS = frozenset({
    "api", "analysis_worker", "premium_worker", "export_worker", "notification_worker",
})


def emit(status: str, *, error: str | None = None) -> None:
    payload = {"status": status}
    if error is not None:
        payload["error"] = error
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in (["startup"], ["database"]):
        raise SystemExit("usage: probe.py startup|database")
    try:
        config = preflight(os.environ, ROOT)
        if args == ["database"]:
            if config.component not in DATABASE_COMPONENTS:
                raise SystemExit("database probe is not valid for this component")
            Database(make_engine(config.secret("PRINCESS_DATABASE_URL"))).ping()
    except PortError as exc:
        emit("not_ready", error=exc.code)
        return 1
    emit("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
