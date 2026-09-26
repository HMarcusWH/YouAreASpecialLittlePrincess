"""Regression tests for the T00 CI lock and dependency policy."""

from types import SimpleNamespace

import pytest

import verify_ci_lock
import verify_project_dependency_policy


def fake_dist(name: str, version: str):
    return SimpleNamespace(metadata={"Name": name}, version=version)


def write_policy_fixture(tmp_path, body: str, manifest: str):
    pyproject = tmp_path / "pyproject.toml"
    manifest_path = tmp_path / "manifest.txt"
    pyproject.write_text(body.strip() + "\n", encoding="utf-8")
    manifest_path.write_text(manifest, encoding="utf-8")
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
