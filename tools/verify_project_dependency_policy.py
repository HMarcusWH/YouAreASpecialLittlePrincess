#!/usr/bin/env python3
"""Verify that selected project, build and locked dependencies form a closed reviewed graph."""

from __future__ import annotations

import argparse
import email.parser
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from verify_ci_lock import read_lock, read_lock_target, read_manifest, running_target

# The explicitly supported build configuration. Each backend maps to the
# distribution that must provide it through an exact reviewed build requirement.
SUPPORTED_BUILD_BACKENDS = {"setuptools.build_meta": "setuptools"}

# Legacy setuptools configuration files can supply dependency metadata and
# backend-reported build requirements (setup_requires) outside pyproject.toml.
PROHIBITED_BUILD_FILES = ("setup.py", "setup.cfg")

DYNAMIC_DEPENDENCY_FIELDS = ("dependencies", "optional-dependencies")

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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


def load_pyproject(pyproject: Path) -> dict:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def table(data: object, key: str) -> dict:
    value = data.get(key, {}) if isinstance(data, dict) else {}
    return value if isinstance(value, dict) else {}


def string_list(data: dict, key: str) -> list[str]:
    value = data.get(key, [])
    return value if is_string_list(value) else []


def build_configuration_errors(pyproject: Path, data: dict) -> list[str]:
    """Reject metadata/build configurations that can bypass the static policy."""
    errors: list[str] = []

    for name in PROHIBITED_BUILD_FILES:
        if (pyproject.parent / name).exists():
            errors.append(
                f"{name} is prohibited: legacy setuptools configuration can supply unreviewed "
                f"dependency metadata or backend-reported build requirements"
            )

    build_system = data.get("build-system")
    if not isinstance(build_system, dict):
        errors.append(
            "Missing [build-system] table: pip would fall back to an implicit, unreviewed "
            "setuptools legacy backend"
        )
    else:
        requires = build_system.get("requires")
        backend = build_system.get("build-backend")
        if not is_string_list(requires):
            errors.append("[build-system].requires must be an explicit list of requirement strings")
        if not isinstance(backend, str) or not backend:
            errors.append(
                "[build-system].build-backend must be declared: pip would otherwise fall back to "
                "the setuptools legacy backend"
            )
        elif backend not in SUPPORTED_BUILD_BACKENDS:
            supported = ", ".join(sorted(SUPPORTED_BUILD_BACKENDS))
            errors.append(f"Unsupported build backend {backend!r}; reviewed backends: {supported}")
        elif is_string_list(requires):
            provider = SUPPORTED_BUILD_BACKENDS[backend]
            declared = {normalize(match.group(0)) for raw in requires if (match := NAME.match(raw.strip()))}
            if provider not in declared:
                errors.append(f"[build-system].requires must declare the {backend} provider {provider}")
        if "backend-path" in build_system:
            errors.append("[build-system].backend-path is prohibited: in-tree backends are unreviewed hook code")

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("Missing [project] table: dependency metadata must be declared statically")
        return errors

    dynamic = project.get("dynamic", [])
    if not is_string_list(dynamic):
        errors.append("[project].dynamic must be a list of field names")
    else:
        for field in DYNAMIC_DEPENDENCY_FIELDS:
            if field in dynamic:
                errors.append(
                    f"Dynamic {field} are prohibited: backend-generated dependency metadata "
                    f"bypasses the reviewed manifest"
                )

    setuptools_dynamic = table(table(table(data, "tool"), "setuptools"), "dynamic")
    for field in DYNAMIC_DEPENDENCY_FIELDS:
        if field in setuptools_dynamic:
            errors.append(f"[tool.setuptools.dynamic].{field} is prohibited: declare dependencies statically")

    if not is_string_list(project.get("dependencies", [])):
        errors.append("[project].dependencies must be a list of requirement strings")
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict) or not all(is_string_list(group) for group in optional.values()):
        errors.append("[project.optional-dependencies] must map group names to requirement string lists")

    return errors


def dependency_records(data: dict, extras: list[str]) -> list[tuple[str, str, list[str]]]:
    # Malformed shapes are reported by build_configuration_errors(); only
    # well-formed requirement lists are interpreted here.
    project = table(data, "project")
    optional = table(project, "optional-dependencies")

    records: list[tuple[str, str, list[str]]] = []

    project_contexts = ["", *extras]
    for raw in string_list(project, "dependencies"):
        records.append((raw, "project.dependencies", project_contexts))

    for extra in extras:
        for raw in string_list(optional, extra):
            records.append((raw, f"project.optional-dependencies.{extra}", [extra]))

    for raw in string_list(table(data, "build-system"), "requires"):
        records.append((raw, "build-system.requires", [""]))

    return records


def validate(pyproject: Path, manifest: Path, extras: list[str]) -> list[str]:
    data = load_pyproject(pyproject)
    errors = build_configuration_errors(pyproject, data)
    reviewed = read_manifest(manifest)

    optional = table(table(data, "project"), "optional-dependencies")
    for extra in extras:
        if extra not in optional:
            errors.append(f"Unknown optional dependency group: {extra}")

    for raw, source, marker_extras in dependency_records(data, extras):
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            errors.append(f"Invalid requirement in {source}: {raw!r} ({exc})")
            continue

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
            continue

        # An isolated downstream source build resolves build-system.requires
        # from an index without our hashes; only an exact pin keeps it on the
        # reviewed release.
        if source == "build-system.requires" and not is_exact_pin(requirement, version):
            errors.append(
                f"Build requirement {requirement.name} must be pinned exactly to its reviewed version "
                f"{version}: {raw}"
            )

    return errors


def active_root_names(data: dict, extras: list[str]) -> set[str]:
    """Names activated by the selected pyproject surfaces (rejected forms excluded)."""
    roots: set[str] = set()
    for raw, _source, marker_extras in dependency_records(data, extras):
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue
        if requirement.url is None and not requirement.extras and marker_matches(requirement, marker_extras):
            roots.add(normalize(requirement.name))
    return roots


@dataclass(frozen=True)
class LockedWheel:
    filename: str
    name: str
    version: str
    requires: tuple[str, ...]


def read_wheel_metadata(path: Path):
    """Read the single top-level .dist-info/METADATA without installing or executing anything."""
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", name)]
        if len(candidates) != 1:
            raise ValueError(f"expected exactly one top-level .dist-info/METADATA, found {len(candidates)}")
        return email.parser.BytesHeaderParser().parsebytes(archive.read(candidates[0]))


def read_wheelhouse(wheelhouse: Path) -> tuple[dict[str, LockedWheel | None], list[str]]:
    """Map each distribution to its single readable wheel, or None when unusable (already reported)."""
    if not wheelhouse.is_dir():
        return {}, [f"Wheelhouse not found: {wheelhouse}"]

    found: dict[str, list[LockedWheel | None]] = {}
    errors: list[str] = []
    for path in sorted(wheelhouse.iterdir()):
        if not path.is_file() or path.suffix != ".whl":
            errors.append(f"Unexpected non-wheel artifact in wheelhouse: {path.name}")
            continue
        try:
            raw_name, version, _build, _tags = parse_wheel_filename(path.name)
        except InvalidWheelFilename as exc:
            errors.append(f"Invalid wheel filename {path.name}: {exc}")
            continue
        name = normalize(raw_name)
        entries = found.setdefault(name, [])
        try:
            metadata = read_wheel_metadata(path)
            metadata_version = Version(metadata.get("Version", ""))
        except (InvalidVersion, ValueError, zipfile.BadZipFile) as exc:
            errors.append(f"Unreadable wheel metadata in {path.name}: {exc}")
            entries.append(None)
            continue
        if normalize(metadata.get("Name", "")) != name or metadata_version != version:
            errors.append(
                f"Wheel METADATA identity {metadata.get('Name')}=={metadata.get('Version')} "
                f"does not match its filename {path.name}"
            )
            entries.append(None)
            continue
        entries.append(LockedWheel(path.name, name, str(version), tuple(metadata.get_all("Requires-Dist") or ())))

    wheels: dict[str, LockedWheel | None] = {}
    for name, entries in sorted(found.items()):
        if len(entries) > 1:
            # Never pick one by discovery order: the other could be what pip installs.
            filenames = ", ".join(sorted(entry.filename for entry in entries if entry is not None))
            errors.append(f"Duplicate wheels for {name}: {filenames or 'unreadable artifacts'}")
            wheels[name] = None
        else:
            wheels[name] = entries[0]
    return wheels, errors


def locked_graph_errors(
    pyproject: Path, lock: Path, wheelhouse: Path, extras: list[str], roots: list[str]
) -> tuple[list[str], int]:
    """Walk every active Requires-Dist edge from the reviewed roots through the locked wheels.

    Returns policy errors and the number of active edges inspected. Markers are
    evaluated for the running interpreter, which must match the lock's target.
    """
    target = read_lock_target(lock)
    running = running_target()
    if target is None:
        return [f"{lock} does not declare the interpreter/platform it was generated for"], 0
    if target != running:
        return [
            f"{lock} targets Python {target[0]} {target[1]} {target[2]} but the verifier runs on "
            f"Python {running[0]} {running[1]} {running[2]}; markers would be evaluated for the wrong environment"
        ], 0

    locked = read_lock(lock)
    wheels, errors = read_wheelhouse(wheelhouse)
    for name, version in sorted(locked.items()):
        wheel = wheels.get(name)
        if name not in wheels:
            errors.append(f"No authenticated wheel for locked {name}=={version} in {wheelhouse}")
        elif wheel is not None and Version(wheel.version) != Version(version):
            errors.append(f"Wheel {wheel.filename} does not match locked {name}=={version}")
    for name in sorted(set(wheels) - set(locked)):
        wheel = wheels[name]
        errors.append(f"Unexpected wheel outside the reviewed lock: {wheel.filename if wheel else name}")

    start = sorted(active_root_names(load_pyproject(pyproject), extras) | {normalize(root) for root in roots})
    for name in start:
        if name not in locked:
            errors.append(f"Reviewed root {name} is missing from the lock")

    environment = default_environment()
    environment["extra"] = ""  # upstream extras are never activated by the reviewed graph
    reached: set[str] = set()
    edges = 0
    pending = [name for name in start if name in locked]
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        wheel = wheels.get(name)
        if wheel is None:
            continue
        for raw in wheel.requires:
            label = f"{wheel.filename} Requires-Dist {raw!r}"
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                errors.append(f"Invalid requirement in locked metadata: {label} ({exc})")
                continue
            if requirement.marker is not None and not requirement.marker.evaluate(environment=environment):
                continue
            edges += 1
            if requirement.url is not None:
                errors.append(f"Direct URL dependency is prohibited in locked metadata: {label}")
                continue
            if requirement.extras:
                errors.append(
                    f"Dependency extras are prohibited until their transitive graph is reviewed: {label}"
                )
                continue
            child = normalize(requirement.name)
            if child not in locked:
                errors.append(f"Locked dependency edge leaves the reviewed lock: {label}")
                continue
            child_version = Version(locked[child])
            if requirement.specifier and not requirement.specifier.contains(child_version, prereleases=True):
                errors.append(f"Locked {child}=={child_version} does not satisfy {label}")
                continue
            pending.append(child)

    for name in sorted(set(locked) - reached):
        errors.append(f"Locked distribution is not reachable from a reviewed root: {name}=={locked[name]}")
    return errors, edges


def is_exact_pin(requirement: Requirement, version: Version) -> bool:
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1:
        return False
    specifier = specifiers[0]
    return specifier.operator == "==" and "*" not in specifier.version and Version(specifier.version) == version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--lock", type=Path, help="hash lock whose active Requires-Dist graph must be closed")
    parser.add_argument("--wheelhouse", type=Path, help="directory of the lock's authenticated wheels")
    parser.add_argument(
        "--root", action="append", default=[], help="additional reviewed root outside pyproject, e.g. pip"
    )
    args = parser.parse_args()
    if (args.lock is None) != (args.wheelhouse is None):
        parser.error("--lock and --wheelhouse must be given together")

    errors = validate(args.pyproject, args.manifest, args.extra)
    if args.lock is not None and not errors:
        graph_errors, edges = locked_graph_errors(args.pyproject, args.lock, args.wheelhouse, args.extra, args.root)
        errors += graph_errors
        if not graph_errors:
            print(f"Closed locked graph: {len(read_lock(args.lock))} distributions, {edges} active edges")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
