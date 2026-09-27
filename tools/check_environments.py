#!/usr/bin/env python3
"""Validate every reviewed environment manifest under infra/environments."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.config import load_manifest  # noqa: E402
from princess_app.ports.base import Environment, PortError  # noqa: E402


def main() -> int:
    failures = 0
    expected = {f"{env.value}.json" for env in Environment}
    present = {p.name for p in (ROOT / "infra" / "environments").glob("*.json")}
    for extra in sorted(present - expected):
        print(f"FAIL unexpected manifest {extra}")
        failures += 1
    for env in Environment:
        try:
            manifest = load_manifest(ROOT, env)
        except PortError as exc:
            print(f"FAIL {env.value}: {exc}")
            failures += 1
            continue
        modes = sorted({mode.value for mode in manifest.providers.values()})
        print(f"PASS {env.value}: database={manifest.database_name} modes={','.join(modes)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
