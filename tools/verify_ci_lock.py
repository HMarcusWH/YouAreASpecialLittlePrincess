#!/usr/bin/env python3
"""Verify that the installed CI environment exactly matches a reviewed hash lock."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
from pathlib import Path


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_exact(value: str) -> tuple[str, str]:
    if "==" not in value:
        raise ValueError(f"Expected exact requirement, got {value!r}")
    name, version = value.split("==", 1)
    if not name or not version:
        raise ValueError(f"Invalid exact requirement: {value!r}")
    return normalize(name), version


def read_lock(path: Path) -> dict[str, str]:
    expected = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        requirement = parts[0]
        hashes = [part for part in parts[1:] if part.startswith("--hash=sha256:")]
        if not hashes:
            raise ValueError(f"Lock entry lacks SHA-256 hash: {line!r}")
        name, version = parse_exact(requirement)
        if name in expected:
            raise ValueError(f"Duplicate lock entry: {name}")
        expected[name] = version
    return expected


def installed_distributions() -> dict[str, str]:
    installed = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            installed[normalize(name)] = dist.version
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--allow", action="append", default=[])
    args = parser.parse_args()

    expected = read_lock(args.lock)
    for value in args.allow:
        name, version = parse_exact(value)
        expected[name] = version

    installed = installed_distributions()
    missing = sorted(set(expected) - set(installed))
    extra = sorted(set(installed) - set(expected))
    mismatched = sorted(
        name for name in set(expected) & set(installed) if expected[name] != installed[name]
    )

    if missing or extra or mismatched:
        if missing:
            print("Missing locked distributions:", ", ".join(missing))
        if extra:
            print("Unreviewed installed distributions:", ", ".join(extra))
        for name in mismatched:
            print(f"Version mismatch for {name}: expected {expected[name]}, got {installed[name]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
