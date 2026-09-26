#!/usr/bin/env python3
"""Verify that CI lock metadata and the installed environment match exactly."""

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


def read_manifest(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " " in line or "--hash=" in line:
            raise ValueError(f"Manifest must contain one exact requirement per line: {line!r}")
        name, version = parse_exact(line)
        if name in expected:
            raise ValueError(f"Duplicate manifest entry: {name}")
        expected[name] = version
    return expected


def read_lock(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        requirement = parts[0]
        hashes = [part for part in parts[1:] if part.startswith("--hash=sha256:")]
        if len(hashes) != 1:
            raise ValueError(f"Lock entry must contain exactly one SHA-256 hash: {line!r}")
        name, version = parse_exact(requirement)
        if name in expected:
            raise ValueError(f"Duplicate lock entry: {name}")
        expected[name] = version
    return expected


def installed_distributions() -> dict[str, str]:
    records: dict[str, list[str]] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            records.setdefault(normalize(name), []).append(dist.version)

    duplicates = {name: versions for name, versions in records.items() if len(versions) > 1}
    if duplicates:
        details = "; ".join(
            f"{name}={','.join(versions)}" for name, versions in sorted(duplicates.items())
        )
        raise ValueError(f"Duplicate installed distributions detected: {details}")

    return {name: versions[0] for name, versions in records.items()}


def report_mapping_diff(label: str, expected: dict[str, str], actual: dict[str, str]) -> bool:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(
        name for name in set(expected) & set(actual) if expected[name] != actual[name]
    )
    if not (missing or extra or mismatched):
        return False
    if missing:
        print(f"{label} missing:", ", ".join(missing))
    if extra:
        print(f"{label} unexpected:", ", ".join(extra))
    for name in mismatched:
        print(f"{label} version mismatch for {name}: expected {expected[name]}, got {actual[name]}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--allow", action="append", default=[])
    args = parser.parse_args()

    manifest = read_manifest(args.manifest)
    locked = read_lock(args.lock)
    failed = report_mapping_diff("Lock/manifest", manifest, locked)

    expected_installed = dict(locked)
    for value in args.allow:
        name, version = parse_exact(value)
        expected_installed[name] = version

    try:
        installed = installed_distributions()
    except ValueError as exc:
        print(exc)
        return 1

    failed = report_mapping_diff("Installed environment", expected_installed, installed) or failed
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
