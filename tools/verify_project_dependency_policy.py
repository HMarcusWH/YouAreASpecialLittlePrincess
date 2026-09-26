#!/usr/bin/env python3
"""Verify that selected project, build and locked dependencies form a closed reviewed graph."""

from __future__ import annotations

import argparse
import email.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from packaging.markers import Marker, Variable, default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from render_ci_workflow import require_regular_file, verified_targets

from verify_ci_lock import read_lock, read_lock_target, read_manifest, running_target

# The explicitly supported build configuration. Each backend maps to the
# distribution that must provide it through an exact reviewed build requirement.
SUPPORTED_BUILD_BACKENDS = {"setuptools.build_meta": "setuptools"}

# Legacy setuptools configuration files can supply dependency metadata and
# backend-reported build requirements (setup_requires) outside pyproject.toml.
PROHIBITED_BUILD_FILES = ("setup.py", "setup.cfg")

DYNAMIC_DEPENDENCY_FIELDS = ("dependencies", "optional-dependencies")

# A lock is stamped with a Python minor, system and machine. These marker
# variables are not fixed by that target, so a marker using them can change
# value between interpreters the lock and requires-python both cover.
UNFIXED_MARKER_VARIABLES = frozenset({
    "python_full_version", "implementation_version", "platform_release", "platform_version",
    "platform_python_implementation", "implementation_name",
})

BACKEND_HOOKS = ("get_requires_for_build_wheel", "get_requires_for_build_editable", "get_requires_for_build_sdist")

# Build outputs and caches never feed the backend's view of the project.
SANDBOX_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"
)

# Executed as `python -I -B -c RUNNER BACKEND HOOK RESULT_PATH` inside the sandbox copy.
# Isolated mode (-I) keeps the working directory, PYTHONPATH and the user site
# off sys.path from interpreter start-up, so a committed socket.py or json.py
# cannot run in place of these imports. Socket egress is denied
# before the backend is imported, the project tree is stripped from sys.path
# again as a second guard, and backend output is diverted so only the JSON
# result file is trusted.
BACKEND_HOOK_RUNNER = r"""
import contextlib, importlib, json, os, socket, sys

backend_name, hook, result_path = sys.argv[1:4]
egress = []

def deny(*args, **kwargs):
    egress.append(repr(args[1:3] if args and isinstance(args[0], socket.socket) else args[:2]))
    raise OSError("network access is denied while capturing build requirements")

socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.socket.sendto = deny
socket.create_connection = deny
socket.getaddrinfo = deny

cwd = os.getcwd()
sys.path[:] = [entry for entry in sys.path if entry not in ("", ".", cwd)]
result = {"requires": None, "error": None, "egress": egress}
try:
    module_name, _, attribute = backend_name.partition(":")
    backend = importlib.import_module(module_name)
    for part in filter(None, attribute.split(".")):
        backend = getattr(backend, part)
    function = getattr(backend, hook, None)
    with contextlib.redirect_stdout(sys.stderr):
        requires = [] if function is None else function(None)
    if not isinstance(requires, list) or not all(isinstance(item, str) for item in requires):
        raise TypeError(f"returned {requires!r}, not a list of strings")
    result["requires"] = requires
except BaseException as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def marker_state(marker: Marker, environment: dict[str, str]) -> bool | None:
    """Evaluate a marker for the lock target; None when it depends on a variable the target does not fix."""
    return _marker_items_state(marker._markers, environment)


def _marker_items_state(items: list, environment: dict[str, str]) -> bool | None:
    # packaging's marker list: atoms, nested lists and "and"/"or", with "and"
    # binding tighter. Unknown atoms propagate with three-valued logic.
    groups: list[list[bool | None]] = [[]]
    for item in items:
        if item == "or":
            groups.append([])
        elif isinstance(item, list):
            groups[-1].append(_marker_items_state(item, environment))
        elif isinstance(item, tuple):
            if any(isinstance(node, Variable) and node.value in UNFIXED_MARKER_VARIABLES for node in item):
                groups[-1].append(None)
            else:
                groups[-1].append(Marker(" ".join(node.serialize() for node in item)).evaluate(environment))
    results = [False if False in group else None if None in group else True for group in groups]
    return True if True in results else None if None in results else False


def marker_matches(requirement: Requirement, extras: list[str]) -> bool:
    """Active unless the marker is false for every interpreter/platform the lock target covers."""
    if requirement.marker is None:
        return True

    contexts = extras or [""]
    for extra in contexts:
        environment = default_environment()
        environment["extra"] = extra
        if marker_state(requirement.marker, environment) is not False:
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


def unconditional_names(requirements: list[str]) -> set[str]:
    """Names of parseable requirements without an environment marker."""
    names = set()
    for raw in requirements:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue  # reported by validate()
        if requirement.marker is None:
            names.add(normalize(requirement.name))
    return names


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
            if provider not in unconditional_names(requires):
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
        for field in dynamic:
            if field in DYNAMIC_DEPENDENCY_FIELDS:
                errors.append(
                    f"Dynamic {field} are prohibited: backend-generated dependency metadata "
                    f"bypasses the reviewed manifest"
                )
            else:
                errors.append(
                    f"Dynamic {field} is prohibited: setuptools may import project code to compute it "
                    f"while the build hooks run"
                )

    setuptools = table(table(data, "tool"), "setuptools")
    for field in table(setuptools, "dynamic"):
        if field in DYNAMIC_DEPENDENCY_FIELDS:
            errors.append(f"[tool.setuptools.dynamic].{field} is prohibited: declare dependencies statically")
        else:
            errors.append(f"[tool.setuptools.dynamic].{field} is prohibited: declare metadata statically")
    if "cmdclass" in setuptools:
        errors.append("[tool.setuptools].cmdclass is prohibited: custom commands run project code in the build hooks")

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


class UnsupportedWorkflowConfiguration(ValueError):
    """Non-canonical workflow/targets cannot supply evidence of mandatory coverage."""


def ci_matrix(workflow: Path) -> list[tuple[str, str, str]]:
    """Read reviewed target JSON only after exact verification of the entire workflow.

    No YAML parser, ignored job controls, fake matrix text or optional test jobs.
    """
    if not workflow.is_file():
        return []
    try:
        targets = verified_targets(workflow.absolute().parents[2], workflow)
    except (OSError, ValueError, TypeError, IndexError) as exc:
        raise UnsupportedWorkflowConfiguration(str(exc)) from exc
    return [(t["python"], t["manifest"], t["lock"]) for t in targets]


def interpreter_coverage(requirements_dir: Path, workflow: Path | None = None) -> tuple[set[tuple[int, int]], list[str]]:
    """Python minors whose target-stamped lock has its manifest and a CI matrix job, plus coverage errors.

    A lock header alone is not reviewed evidence: the minor counts only when
    CI actually downloads, installs and tests that lock on that Python.
    """
    workflow = workflow or requirements_dir.resolve().parent / ".github" / "workflows" / "ci.yml"
    root = requirements_dir.absolute().parent
    minors: set[tuple[int, int]] = set()
    errors: list[str] = []
    try:
        jobs = ci_matrix(workflow)
    except UnsupportedWorkflowConfiguration as exc:
        jobs = []
        errors.append(f"{workflow.name} {exc}; no lock counts as tested")
    for python, manifest_name, lock_name in jobs:
        if not (root / lock_name).is_file() or not (root / manifest_name).is_file():
            errors.append(f"CI target {python} lacks its manifest/lock; coverage is incomplete")
    for lock in sorted(requirements_dir.glob("ci-py*.lock")):
        try:
            require_regular_file(lock)
            if lock.with_suffix(".txt").exists():
                require_regular_file(lock.with_suffix(".txt"))
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue
        target = read_lock_target(lock)
        if target is None or target[1:] != ("Linux", "x86_64"):
            errors.append(f"{lock.name} has no supported Linux x86_64 target stamp")
            continue
        manifest = lock.with_suffix(".txt")
        relative = lock.resolve().relative_to(root).as_posix()
        job = (target[0], manifest.resolve().relative_to(root).as_posix(), relative)
        if not manifest.is_file():
            errors.append(f"{relative} has no matching manifest {manifest.name}; the lock is not reviewed evidence")
        elif job not in jobs:
            errors.append(f"{relative} has no CI matrix job for Python {target[0]} in {workflow.name}; "
                          f"its interpreter is not reviewed")
        else:
            major, minor = target[0].split(".")
            minors.add((int(major), int(minor)))
    return minors, errors


def reviewed_interpreters(requirements_dir: Path, workflow: Path | None = None) -> set[tuple[int, int]]:
    """Python minors with a target-stamped lock, its manifest and a CI matrix job."""
    return interpreter_coverage(requirements_dir, workflow)[0]


def requires_python_errors(data: dict, reviewed: set[tuple[int, int]]) -> list[str]:
    """requires-python must advertise exactly the interpreters that have reviewed locks."""
    if not reviewed:
        return ["No reviewed interpreter locks found; requires-python cannot be checked"]
    raw = table(data, "project").get("requires-python")
    supported = ", ".join(f"{major}.{minor}" for major, minor in sorted(reviewed))
    if not isinstance(raw, str) or not raw.strip():
        return [f"[project].requires-python must bound support to the reviewed interpreters ({supported})"]
    try:
        spec = SpecifierSet(raw)
    except InvalidSpecifier as exc:
        return [f"Invalid [project].requires-python {raw!r}: {exc}"]

    # Only whole-minor >= and < bounds are accepted. Their intersection is one
    # interval whose boundaries can be compared exactly without sampling patches
    # or enumerating a finite grid of minors. Exclusions, wildcards and patch-only
    # bounds are outside this reviewed whole-minor contract.
    shapes = []
    for clause in sorted(spec, key=str):
        try:
            version = Version(clause.version)
        except InvalidVersion:
            version = None
        if (
            clause.operator not in (">=", "<")
            or version is None
            or len(version.release) < 2
            or version.epoch
            or version.is_prerelease
            or version.is_postrelease
            or version.local
            or any(version.release[2:])
        ):
            shapes.append(f"requires-python clause {str(clause)!r} is not a whole-minor bound; use only '>=X.Y' and '<X.Y'")
    if shapes:
        return shapes

    lower = [Version(c.version).release[:2] for c in spec if c.operator == ">="]
    upper = [Version(c.version).release[:2] for c in spec if c.operator == "<"]
    if not lower or not upper:
        return ["requires-python needs both a finite lower and upper whole-minor bound"]
    first, last = min(reviewed), max(reviewed)
    if first[0] != last[0] or len(reviewed) != last[1] - first[1] + 1:
        return ["reviewed interpreters must be a contiguous set of whole minors"]
    expected_upper = (last[0], last[1] + 1)
    if max(lower) != first or min(upper) != expected_upper:
        return [f"requires-python {raw!r} must equal the reviewed whole-minor interval "
                f">={first[0]}.{first[1]},<{expected_upper[0]}.{expected_upper[1]}"]
    return []


def validate(pyproject: Path, manifest: Path, extras: list[str],
             reviewed_pythons: set[tuple[int, int]] | None = None) -> list[str]:
    data = load_pyproject(pyproject)
    errors = build_configuration_errors(pyproject, data)
    if reviewed_pythons is not None:
        errors += requires_python_errors(data, reviewed_pythons)
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

        # Build requirements are unconditional in the supported configuration:
        # a marker could hide a requirement from this runner's checks while an
        # isolated build elsewhere installs it, or drop the backend provider.
        if source == "build-system.requires" and requirement.marker is not None:
            errors.append(f"Environment markers are prohibited in build-system.requires: {raw}")
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
            # A marker that depends on a variable the lock target does not fix
            # (python_full_version, platform_release, ...) counts as active.
            if requirement.marker is not None and marker_state(requirement.marker, environment) is False:
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


def capture_backend_requirements(
    project_root: Path, backend: str, *, python: str = sys.executable, timeout: float = 300
) -> tuple[dict[str, list[str]], list[str]]:
    """Ask the reviewed backend which extra build requirements it would report.

    pip never calls these hooks under --no-build-isolation, so CI cannot see
    them otherwise, while an ordinary isolated source build installs them.
    Each hook runs in its own process on a temporary copy of the project.
    """
    reported: dict[str, list[str]] = {}
    errors: list[str] = []
    # -I ignores PYTHON* variables, so -B replaces PYTHONDONTWRITEBYTECODE.
    environment = dict(os.environ, PIP_NO_INDEX="1", PIP_NO_INPUT="1")
    with tempfile.TemporaryDirectory(prefix="backend-hooks-") as tmp:
        sandbox = Path(tmp) / "project"
        shutil.copytree(project_root, sandbox, symlinks=True, ignore=SANDBOX_IGNORE)
        for hook in BACKEND_HOOKS:
            result_path = Path(tmp) / f"{hook}.json"
            try:
                completed = subprocess.run(
                    [python, "-I", "-B", "-c", BACKEND_HOOK_RUNNER, backend, hook, str(result_path)],
                    cwd=sandbox,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                errors.append(f"{backend} {hook} did not finish within {timeout} seconds")
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                tail = completed.stderr.strip().splitlines()[-1:] or ["no output"]
                errors.append(f"{backend} {hook} produced no result (exit {completed.returncode}): {tail[0]}")
                continue
            if result["egress"]:
                errors.append(f"{backend} {hook} attempted network access: {', '.join(result['egress'])}")
            if result["error"]:
                errors.append(f"{backend} {hook} failed: {result['error']}")
            elif result["requires"] is not None:
                reported[hook] = result["requires"]
    return reported, errors


def backend_requirement_errors(reported: dict[str, list[str]], reviewed: dict[str, str], declared: set[str]) -> list[str]:
    """Backend-reported requirements must already be exact reviewed build-system requirements."""
    errors: list[str] = []
    for hook, requirements in reported.items():
        for raw in requirements:
            label = f"{hook} reported {raw!r}"
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                errors.append(f"Invalid backend-reported requirement: {label} ({exc})")
                continue
            if requirement.url is not None:
                errors.append(f"Direct URL dependency is prohibited in backend-reported requirements: {label}")
                continue
            if requirement.extras:
                errors.append(f"Dependency extras are prohibited in backend-reported requirements: {label}")
                continue
            # Validated whatever the marker says: a requirement inactive on this
            # runner can still be installed by an isolated build elsewhere.
            name = normalize(requirement.name)
            if name not in reviewed:
                errors.append(f"Backend-reported build requirement missing from reviewed manifest: {label}")
                continue
            if requirement.specifier and not requirement.specifier.contains(Version(reviewed[name]), prereleases=True):
                errors.append(f"Reviewed version {name}=={reviewed[name]} does not satisfy {label}")
                continue
            if name not in declared:
                errors.append(
                    f"Backend-reported build requirement is not declared in [build-system].requires: {label}"
                )
    return errors


def is_exact_pin(requirement: Requirement, version: Version) -> bool:
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1:
        return False
    specifier = specifiers[0]
    return specifier.operator == "==" and "*" not in specifier.version and Version(specifier.version) == version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument(
        "--requirements-dir", type=Path, help="directory of target-stamped ci-py*.lock files (default: <pyproject dir>/requirements)"
    )
    parser.add_argument(
        "--workflow", type=Path, help="CI workflow whose matrix must test every lock (default: <pyproject dir>/.github/workflows/ci.yml)"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--lock", type=Path, help="hash lock whose active Requires-Dist graph must be closed")
    parser.add_argument("--wheelhouse", type=Path, help="directory of the lock's authenticated wheels")
    parser.add_argument(
        "--root", action="append", default=[], help="additional reviewed root outside pyproject, e.g. pip"
    )
    parser.add_argument(
        "--backend-requirements",
        action="store_true",
        help="run the reviewed backend's get_requires_for_build_* hooks in an egress-denied sandbox copy",
    )
    args = parser.parse_args(argv)
    if (args.lock is None) != (args.wheelhouse is None):
        parser.error("--lock and --wheelhouse must be given together")

    requirements_dir = args.requirements_dir or args.pyproject.resolve().parent / "requirements"
    workflow = args.workflow or args.pyproject.resolve().parent / ".github" / "workflows" / "ci.yml"
    reviewed, errors = interpreter_coverage(requirements_dir, workflow)
    errors += validate(args.pyproject, args.manifest, args.extra, reviewed)
    # Later stages trust the static configuration (backend allowlist, no
    # setup.py/setup.cfg); never execute backend code when it failed.
    if args.lock is not None and not errors:
        graph_errors, edges = locked_graph_errors(args.pyproject, args.lock, args.wheelhouse, args.extra, args.root)
        errors += graph_errors
        if not graph_errors:
            print(f"Closed locked graph: {len(read_lock(args.lock))} distributions, {edges} active edges")
    if args.backend_requirements and not errors:
        data = load_pyproject(args.pyproject)
        build_system = table(data, "build-system")
        reported, hook_errors = capture_backend_requirements(
            args.pyproject.resolve().parent, build_system["build-backend"]
        )
        declared = {normalize(Requirement(raw).name) for raw in string_list(build_system, "requires")}
        hook_errors += backend_requirement_errors(reported, read_manifest(args.manifest), declared)
        errors += hook_errors
        if not hook_errors:
            summary = ", ".join(f"{hook.rsplit('_', 1)[-1]}={reported[hook]}" for hook in BACKEND_HOOKS)
            print(f"Backend-reported build requirements: {summary}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
