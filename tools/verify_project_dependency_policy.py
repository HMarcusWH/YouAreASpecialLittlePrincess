#!/usr/bin/env python3
"""Verify that selected project and build dependencies are reviewed before installation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from verify_ci_lock import read_manifest


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def marker_matches(requirement: Requirement, extras: list[str]) -> bool:
    if requirement.marker is None:
        return True

    contexts = extras or [""]
    for extra in contexts:
        environment = default_environment()
        environment["extra"] = extra
        if requirement.marker.evaluate(environment=environment):
            return True
    return False


def dependency_records(pyproject: Path, extras: list[str]) -> list[tuple[str, str, list[str]]]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    optional = project.get("optional-dependencies", {})

    records: list[tuple[str, str, list[str]]] = []

    project_contexts = ["", *extras]
    for raw in project.get("dependencies", []):
        records.append((raw, "project.dependencies", project_contexts))

    for extra in extras:
        if extra not in optional:
            raise ValueError(f"Unknown optional dependency group: {extra}")
        for raw in optional[extra]:
            records.append((raw, f"project.optional-dependencies.{extra}", [extra]))

    for raw in data.get("build-system", {}).get("requires", []):
        records.append((raw, "build-system.requires", [""]))

    return records


def validate(pyproject: Path, manifest: Path, extras: list[str]) -> list[str]:
    reviewed = read_manifest(manifest)
    errors: list[str] = []

    for raw, source, marker_extras in dependency_records(pyproject, extras):
        requirement = Requirement(raw)

        # These forms can activate additional unreviewed artifacts. Reject them
        # anywhere in the selected dependency surfaces, even if a marker is
        # inactive on this particular runner.
        if requirement.url is not None:
            errors.append(f"Direct URL dependency is prohibited in {source}: {raw}")
            continue
        if requirement.extras:
            requested = ",".join(sorted(requirement.extras))
            errors.append(
                f"Dependency extras are prohibited until their transitive graph is reviewed: "
                f"{requirement.name}[{requested}] in {source}"
            )
            continue

        if not marker_matches(requirement, marker_extras):
            continue

        name = normalize(requirement.name)
        if name not in reviewed:
            errors.append(f"Dependency missing from reviewed manifest: {requirement.name} ({source})")
            continue

        version = Version(reviewed[name])
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            errors.append(
                f"Reviewed version for {requirement.name} does not satisfy "
                f"{requirement.specifier}: {version} ({source})"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args()

    errors = validate(args.pyproject, args.manifest, args.extra)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
