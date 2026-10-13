"""Verify all execution-relevant imports against the reviewed interpreter and wheels.

The wheelhouse is authenticated against the repository's hashed Python-specific
lock; installed RECORD files are intentionally *not* trusted. This is an
in-process consistency check under a trusted host/interpreter, not a sandbox.
"""
from __future__ import annotations

import hashlib
import io
import importlib
import importlib.metadata
import importlib.util
import marshal
import os
import re
import sys
import sysconfig
import types
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath

# Authenticate every wheel-installed payload except pip-generated RECORD metadata.
# In particular, native .so.5/.so.5.0 libraries are NOT Python modules and
# Path.suffix cannot identify them reliably.
_NATIVE_SUFFIXES = (".so", ".pyd", ".dll", ".dylib")
_CYTHON_VERSION_MODULE = re.compile(r"^_cython_[0-9]+_[0-9]+_[0-9]+$")


def _reviewed_virtual_cython_module(name: str, module) -> bool:
    """Narrow Cython runtime exception for synthetic modules emitted by
    authenticated native extensions. The trusted staged import boundary is
    essential; this check is not an independent process attestation.
    """
    return (
        (name == "cython_runtime" or _CYTHON_VERSION_MODULE.fullmatch(name) is not None)
        and type(module) is types.ModuleType
        and getattr(module, "__spec__", None) is None
        and getattr(module, "__file__", None) is None
        and getattr(module, "__loader__", None) is None
    )
LOCK_ENTRY = re.compile(r"^([a-zA-Z0-9_.-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})$")
ROOTS = ("evaluation", "princess_graphology", "princess_contracts", "princess_app")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheelhouse_path() -> Path:
    explicit = os.environ.get("QUALIFICATION_WHEELHOUSE")
    runner_temp = os.environ.get("RUNNER_TEMP")
    if explicit:
        return Path(explicit).resolve(strict=True)
    if runner_temp:
        return (Path(runner_temp) / "ci-wheelhouse").resolve(strict=True)
    raise ValueError("authenticated qualification wheelhouse required")


def _site_roots() -> tuple[Path, ...]:
    paths = sysconfig.get_paths()
    return tuple(dict.fromkeys(Path(paths[k]).resolve(strict=True)
                               for k in ("purelib", "platlib")))


@lru_cache(maxsize=4)
def _trusted_files(wheelhouse_name: str, lock_name: str, site_names: tuple[str, ...]):
    """Derive hashes directly from wheels whose complete archives match the lock."""
    wheelhouse, lock = Path(wheelhouse_name), Path(lock_name)
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise ValueError("untrusted wheelhouse")
    expected = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        hit = LOCK_ENTRY.fullmatch(line)
        if hit is None:
            raise ValueError("invalid reviewed wheel lock entry")
        name, version, digest = hit.groups()
        key = (_norm(name), version)
        if key in expected:
            raise ValueError("duplicate reviewed wheel name")
        expected[key] = digest

    site = Path(site_names[0])
    files = {}
    seen = set()
    for wheel in sorted(wheelhouse.iterdir()):
        if wheel.suffix != ".whl" or wheel.is_symlink() or not wheel.is_file():
            raise ValueError("untrusted wheelhouse entry")
        parts = wheel.name[:-4].split("-")
        if len(parts) < 5:
            raise ValueError("invalid reviewed wheel filename")
        key = (_norm(parts[0]), parts[1])
        if key not in expected or key in seen:
            raise ValueError("wheel not uniquely present in reviewed lock")
        seen.add(key)
        # One immutable archive snapshot: never hash a wheel by path and
        # reopen that pathname later (a second TOCTOU opportunity).
        archive_bytes = wheel.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != expected[key]:
            raise ValueError("wheel archive differs from independently reviewed lock")

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            if archive.testzip() is not None:
                raise ValueError("invalid reviewed wheel payload")
            names = set()
            for entry in archive.infolist():
                if entry.filename in names:
                    raise ValueError("duplicate wheel archive entry")
                names.add(entry.filename)
                entry_path = PurePosixPath(entry.filename)
                if entry.is_dir():
                    continue
                if (entry_path.is_absolute()
                        or any(part in (".", "..") for part in entry_path.parts)):
                    raise ValueError("unsafe reviewed wheel entry")
                parts = entry_path.parts
                if any(part in ("", ".", "..") for part in entry.filename.split("/")):
                    raise ValueError("unsafe reviewed wheel entry component")
                if len(parts) >= 2 and parts[0].endswith(".dist-info"):
                    # pip rewrites RECORD at installation time. All other
                    # wheel-supplied distribution metadata remains checked.
                    if parts[1] == "RECORD":
                        continue
                if parts[0].endswith(".data"):
                    if len(parts) < 3:
                        raise ValueError("unrecognized wheel data relocation")
                    scheme = parts[1]
                    mapping = sysconfig.get_paths()
                    target_root = {
                        "purelib": site, "platlib": Path(site_names[-1]),
                        "scripts": Path(mapping["scripts"]),
                        "data": Path(mapping["data"]),
                        "headers": Path(mapping["include"]),
                    }.get(scheme)
                    if target_root is None:
                        raise ValueError("unknown reviewed wheel install scheme")
                    target = target_root.joinpath(*parts[2:])
                else:
                    target = site.joinpath(*parts)
                target = target.absolute()
                if target in files:
                    raise ValueError("overlapping reviewed wheel payload")
                with archive.open(entry) as stream:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                files[target] = digest.hexdigest()
    if seen != set(expected):
        raise ValueError("missing reviewed wheel artifact")
    return files



def _is_native_artifact(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(_NATIVE_SUFFIXES) or ".so." in name or ".dylib." in name


def preflight_reviewed_environment(root: Path) -> None:
    """Validate installed executable bytes BEFORE numerical wheels are imported.

    The dependency manifest is taken from the original lock-authenticated
    archives, never from locally editable dist-info/RECORD files.
    """
    root = root.resolve(strict=True)
    sites = _site_roots()
    wheelhouse = _wheelhouse_path()
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    approved = _trusted_files(str(wheelhouse), str(lock), tuple(map(str, sites)))
    for path, digest in approved.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or redirected locked executable artifact")
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError("installed file differs from authenticated locked wheel")
        if path.suffix == ".py":
            # -B prevents writing caches, but CPython can still READ existing
            # timestamp-matched .pyc files. Verify all approved dependency
            # caches before adding site-packages to the import path.
            cache = Path(importlib.util.cache_from_source(str(path)))
            if cache.exists():
                if cache.is_symlink() or not cache.is_file():
                    raise ValueError("unreviewed installed bytecode cache")
                cached_bytes = cache.read_bytes()
                if (len(cached_bytes) < 16
                        or cached_bytes[:4] != importlib.util.MAGIC_NUMBER):
                    raise ValueError("unreviewed installed bytecode cache")
                actual_code = marshal.loads(cached_bytes[16:])
                if (not isinstance(actual_code, types.CodeType)
                        or not isinstance(actual_code.co_filename, str)
                        or len(actual_code.co_filename) > 4096):
                    raise ValueError("unreviewed installed bytecode cache")
                # compileall/pip may encode a relative or normalized filename;
                # that is informational, not executable bytecode. Disable
                # inheritance of this verifier module's future flags.
                expected_code = compile(
                    source, actual_code.co_filename, "exec", dont_inherit=True
                )
                if actual_code != expected_code:
                    raise ValueError("unreviewed installed bytecode cache")

    # Native dlopen() calls do not create Python sys.modules entries. Refuse
    # unreviewed loadable libraries in installed dependency locations.
    for site in sites:
        for native in site.rglob("*"):
            if _is_native_artifact(native):
                if (native.is_symlink() or not native.is_file()
                        or native.absolute() not in approved):
                    raise ValueError("unreviewed installed native library")


def _project_path(path: Path, root: Path) -> bool:
    allowed = (
        root / "evaluation",
        root / "src" / "princess_graphology",
        root / "src" / "princess_app",
        root / "src" / "princess_contracts",
        root / "tools",
        root / "tests",
        root / "apps" / "api",
        root / "apps" / "workers",
        root / "infra",
        root / "migrations",
        root / "docs" / "roadmap",
    )
    return any(path.is_relative_to(directory) for directory in allowed)


def _check_project_bytecode(module, source: Path) -> None:
    """Refuse a malicious timestamp-matched .pyc accepted by the import loader.

    The official isolated launcher additionally uses a newly created Git
    worktree, -B, and checks there are no inherited pycache files.
    """
    if source.suffix != ".py":
        return
    # A loaded module may erase or rewrite its own __cached__ metadata.
    # Derive the cache path from reviewed source instead.
    cache_path = Path(importlib.util.cache_from_source(str(source)))
    claimed = getattr(module, "__cached__", None)
    if claimed is not None and Path(claimed).resolve(strict=False) != cache_path.resolve(strict=False):
        raise ValueError("unverified cached project bytecode")
    if not cache_path.is_file():
        # The isolated official worker imports from a clean verified Git
        # worktree under -B and therefore has no caches to examine.
        if not sys.flags.dont_write_bytecode:
            raise ValueError("unverified cached project bytecode")
        return
    try:
        encoded = cache_path.read_bytes()
        if len(encoded) < 16:
            raise ValueError("malformed cached bytecode")
        # marshal backrefs and compileall's embedded filename can differ
        # without changing execution. Recompile authenticated source with
        # the recorded informational filename and *no* inherited future flags.
        actual = marshal.loads(encoded[16:])
        if (not isinstance(actual, types.CodeType)
                or not isinstance(actual.co_filename, str)
                or len(actual.co_filename) > 4096):
            raise ValueError("invalid cached project code object")
        expected = compile(
            source.read_bytes(), actual.co_filename, "exec", dont_inherit=True
        )
        if actual != expected:
            raise ValueError("cached project bytecode differs from reviewed source")
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        raise ValueError("unverified cached project bytecode") from exc


def verify_loaded_module_closure(root: Path) -> None:
    """Check every loaded module, including transitive/stdlib and native imports."""
    root = root.resolve(strict=True)
    wheelhouse = _wheelhouse_path()
    sites = _site_roots()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    target = f"{sys.version_info.major}{sys.version_info.minor}"
    lock = root / "requirements" / f"ci-py{target}.lock"
    files = _trusted_files(str(wheelhouse), str(lock), tuple(map(str, sites)))
    for name, module in tuple(sys.modules.items()):
        if module is None or name == "__main__" or (
            name == "__mp_main__" and module is sys.modules.get("__main__")
        ):
            # Script and multiprocessing aliases inherit the staged launcher.
            continue
        spec = getattr(module, "__spec__", None)
        origin = getattr(module, "__file__", None)
        spec_origin = getattr(spec, "origin", None)
        if origin is None:
            if _reviewed_virtual_cython_module(name, module):
                # Native Cython wheels create virtual runtime modules whose
                # metadata does not describe separate importable source files.
                continue
            if (spec_origin == "built-in"
                    and name in sys.builtin_module_names):
                continue
            if (spec_origin == "frozen"
                    and name.split(".")[0] in sys.stdlib_module_names):
                continue
            if spec_origin in (None, "namespace"):
                paths = getattr(module, "__path__", None)
                if paths is not None:
                    approved_roots = (*sites, stdlib, root / "src", root / "evaluation",
                                      root / "tools", root / "tests",
                                      root / "apps" / "api", root / "apps" / "workers",
                                      root / "infra", root / "migrations",
                                      root / "docs" / "roadmap")
                    try:
                        if all(any(Path(p).resolve(strict=True).is_relative_to(a)
                                   for a in approved_roots) for p in tuple(paths)):
                            continue
                    except (OSError, ValueError, AttributeError, ImportError, TypeError) as exc:
                        raise ValueError("unreviewed imported evaluation module") from exc
                parent_name, _, child = name.rpartition(".")
                parent = sys.modules.get(parent_name)
                if parent is not None and getattr(parent, child, None) is module:
                    # Alias modules inherit a parent whose actual source is
                    # separately authenticated in the same complete scan.
                    continue
                if _reviewed_virtual_cython_module(name, module):
                    # Cython extensions create runtime-only module objects
                    # without separately importable .py/.so files. Their
                    # native wheel artifacts are independently preverified.
                    continue
            raise ValueError("unreviewed imported evaluation module")
        try:
            path = Path(origin).resolve(strict=True)
            parent_name, _, child = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            native_alias = (spec is None and path.suffix in (".so", ".pyd")
                            and parent is not None and getattr(parent, child, None) is module)
            frozen_stdlib = (
                spec_origin == "frozen"
                and name.partition(".")[0] in sys.stdlib_module_names
                and path.is_relative_to(stdlib)
                and not any(path.is_relative_to(site) for site in sites)
            )
            # CPython sometimes supplies an informational __file__ for frozen
            # interpreter modules such as abc/io, while spec.origin is "frozen".
            # The host interpreter, not that .py source, owns their code.
            if (not (native_alias or frozen_stdlib) and
                    (not isinstance(spec_origin, str)
                     or Path(spec_origin).resolve(strict=True) != path)):
                raise ValueError("import origin and executed path disagree")
            paths = getattr(module, "__path__", None)
            if paths and not all(
                any(Path(p).resolve(strict=True).is_relative_to(allowed)
                    for allowed in (*sites, stdlib, root / "src", root / "evaluation", root / "tools", root / "tests",
                                    root / "apps" / "api", root / "apps" / "workers",
                                    root / "infra", root / "migrations",
                                    root / "docs" / "roadmap"))
                for p in paths
            ):
                raise ValueError("unreviewed package import search path")
            if any(path.is_relative_to(s) for s in sites):
                expected = files.get(path)
                if expected is None or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("unreviewed installed executable file")
            elif _project_path(path, root):
                if path.suffix != ".py":
                    raise ValueError("unapproved project code artifact")
                # pytest assertion-rewrites its own test modules; those are
                # not imported by the staged qualification subprocess.
                if not path.is_relative_to(root / "tests"):
                    _check_project_bytecode(module, path)
            elif path.is_relative_to(stdlib):
                # The system Python interpreter/stdlib is part of the reviewed
                # runner trust anchor; never accept a repo-local stdlib shadow.
                if path.is_relative_to(root):
                    raise ValueError("repository standard-library shadow import")
            else:
                raise ValueError("unreviewed import outside interpreter and locked distributions")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError("unreviewed imported evaluation module") from exc
