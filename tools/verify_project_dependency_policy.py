#!/usr/bin/env python3
"""Verify that selected project dependencies are reviewed before local installation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from verify_ci_lock import read_manifest


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def selected_requirements(pyproject: Path, extras: list[str]) -> list[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extra in extras:
        if extra not in optional:
            raise ValueError(f"Unknown optional dependency group: {extra}")
        requirements.extend(optional[extra])
    return requirements


def validate(pyproject: Path, manifest: Path, extras: list[str]) -> list[str]:
    reviewed = read_manifest(manifest)
    errors: list[str] = []

    for raw in selected_requirements(pyproject, extras):
        requirement = Requirement(raw)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue

        name = normalize(requirement.name)
        if requirement.url is not None:
            errors.append(f"Direct URL dependency is prohibited in reviewed CI scope: {raw}")
            continue

        if name not in reviewed:
            errors.append(f"Dependency missing from reviewed manifest: {requirement.name}")
            continue

        version = Version(reviewed[name])
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            errors.append(
                f"Reviewed version for {requirement.name} does not satisfy {requirement.specifier}: {version}"
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
