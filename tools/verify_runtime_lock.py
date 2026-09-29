#!/usr/bin/env python3
"""Verify the T24 source-tree runtime lock is a reviewed subset of the app lock."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "infra/runtime/python-py312.txt"
RUNTIME_LOCK = ROOT / "infra/runtime/python-py312.lock"
APP_MANIFEST = ROOT / "requirements/app-py312.txt"
APP_LOCK = ROOT / "requirements/app-py312.lock"
FORBIDDEN = {"pip", "setuptools", "wheel", "pytest", "ruff", "iniconfig", "pluggy", "pygments"}
REQUIRED = {
    "numpy", "opencv-python-headless", "scipy", "scikit-learn", "scikit-image",
    "fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg", "psycopg-binary",
}
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def records(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.match(line)
        if match is None:
            raise SystemExit(f"{path}: non-exact record: {line}")
        name = normalize(match.group(1))
        if name in out:
            raise SystemExit(f"{path}: duplicate distribution: {name}")
        out[name] = line
    return out


def main() -> int:
    runtime_manifest = records(RUNTIME_MANIFEST)
    runtime_lock = records(RUNTIME_LOCK)
    app_manifest = records(APP_MANIFEST)
    app_lock = records(APP_LOCK)
    errors: list[str] = []

    if "# Python 3.12; Linux x86_64." not in RUNTIME_LOCK.read_text(encoding="utf-8"):
        errors.append("runtime lock is not stamped for Python 3.12 Linux x86_64")
    if set(runtime_manifest) != set(runtime_lock):
        errors.append("runtime manifest/lock distribution sets differ")
    if FORBIDDEN & set(runtime_lock):
        errors.append("build/test tooling leaked into runtime lock: " + ",".join(sorted(FORBIDDEN & set(runtime_lock))))
    if not REQUIRED <= set(runtime_lock):
        errors.append("runtime roots missing: " + ",".join(sorted(REQUIRED - set(runtime_lock))))

    for name, line in runtime_manifest.items():
        if app_manifest.get(name) != line:
            errors.append(f"runtime manifest record is not inherited exactly: {name}")
    for name, line in runtime_lock.items():
        if app_lock.get(name) != line:
            errors.append(f"runtime lock/hash record is not inherited exactly: {name}")

    for error in errors:
        print(error)
    if not errors:
        print(f"Runtime lock verified: {len(runtime_lock)} reviewed distributions; no build/test tools")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
