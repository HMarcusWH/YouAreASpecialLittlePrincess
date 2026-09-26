"""Regression tests for the T00 CI lock and dependency policy."""

import subprocess
import venv
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import verify_ci_lock
import verify_project_dependency_policy


def fake_dist(name: str, version: str):
    return SimpleNamespace(metadata={"Name": name}, version=version)


REVIEWED_BUILD_SYSTEM = """
[build-system]
requires = ["setuptools==84.0.0", "wheel==0.48.0"]
build-backend = "setuptools.build_meta"
"""
REVIEWED_TOOLCHAIN = "setuptools==84.0.0\nwheel==0.48.0\n"


def write_policy_fixture(tmp_path, body: str, manifest: str, *, build_system: str | None = REVIEWED_BUILD_SYSTEM):
    """Write a pyproject/manifest pair; the reviewed build system is added unless the body declares one."""
    pyproject = tmp_path / "pyproject.toml"
    manifest_path = tmp_path / "manifest.txt"
    if "[build-system]" not in body and build_system is not None:
        body = build_system + body
    names = {line.split("==", 1)[0] for line in manifest.splitlines() if "==" in line}
    toolchain = "".join(line + "\n" for line in REVIEWED_TOOLCHAIN.splitlines() if line.split("==", 1)[0] not in names)
    pyproject.write_text(body.strip() + "\n", encoding="utf-8")
    manifest_path.write_text(toolchain + manifest, encoding="utf-8")
    return pyproject, manifest_path


def test_duplicate_installed_distributions_are_rejected(monkeypatch):
    monkeypatch.setattr(
        verify_ci_lock.importlib.metadata,
        "distributions",
        lambda: [
            fake_dist("Example-Pkg", "1.0"),
            fake_dist("example_pkg", "1.0"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate installed distributions"):
        verify_ci_lock.installed_distributions()


def test_direct_url_dependency_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg @ https://example.com/example_pkg-1.0-py3-none-any.whl"]

[project.optional-dependencies]
dev = []
""",
        "example-pkg==1.0\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Direct URL dependency is prohibited" in error for error in errors)


def test_selected_dependency_missing_from_manifest_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg>=1"]

[project.optional-dependencies]
dev = ["pytest>=9"]
""",
        "example-pkg==1.2\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == ["Dependency missing from reviewed manifest: pytest (project.optional-dependencies.dev)"]


def test_reviewed_version_must_satisfy_project_specifier(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg>=2"]

[project.optional-dependencies]
dev = []
""",
        "example-pkg==1.9\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("does not satisfy" in error for error in errors)


def test_optional_group_marker_uses_selected_extra_context(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = [
  "example-pkg @ https://example.com/example_pkg-1.0-py3-none-any.whl ; extra == 'dev'"
]
""",
        "example-pkg==1.0\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Direct URL dependency is prohibited" in error for error in errors)


def test_inactive_optional_marker_does_not_require_manifest_entry(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = ["example-pkg>=1 ; extra == 'docs'"]
""",
        "",
    )

    assert verify_project_dependency_policy.validate(pyproject, manifest, ["dev"]) == []


def test_requested_dependency_extras_are_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["basepkg[feature]>=1"]

[project.optional-dependencies]
dev = []
""",
        "basepkg==1.2\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == [
        "Dependency extras are prohibited until their transitive graph is reviewed: "
        "basepkg[feature] in project.dependencies"
    ]


def test_build_system_direct_url_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
requires = ["setuptools @ https://example.com/setuptools.whl"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = []
""",
        "setuptools==84.0.0\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Direct URL dependency is prohibited in build-system.requires" in error for error in errors)


def test_build_system_requirement_must_match_reviewed_manifest(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
requires = ["setuptools>=85"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = []
""",
        "setuptools==84.0.0\n",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any(
        "Reviewed version for setuptools does not satisfy >=85" in error
        and "build-system.requires" in error
        for error in errors
    )


MINIMAL_PROJECT = """
[project]
name = "demo"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = []
"""


def test_reviewed_build_configuration_passes(tmp_path):
    pyproject, manifest = write_policy_fixture(tmp_path, MINIMAL_PROJECT, "")

    assert verify_project_dependency_policy.validate(pyproject, manifest, ["dev"]) == []


@pytest.mark.parametrize("manifest_name", ["ci-py310.txt", "ci-py311.txt", "ci-py312.txt"])
def test_repository_pyproject_satisfies_every_reviewed_manifest(manifest_name):
    root = Path(__file__).resolve().parents[1]
    errors = verify_project_dependency_policy.validate(
        root / "pyproject.toml", root / "requirements" / manifest_name, ["dev"]
    )
    assert errors == []


def test_missing_build_system_table_is_rejected(tmp_path):
    # pip would otherwise supply setuptools>=40.8.0 with the legacy backend.
    pyproject, manifest = write_policy_fixture(tmp_path, MINIMAL_PROJECT, "", build_system=None)

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Missing [build-system] table" in error for error in errors)


def test_missing_build_backend_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
requires = ["setuptools==84.0.0", "wheel==0.48.0"]
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("build-backend must be declared" in error for error in errors)


def test_missing_build_requires_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
build-backend = "setuptools.build_meta"
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("[build-system].requires must be an explicit list" in error for error in errors)


@pytest.mark.parametrize("backend", ["setuptools.build_meta:__legacy__", "hatchling.build", "local_backend"])
def test_unreviewed_build_backend_is_rejected(tmp_path, backend):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        f"""
[build-system]
requires = ["setuptools==84.0.0", "wheel==0.48.0"]
build-backend = "{backend}"
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Unsupported build backend" in error for error in errors)


def test_in_tree_backend_path_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
requires = ["setuptools==84.0.0", "wheel==0.48.0"]
build-backend = "setuptools.build_meta"
backend-path = ["."]
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("backend-path is prohibited" in error for error in errors)


def test_build_backend_provider_must_be_declared(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        """
[build-system]
requires = ["wheel==0.48.0"]
build-backend = "setuptools.build_meta"
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == ["[build-system].requires must declare the setuptools.build_meta provider setuptools"]


@pytest.mark.parametrize("requirement", ["setuptools>=84", "setuptools==84.*", "setuptools", "setuptools==84.0.0,<85"])
def test_build_requirement_must_be_an_exact_reviewed_pin(tmp_path, requirement):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        f"""
[build-system]
requires = ["{requirement}", "wheel==0.48.0"]
build-backend = "setuptools.build_meta"
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == [
        f"Build requirement setuptools must be pinned exactly to its reviewed version 84.0.0: {requirement}"
    ]


@pytest.mark.parametrize(
    "requirement",
    [
        # Codex review of PR #12: an inactive marker skipped manifest and exact-pin
        # checks while the raw name still counted as declaring the backend provider.
        "setuptools>=1; python_version < '3'",
        "setuptools==84.0.0; python_version >= '3'",
    ],
)
def test_build_requirements_must_be_unconditional(tmp_path, requirement):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        f"""
[build-system]
requires = ["{requirement}", "wheel==0.48.0"]
build-backend = "setuptools.build_meta"
""" + MINIMAL_PROJECT,
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == [
        "[build-system].requires must declare the setuptools.build_meta provider setuptools",
        f"Environment markers are prohibited in build-system.requires: {requirement}",
    ]


@pytest.mark.parametrize("field", ["dependencies", "optional-dependencies"])
def test_dynamic_dependency_metadata_is_rejected(tmp_path, field):
    body = MINIMAL_PROJECT.replace('dependencies = []\n', "").replace("[project.optional-dependencies]\ndev = []\n", "")
    body = body.replace('version = "0.1.0"', f'version = "0.1.0"\ndynamic = ["{field}"]')
    body += f"""
[tool.setuptools.dynamic]
{field} = {{file = ["dynamic-requirements.txt"]}}
""" if field == "dependencies" else """
[tool.setuptools.dynamic.optional-dependencies]
dev = {file = ["dynamic-requirements.txt"]}
"""
    pyproject, manifest = write_policy_fixture(tmp_path, body, "")
    (tmp_path / "dynamic-requirements.txt").write_text(
        "evilpkg @ https://example.invalid/evilpkg-1.0-py3-none-any.whl\n", encoding="utf-8"
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, [] if field == "dependencies" else ["dev"])
    assert any(f"Dynamic {field} are prohibited" in error for error in errors)
    assert any(f"[tool.setuptools.dynamic].{field} is prohibited" in error for error in errors)


def test_missing_project_table_is_rejected(tmp_path):
    pyproject, manifest = write_policy_fixture(tmp_path, "", "")

    errors = verify_project_dependency_policy.validate(pyproject, manifest, [])
    assert any("Missing [project] table" in error for error in errors)


@pytest.mark.parametrize("filename", ["setup.py", "setup.cfg"])
def test_legacy_setuptools_configuration_is_rejected(tmp_path, filename):
    # setup_requires in either file is reported by get_requires_for_build_* and
    # installed by isolated builds, while --no-build-isolation CI never sees it.
    pyproject, manifest = write_policy_fixture(tmp_path, MINIMAL_PROJECT, "")
    (tmp_path / filename).write_text(
        "[options]\nsetup_requires = unreviewed-helper\n" if filename == "setup.cfg"
        else "from setuptools import setup\nsetup(setup_requires=['unreviewed-helper'])\n",
        encoding="utf-8",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any(error.startswith(f"{filename} is prohibited") for error in errors)


def test_malformed_requirement_is_reported_not_raised(tmp_path):
    pyproject, manifest = write_policy_fixture(
        tmp_path,
        MINIMAL_PROJECT.replace('dependencies = []', 'dependencies = ["not a requirement!!"]'),
        "",
    )

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert len(errors) == 1 and errors[0].startswith("Invalid requirement in project.dependencies")


def write_wheel(wheelhouse, name: str, version: str, requires=(), *, filename=None, metadata_name=None, extra_dist_info=False):
    """Write a metadata-only wheel; the verifier never installs or imports it."""
    wheelhouse.mkdir(exist_ok=True)
    stem = name.replace("-", "_")
    path = wheelhouse / (filename or f"{stem}-{version}-py3-none-any.whl")
    metadata = ["Metadata-Version: 2.1", f"Name: {metadata_name or name}", f"Version: {version}"]
    metadata += [f"Requires-Dist: {requirement}" for requirement in requires]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{stem}-{version}.dist-info/METADATA", "\n".join(metadata) + "\n\nDescription body\n")
        if extra_dist_info:
            archive.writestr(f"{stem}_shadow-{version}.dist-info/METADATA", "Name: shadow\nVersion: 9\n")
    return path


def write_graph_fixture(tmp_path, wheels: dict, dependencies=("parentpkg>=1",), target=None):
    """Create pyproject, manifest, target-stamped lock and wheelhouse for a locked graph."""
    toolchain = {"setuptools": ("84.0.0", ()), "wheel": ("0.48.0", ())}
    wheels = {**toolchain, **wheels}
    manifest = "".join(f"{name}=={version}\n" for name, (version, _requires) in wheels.items())
    body = MINIMAL_PROJECT.replace("dependencies = []", f"dependencies = {list(dependencies)!r}".replace("'", '"'))
    pyproject, manifest_path = write_policy_fixture(tmp_path, body, manifest)
    python, system, machine = target or verify_ci_lock.running_target()
    lock = tmp_path / "ci.lock"
    lock.write_text(
        f"# Python {python}; {system} {machine}.\n"
        + "".join(f"{name}=={version} --hash=sha256:{'0' * 64}\n" for name, (version, _r) in wheels.items()),
        encoding="utf-8",
    )
    wheelhouse = tmp_path / "wheelhouse"
    for name, (version, requires) in wheels.items():
        write_wheel(wheelhouse, name, version, requires)
    return pyproject, manifest_path, lock, wheelhouse


def graph_errors(pyproject, lock, wheelhouse, roots=()):
    errors, _edges = verify_project_dependency_policy.locked_graph_errors(pyproject, lock, wheelhouse, ["dev"], list(roots))
    return errors


def test_closed_locked_graph_passes(tmp_path):
    pyproject, manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path,
        {
            "parentpkg": ("1.0", ["Child_Pkg>=1,<2"]),
            "child-pkg": ("1.5", ["wheel==0.48.0"]),
        },
    )

    assert verify_project_dependency_policy.validate(pyproject, manifest, ["dev"]) == []
    errors, edges = verify_project_dependency_policy.locked_graph_errors(pyproject, lock, wheelhouse, ["dev"], [])
    assert errors == []
    assert edges == 2


def test_locked_requires_dist_extra_is_rejected(tmp_path):
    # PR #10 post-merge finding 1: child[feature] activates dependencies that
    # neither the lock, the exact-environment check nor pip check sees.
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path,
        {
            "parentpkg": ("1.0", ["childpkg[feature]>=1"]),
            "childpkg": ("1.0", ['grandchild>=1; extra == "feature"']),
        },
    )

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors[0].startswith("Dependency extras are prohibited until their transitive graph is reviewed")
    assert "childpkg[feature]>=1" in errors[0]
    assert errors[1:] == ["Locked distribution is not reachable from a reviewed root: childpkg==1.0"]


def test_locked_requires_dist_direct_url_is_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path,
        {
            "parentpkg": ("1.0", ["childpkg @ https://example.invalid/childpkg-1.0-py3-none-any.whl"]),
            "childpkg": ("1.0", []),
        },
    )

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors[0].startswith("Direct URL dependency is prohibited in locked metadata")


def test_locked_requires_dist_outside_lock_is_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", ["unlocked-pkg"])})

    assert graph_errors(pyproject, lock, wheelhouse) == [
        "Locked dependency edge leaves the reviewed lock: parentpkg-1.0-py3-none-any.whl Requires-Dist 'unlocked-pkg'"
    ]


def test_locked_requires_dist_version_must_be_satisfied(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path, {"parentpkg": ("1.0", ["childpkg>=2"]), "childpkg": ("1.0", [])}
    )

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors[0] == (
        "Locked childpkg==1.0 does not satisfy parentpkg-1.0-py3-none-any.whl Requires-Dist 'childpkg>=2'"
    )


def test_inactive_locked_markers_are_not_edges(tmp_path):
    # Extras-only and other-interpreter edges are inactive for this lock; even
    # URL/extra forms there cannot be activated because extras are never requested.
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path,
        {
            "parentpkg": (
                "1.0",
                [
                    'pytest[testing]>=9; extra == "dev"',
                    'docs-helper @ https://example.invalid/d.whl ; extra == "docs"',
                    'legacy-backport>=1; python_version < "3.0"',
                ],
            ),
        },
    )

    errors, edges = verify_project_dependency_policy.locked_graph_errors(pyproject, lock, wheelhouse, ["dev"], [])
    assert errors == []
    assert edges == 0


def test_unreachable_locked_distribution_is_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path, {"parentpkg": ("1.0", []), "stale-pkg": ("3.0", [])}
    )

    assert graph_errors(pyproject, lock, wheelhouse) == [
        "Locked distribution is not reachable from a reviewed root: stale-pkg==3.0"
    ]
    assert graph_errors(pyproject, lock, wheelhouse, roots=["Stale_Pkg"]) == []


def test_duplicate_wheels_for_one_distribution_are_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    write_wheel(wheelhouse, "parentpkg", "1.0", ["unreviewed"], filename="ParentPkg-1.0-py2.py3-none-any.whl",
                metadata_name="ParentPkg")

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors == [
        "Duplicate wheels for parentpkg: ParentPkg-1.0-py2.py3-none-any.whl, parentpkg-1.0-py3-none-any.whl"
    ]


def test_wheel_with_duplicate_dist_info_metadata_is_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    write_wheel(wheelhouse, "parentpkg", "1.0", [], extra_dist_info=True)

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert len(errors) == 1
    assert errors[0].startswith("Unreadable wheel metadata in parentpkg-1.0-py3-none-any.whl: expected exactly one")


def test_wheel_metadata_identity_must_match_filename(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    write_wheel(wheelhouse, "parentpkg", "1.0", [], metadata_name="impostor")

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors[0] == (
        "Wheel METADATA identity impostor==1.0 does not match its filename parentpkg-1.0-py3-none-any.whl"
    )


def test_wheelhouse_must_equal_lock(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    write_wheel(wheelhouse, "extra-pkg", "2.0", [])
    (wheelhouse / "wheel-0.48.0-py3-none-any.whl").unlink()
    (wheelhouse / "sneaky-1.0.tar.gz").write_bytes(b"")

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert "Unexpected non-wheel artifact in wheelhouse: sneaky-1.0.tar.gz" in errors
    assert any(error.startswith("No authenticated wheel for locked wheel==0.48.0") for error in errors)
    assert "Unexpected wheel outside the reviewed lock: extra_pkg-2.0-py3-none-any.whl" in errors


def test_lock_target_must_match_running_interpreter(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path, {"parentpkg": ("1.0", [])}, target=("2.7", "Plan9", "mips")
    )

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert len(errors) == 1 and "markers would be evaluated for the wrong environment" in errors[0]


def test_lock_without_target_header_is_rejected(tmp_path):
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    lock.write_text("\n".join(lock.read_text(encoding="utf-8").splitlines()[1:]) + "\n", encoding="utf-8")

    errors = graph_errors(pyproject, lock, wheelhouse)
    assert errors == [f"{lock} does not declare the interpreter/platform it was generated for"]


@pytest.mark.parametrize("version", ["310", "311", "312"])
def test_repository_locks_declare_their_target(version):
    root = Path(__file__).resolve().parents[1]
    python, system, machine = verify_ci_lock.read_lock_target(root / "requirements" / f"ci-py{version}.lock")
    assert (python.replace(".", ""), system, machine) == (version, "Linux", "x86_64")


def backend_python(project: Path) -> Path:
    return project.parent / "venv" / "bin" / "python"


def fake_backend(tmp_path, body: str, name: str = "fake_backend"):
    """Install a fake PEP 517 backend into a throwaway venv (outside the project tree) and return the project root.

    Hooks run under python -I, which ignores PYTHONPATH, so the backend is made
    importable the way a real one is: through the interpreter's site-packages.
    """
    backends = tmp_path / "backends"
    backends.mkdir(exist_ok=True)
    (backends / f"{name}.py").write_text(body, encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "pyproject.toml").write_text(REVIEWED_BUILD_SYSTEM + MINIMAL_PROJECT, encoding="utf-8")
    python = backend_python(project)
    if not python.exists():
        venv.create(python.parent.parent, with_pip=False, symlinks=True)
        purelib = subprocess.run(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        (Path(purelib) / "fake_backends.pth").write_text(f"{backends}\n", encoding="utf-8")
    return project


REPORTING_BACKEND = """
def get_requires_for_build_wheel(config_settings=None):
    return {wheel!r}

def get_requires_for_build_editable(config_settings=None):
    return {editable!r}
"""


def backend_errors(project, backend="fake_backend", manifest=None, declared=("setuptools", "wheel")):
    reported, errors = verify_project_dependency_policy.capture_backend_requirements(
        project, backend, python=str(backend_python(project)), timeout=60
    )
    reviewed = manifest or {"setuptools": "84.0.0", "wheel": "0.48.0", "helper": "1.0"}
    return reported, errors + verify_project_dependency_policy.backend_requirement_errors(
        reported, reviewed, set(declared)
    )


def test_backend_reported_requirements_outside_the_lock_are_rejected(tmp_path):
    # PR #10 post-merge finding 3: --no-build-isolation never asks the backend,
    # but an isolated source build installs whatever it reports.
    project = fake_backend(
        tmp_path,
        REPORTING_BACKEND.format(wheel=["unreviewed-helper>=1"], editable=["helper[fast]", "x @ https://example.invalid/x.whl"]),
    )

    reported, errors = backend_errors(project)
    assert reported == {
        "get_requires_for_build_wheel": ["unreviewed-helper>=1"],
        "get_requires_for_build_editable": ["helper[fast]", "x @ https://example.invalid/x.whl"],
        "get_requires_for_build_sdist": [],
    }
    assert errors == [
        "Backend-reported build requirement missing from reviewed manifest: "
        "get_requires_for_build_wheel reported 'unreviewed-helper>=1'",
        "Dependency extras are prohibited in backend-reported requirements: "
        "get_requires_for_build_editable reported 'helper[fast]'",
        "Direct URL dependency is prohibited in backend-reported requirements: "
        "get_requires_for_build_editable reported 'x @ https://example.invalid/x.whl'",
    ]


def test_backend_reported_requirement_must_be_a_declared_reviewed_build_requirement(tmp_path):
    project = fake_backend(
        tmp_path,
        REPORTING_BACKEND.format(wheel=["wheel==0.48.0", 'legacy; python_version < "3"'], editable=["helper>=1", "wheel>=0.40"]),
    )

    _reported, errors = backend_errors(project)
    assert errors == [
        # Inactive on this interpreter, but an isolated build elsewhere would install it.
        "Backend-reported build requirement missing from reviewed manifest: "
        "get_requires_for_build_wheel reported 'legacy; python_version < \"3\"'",
        "Backend-reported build requirement is not declared in [build-system].requires: "
        "get_requires_for_build_editable reported 'helper>=1'",
    ]
    _reported, errors = backend_errors(project, manifest={"setuptools": "84.0.0", "wheel": "0.47.0", "helper": "1.0",
                                                          "legacy": "1.0"},
                                       declared=("setuptools", "wheel", "helper", "legacy"))
    assert errors == [
        "Reviewed version wheel==0.47.0 does not satisfy get_requires_for_build_wheel reported 'wheel==0.48.0'",
    ]


def test_backend_hooks_cannot_reach_the_network(tmp_path):
    project = fake_backend(
        tmp_path,
        """
import socket

def get_requires_for_build_wheel(config_settings=None):
    try:
        socket.create_connection(("192.0.2.1", 9), timeout=1)
    except OSError:
        pass  # a backend swallowing the failure must still be reported
    return []
""",
    )

    reported, errors = backend_errors(project)
    assert reported["get_requires_for_build_wheel"] == []
    assert len(errors) == 1
    assert errors[0].startswith("fake_backend get_requires_for_build_wheel attempted network access: ")
    assert "192.0.2.1" in errors[0]


def test_backend_hooks_run_on_a_disposable_copy(tmp_path):
    project = fake_backend(
        tmp_path,
        """
import pathlib

def get_requires_for_build_wheel(config_settings=None):
    pathlib.Path("generated.egg-info").mkdir()
    print("noise on stdout is ignored")
    return []
""",
    )

    reported, errors = backend_errors(project)
    assert errors == []
    assert reported["get_requires_for_build_wheel"] == []
    assert not (project / "generated.egg-info").exists()


def test_in_tree_module_cannot_pose_as_the_backend(tmp_path):
    project = fake_backend(tmp_path, "", name="unrelated")
    (project / "intree_backend.py").write_text(
        "def get_requires_for_build_wheel(config_settings=None):\n    return ['evil']\n", encoding="utf-8"
    )

    reported, errors = backend_errors(project, backend="intree_backend")
    assert reported == {}
    assert len(errors) == 3
    assert all("ModuleNotFoundError" in error for error in errors)


def test_project_modules_cannot_shadow_the_runner_imports(tmp_path):
    # Codex review of #12: the hook process started in the project copy with
    # the working directory on sys.path, so a committed socket.py ran before
    # the egress guard was installed.
    project = fake_backend(tmp_path, REPORTING_BACKEND.format(wheel=[], editable=[]))
    ran = tmp_path / "shadow-ran"
    ran.mkdir()
    for module in ("socket", "json", "contextlib"):
        (project / f"{module}.py").write_text(
            f"open({str(ran / module)!r}, 'w').close()\nraise SystemExit('project {module}.py was imported')\n",
            encoding="utf-8",
        )

    reported, errors = backend_errors(project)
    assert errors == []
    assert reported == {hook: [] for hook in verify_project_dependency_policy.BACKEND_HOOKS}
    assert sorted(path.name for path in ran.iterdir()) == []


def test_pythonpath_cannot_supply_the_backend(tmp_path, monkeypatch):
    project = fake_backend(tmp_path, "", name="unrelated")
    injected = tmp_path / "injected"
    injected.mkdir()
    (injected / "env_backend.py").write_text(
        "def get_requires_for_build_wheel(config_settings=None):\n    return ['evil']\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(injected))

    reported, errors = backend_errors(project, backend="env_backend")
    assert reported == {}
    assert len(errors) == 3
    assert all("ModuleNotFoundError" in error for error in errors)


def test_failing_or_malformed_backend_hooks_are_errors(tmp_path):
    project = fake_backend(
        tmp_path,
        """
def get_requires_for_build_wheel(config_settings=None):
    raise SystemExit("setup() aborted")

def get_requires_for_build_editable(config_settings=None):
    return "wheel"
""",
    )

    reported, errors = backend_errors(project)
    assert reported == {"get_requires_for_build_sdist": []}
    assert errors == [
        "fake_backend get_requires_for_build_wheel failed: SystemExit: setup() aborted",
        "fake_backend get_requires_for_build_editable failed: TypeError: returned 'wheel', not a list of strings",
    ]


def test_repository_backend_reports_no_unreviewed_build_requirements():
    pytest.importorskip("setuptools.build_meta")
    root = Path(__file__).resolve().parents[1]

    reported, errors = verify_project_dependency_policy.capture_backend_requirements(root, "setuptools.build_meta")
    assert errors == []
    assert reported == {hook: [] for hook in verify_project_dependency_policy.BACKEND_HOOKS}


def test_backend_hooks_never_run_when_static_policy_fails(tmp_path, monkeypatch, capsys):
    project = fake_backend(tmp_path, "raise SystemExit('backend must not be imported')\n")
    (project / "setup.py").write_text("raise SystemExit('setup.py must not run')\n", encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(REVIEWED_TOOLCHAIN, encoding="utf-8")
    calls = []
    monkeypatch.setattr(verify_project_dependency_policy, "capture_backend_requirements", lambda *a, **k: calls.append(a))

    exit_code = verify_project_dependency_policy.main(
        ["--pyproject", str(project / "pyproject.toml"), "--manifest", str(manifest), "--backend-requirements"]
    )
    assert exit_code == 1
    assert calls == []
    assert "setup.py is prohibited" in capsys.readouterr().out


def test_cli_combines_static_graph_and_backend_checks(tmp_path, monkeypatch, capsys):
    pyproject, manifest, lock, wheelhouse = write_graph_fixture(tmp_path, {"parentpkg": ("1.0", [])})
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.1.0"', 'version = "0.1.0"\nrequires-python = ">=3.10,<3.13"'),
        encoding="utf-8",
    )
    write_reviewed_interpreters(tmp_path, (10, 11, 12))
    monkeypatch.setattr(
        verify_project_dependency_policy,
        "capture_backend_requirements",
        lambda root, backend: ({hook: [] for hook in verify_project_dependency_policy.BACKEND_HOOKS}, []),
    )

    exit_code = verify_project_dependency_policy.main([
        "--pyproject", str(pyproject), "--manifest", str(manifest), "--extra", "dev",
        "--lock", str(lock), "--wheelhouse", str(wheelhouse), "--backend-requirements",
    ])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Closed locked graph: 3 distributions, 0 active edges" in output
    assert "Backend-reported build requirements: wheel=[], editable=[], sdist=[]" in output


REVIEWED_PYTHONS = {(3, 10), (3, 11), (3, 12)}


def write_reviewed_interpreters(root, minors, ci_minors=None, manifests=None):
    """Target-stamped locks, their manifests and a CI workflow matrix under root."""
    requirements = root / "requirements"
    requirements.mkdir(exist_ok=True)
    for minor in minors:
        (requirements / f"ci-py3{minor}.lock").write_text(f"# Python 3.{minor}; Linux x86_64.\n", encoding="utf-8")
    for minor in minors if manifests is None else manifests:
        (requirements / f"ci-py3{minor}.txt").write_text("", encoding="utf-8")
    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        "jobs:\n  test:\n    strategy:\n      matrix:\n        include:\n" + "".join(
            f"          - python: '3.{minor}'\n            manifest: requirements/ci-py3{minor}.txt\n"
            f"            lock: requirements/ci-py3{minor}.lock\n"
            for minor in (minors if ci_minors is None else ci_minors)
        ),
        encoding="utf-8",
    )
    return requirements, workflow
WHOLE_MINOR = "is not a whole-minor bound; use only '>=X.Y' and '<X.Y'"


@pytest.mark.parametrize(
    ("requires_python", "expected"),
    [
        (">=3.10,<3.13", []),
        # Codex review of #12: widening the advertised range passed every other check.
        (">=3.9", ["requires-python '>=3.9' advertises Python versions with no reviewed lock or CI job: "
                   "3.9, 3.13, 3.14, 3.15 and 84 more"]),
        (">=3.10,<3.14", ["requires-python '>=3.10,<3.14' advertises Python versions with no reviewed lock or CI job: 3.13"]),
        (">=3.10,<3.12", ["requires-python '>=3.10,<3.12' does not fully support reviewed Python 3.12"]),
        (">=3.10.0,<3.13.0", []),
        (None, ["[project].requires-python must bound support to the reviewed interpreters (3.10, 3.11, 3.12)"]),
        # Codex re-review of #12: probing two patches per minor missed partial
        # exclusions, so only whole-minor >= and < bounds are accepted.
        (">=3.10,<3.13,!=3.11.5", [f"requires-python clause '!=3.11.5' {WHOLE_MINOR}"]),
        (">=3.10,<3.13,!=3.11.*", [f"requires-python clause '!=3.11.*' {WHOLE_MINOR}"]),
        (">=3.10,<3.12.5", [f"requires-python clause '<3.12.5' {WHOLE_MINOR}"]),
        (">3.9.99,<3.13", [f"requires-python clause '>3.9.99' {WHOLE_MINOR}"]),
        ("~=3.10", [f"requires-python clause '~=3.10' {WHOLE_MINOR}"]),
        (">=3.10,<3.13,<=3.12", [f"requires-python clause '<=3.12' {WHOLE_MINOR}"]),
        (">=3.10rc1,<3.13", [f"requires-python clause '>=3.10rc1' {WHOLE_MINOR}"]),
    ],
)
def test_requires_python_matches_reviewed_interpreters(tmp_path, requires_python, expected):
    body = MINIMAL_PROJECT if requires_python is None else MINIMAL_PROJECT.replace(
        'version = "0.1.0"', f'version = "0.1.0"\nrequires-python = "{requires_python}"'
    )
    pyproject, manifest = write_policy_fixture(tmp_path, body, "")

    assert verify_project_dependency_policy.validate(pyproject, manifest, ["dev"], REVIEWED_PYTHONS) == expected


def test_reviewed_interpreters_come_from_the_repository_locks():
    root = Path(__file__).resolve().parents[1]
    assert verify_project_dependency_policy.reviewed_interpreters(root / "requirements") == REVIEWED_PYTHONS
    data = verify_project_dependency_policy.load_pyproject(root / "pyproject.toml")
    assert verify_project_dependency_policy.requires_python_errors(data, REVIEWED_PYTHONS) == []


def test_cli_checks_requires_python_against_discovered_locks(tmp_path, capsys):
    pyproject, manifest = write_policy_fixture(
        tmp_path, MINIMAL_PROJECT.replace('version = "0.1.0"', 'version = "0.1.0"\nrequires-python = ">=3.10"'), ""
    )
    assert verify_project_dependency_policy.main(["--pyproject", str(pyproject), "--manifest", str(manifest)]) == 1
    assert "No reviewed interpreter locks found" in capsys.readouterr().out

    write_reviewed_interpreters(tmp_path, (10, 11, 12))
    assert verify_project_dependency_policy.main(["--pyproject", str(pyproject), "--manifest", str(manifest)]) == 1
    assert "advertises Python versions with no reviewed lock or CI job: 3.13" in capsys.readouterr().out


def test_repository_ci_matrix_tests_every_lock():
    root = Path(__file__).resolve().parents[1]
    assert verify_project_dependency_policy.interpreter_coverage(root / "requirements") == (REVIEWED_PYTHONS, [])


def test_lock_without_manifest_or_ci_job_is_not_reviewed(tmp_path, capsys):
    # Codex review of #12: a target-stamped ci-py313.lock let requires-python
    # advertise 3.13 although CI never installed or tested that lock.
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12, 13), ci_minors=(10, 11, 12))
    reviewed, errors = verify_project_dependency_policy.interpreter_coverage(requirements, workflow)
    assert reviewed == REVIEWED_PYTHONS
    assert errors == ["requirements/ci-py313.lock has no CI matrix job for Python 3.13 in ci.yml; its interpreter is not reviewed"]

    (requirements / "ci-py313.txt").unlink()
    reviewed, errors = verify_project_dependency_policy.interpreter_coverage(requirements, workflow)
    assert errors == ["requirements/ci-py313.lock has no matching manifest ci-py313.txt; the lock is not reviewed evidence"]

    workflow.unlink()
    assert verify_project_dependency_policy.interpreter_coverage(requirements, workflow)[0] == set()

    write_reviewed_interpreters(tmp_path, (10, 11, 12, 13), ci_minors=(10, 11, 12))
    pyproject, manifest = write_policy_fixture(
        tmp_path, MINIMAL_PROJECT.replace('version = "0.1.0"', 'version = "0.1.0"\nrequires-python = ">=3.10,<3.14"'), ""
    )
    assert verify_project_dependency_policy.main(["--pyproject", str(pyproject), "--manifest", str(manifest)]) == 1
    output = capsys.readouterr().out
    assert "ci-py313.lock has no CI matrix job" in output
    assert "advertises Python versions with no reviewed lock or CI job: 3.13" in output


FAKE_313 = "- python: '3.13'\n{pad}  manifest: requirements/ci-py313.txt\n{pad}  lock: requirements/ci-py313.lock\n"


@pytest.mark.parametrize(
    "decoy",
    [
        # Codex review of #12: the matrix was found by regex over the whole file.
        "    steps:\n      - name: docs\n        run: |\n          " + FAKE_313.format(pad="          "),
        "        # " + FAKE_313.format(pad="        # "),
        "  other:\n    strategy:\n      matrix:\n        include:\n          " + FAKE_313.format(pad="          "),
        "  lint:\n    env:\n      NOTE: >\n        " + FAKE_313.format(pad="        "),
    ],
    ids=["block-scalar", "comment", "other-job", "folded-scalar"],
)
def test_only_real_matrix_entries_count_as_ci_jobs(tmp_path, decoy):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12, 13), ci_minors=(10, 11, 12))
    workflow.write_text(workflow.read_text(encoding="utf-8") + decoy, encoding="utf-8")
    reviewed, errors = verify_project_dependency_policy.interpreter_coverage(requirements, workflow)
    assert reviewed == REVIEWED_PYTHONS
    assert errors == ["requirements/ci-py313.lock has no CI matrix job for Python 3.13 in ci.yml; its interpreter is not reviewed"]


def test_flow_style_matrix_fails_closed(tmp_path):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10,))
    workflow.write_text(
        "jobs:\n  test:\n    strategy:\n      matrix:\n        include: [{python: '3.10', "
        "manifest: requirements/ci-py310.txt, lock: requirements/ci-py310.lock}]\n",
        encoding="utf-8",
    )
    reviewed, errors = verify_project_dependency_policy.interpreter_coverage(requirements, workflow)
    assert reviewed == set() and len(errors) == 1


def test_repository_workflow_matrix_is_parsed_structurally():
    root = Path(__file__).resolve().parents[1]
    assert verify_project_dependency_policy.ci_matrix(root / ".github" / "workflows" / "ci.yml") == [
        (f"3.{minor}", f"requirements/ci-py3{minor}.txt", f"requirements/ci-py3{minor}.lock") for minor in (10, 11, 12)
    ]


UNTRUSTED_MATRIX = "; the CI matrix is read only from plain block YAML, so no lock counts as tested"


@pytest.mark.parametrize(
    ("snippet", "reason"),
    [
        # Codex review of #12: YAML reads these 3.13 lines as text inside the
        # 3.12 entry's note, but the reader counted a second job.
        ('            note: "harmless\n          ' + FAKE_313.format(pad="          ") + '            end"\n',
         "line 15: a quoted scalar continues onto the next line"),
        ("            note: 'harmless\n          " + FAKE_313.format(pad="          ") + "            end'\n",
         "line 15: a quoted scalar continues onto the next line"),
        ("            note: harmless\n              " + FAKE_313.format(pad="              "),
         "line 16: a scalar from the line above continues onto this line"),
        ("            note: [harmless,\n          " + FAKE_313.format(pad="          ") + "            ]\n",
         "line 15: a flow collection continues onto the next line"),
        ("          note: |\n          " + FAKE_313.format(pad="          "),
         "line 15: indentation does not continue an open mapping or sequence"),
        ("            python: '3.13'\n", "line 15: duplicate key 'python'"),
        ("            note: &entry x\n", "line 15: '&' (anchor, alias, tag or reserved indicator) is not resolved"),
        ("            <<: *entry\n", "line 15: neither a 'key: value' mapping line nor a '- ' item"),
        ("\t    note: x\n", "line 15: tabs in indentation"),
    ],
    ids=["double-quoted", "single-quoted", "plain", "flow", "misindented", "duplicate-key", "anchor", "merge-key", "tab"],
)
def test_yaml_outside_the_read_subset_untrusts_the_whole_matrix(tmp_path, snippet, reason):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12, 13), ci_minors=(10, 11, 12))
    workflow.write_text(workflow.read_text(encoding="utf-8") + snippet, encoding="utf-8")
    reviewed, errors = verify_project_dependency_policy.interpreter_coverage(requirements, workflow)
    assert reviewed == set()
    assert errors[0] == f"ci.yml {reason}{UNTRUSTED_MATRIX}"
    assert len(errors) == 5


def test_values_nested_in_an_entry_are_not_entries(tmp_path):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12, 13), ci_minors=(10, 11, 12))
    workflow.write_text(workflow.read_text(encoding="utf-8") + "            extra:\n              "
                        + FAKE_313.format(pad="              "), encoding="utf-8")
    assert verify_project_dependency_policy.interpreter_coverage(requirements, workflow) == (
        REVIEWED_PYTHONS,
        ["requirements/ci-py313.lock has no CI matrix job for Python 3.13 in ci.yml; its interpreter is not reviewed"],
    )


def test_sequences_at_their_key_indentation_are_read(tmp_path):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11))
    workflow.write_text(
        "jobs:\n  test:\n    strategy:\n      matrix:\n        include:\n" + "".join(
            f"        - python: '3.{minor}'\n          manifest: requirements/ci-py3{minor}.txt\n"
            f"          lock: requirements/ci-py3{minor}.lock\n" for minor in (10, 11)
        ) + "    steps:\n    - run: pytest\n",
        encoding="utf-8",
    )
    assert verify_project_dependency_policy.interpreter_coverage(requirements, workflow) == ({(3, 10), (3, 11)}, [])


def test_unquoted_versions_are_numbers_not_matrix_strings(tmp_path):
    # YAML reads an unquoted 3.10 as the number 3.1, so that job would not run Python 3.10.
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10,))
    workflow.write_text(workflow.read_text(encoding="utf-8").replace("python: '3.10'", "python: 3.10"), encoding="utf-8")
    assert verify_project_dependency_policy.interpreter_coverage(requirements, workflow) == (
        set(), ["requirements/ci-py310.lock has no CI matrix job for Python 3.10 in ci.yml; its interpreter is not reviewed"]
    )


@pytest.mark.parametrize(
    ("project_lines", "tool", "expected"),
    [
        # Codex review of #12: setuptools imports the module named by an attr
        # directive while the build hooks run, executing committed code.
        ('dynamic = ["version"]', '[tool.setuptools.dynamic]\nversion = {attr = "demo.VERSION"}',
         ["Dynamic version is prohibited: setuptools may import project code to compute it while the build hooks run",
          "[tool.setuptools.dynamic].version is prohibited: declare metadata statically"]),
        ('version = "0.1.0"\ndynamic = ["readme"]', "",
         ["Dynamic readme is prohibited: setuptools may import project code to compute it while the build hooks run"]),
        ('version = "0.1.0"', '[tool.setuptools.cmdclass]\negg_info = "demo.build:EggInfo"',
         ["[tool.setuptools].cmdclass is prohibited: custom commands run project code in the build hooks"]),
    ],
)
def test_executable_build_configuration_is_rejected(tmp_path, project_lines, tool, expected):
    body = MINIMAL_PROJECT.replace('version = "0.1.0"', project_lines) + "\n" + tool + "\n"
    pyproject, manifest = write_policy_fixture(tmp_path, body, "")
    assert verify_project_dependency_policy.validate(pyproject, manifest, ["dev"]) == expected


@pytest.mark.parametrize(
    ("marker", "state"),
    [
        ('python_version >= "3"', True),
        ('python_version < "3"', False),
        ('python_full_version == "3.11.5"', None),
        ('platform_release == "6.1"', None),
        ('platform_python_implementation != "PyPy" and extra == "type"', False),
        ('platform_python_implementation != "PyPy" or python_version >= "3"', True),
        ('python_version < "3" or (implementation_name == "pypy" and os_name == "posix")', None),
    ],
)
def test_marker_state_is_unknown_for_variables_the_lock_does_not_fix(marker, state):
    from packaging.markers import Marker, default_environment

    environment = dict(default_environment(), extra="")
    assert verify_project_dependency_policy.marker_state(Marker(marker), environment) is state


def test_patch_level_markers_count_as_active_edges(tmp_path):
    # Codex review of #12: a python_full_version marker was evaluated only for
    # the runner's patch, hiding a dependency another 3.x patch would install.
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        tmp_path, {"parentpkg": ("1.0", ['childpkg; python_full_version == "3.11.5"'])}
    )
    assert graph_errors(pyproject, lock, wheelhouse) == [
        "Locked dependency edge leaves the reviewed lock: parentpkg-1.0-py3-none-any.whl "
        "Requires-Dist 'childpkg; python_full_version == \"3.11.5\"'"
    ]

    locked = tmp_path / "locked"
    locked.mkdir()
    pyproject, _manifest, lock, wheelhouse = write_graph_fixture(
        locked,
        {"parentpkg": ("1.0", ['childpkg>=1; python_full_version == "3.11.5"',
                               'ignored; platform_python_implementation != "PyPy" and extra == "type"']),
         "childpkg": ("1.2", [])},
    )
    errors, edges = verify_project_dependency_policy.locked_graph_errors(pyproject, lock, wheelhouse, ["dev"], [])
    assert (errors, edges) == ([], 1)
