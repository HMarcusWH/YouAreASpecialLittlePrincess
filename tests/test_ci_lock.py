"""Regression tests for the T00 CI lock and dependency policy."""

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
