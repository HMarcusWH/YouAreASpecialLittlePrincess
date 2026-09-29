#!/usr/bin/env python3
"""Fixed dispatcher for the T24 backend runtime images."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "apps" / "api"), str(Path(__file__).resolve().parent)]

from runtime_policy import preflight  # noqa: E402


def command(component: str) -> list[str]:
    py = sys.executable
    commands = {
        "api": [py, "-m", "uvicorn", "--factory", "princess_api.compose:app_from_environment",
                "--host", "0.0.0.0", "--port", "8000"],
        "analysis_worker": [py, str(ROOT / "apps" / "workers" / "analysis" / "run_worker.py")],
        "premium_worker": [py, str(ROOT / "apps" / "workers" / "premium" / "run_worker.py")],
        "export_worker": [py, str(ROOT / "apps" / "workers" / "export" / "run_worker.py")],
        "notification_worker": [py, str(ROOT / "apps" / "workers" / "notifications" / "run_worker.py"), "run"],
        "migrations": [py, "-m", "princess_app.adapters.postgres.migrate", "upgrade"],
    }
    return commands[component]


def main() -> int:
    config = preflight(os.environ, ROOT)
    argv = command(config.component)
    os.execvpe(argv[0], argv, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
