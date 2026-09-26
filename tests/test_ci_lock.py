"""Regression tests for the T00 CI lock and dependency policy."""

from types import SimpleNamespace

import pytest

import verify_ci_lock
import verify_project_dependency_policy


def fake_dist(name: str, version: str):
    return SimpleNamespace(metadata={"Name": name}, version=version)


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
    pyproject = tmp_path / "pyproject.toml"
    manifest = tmp_path / "manifest.txt"
    pyproject.write_text(
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg @ https://example.com/example_pkg-1.0-py3-none-any.whl"]

[project.optional-dependencies]
dev = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest.write_text("example-pkg==1.0\n", encoding="utf-8")

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("Direct URL dependency is prohibited" in error for error in errors)


def test_selected_dependency_missing_from_manifest_is_rejected(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    manifest = tmp_path / "manifest.txt"
    pyproject.write_text(
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg>=1"]

[project.optional-dependencies]
dev = ["pytest>=9"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest.write_text("example-pkg==1.2\n", encoding="utf-8")

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert errors == ["Dependency missing from reviewed manifest: pytest"]


def test_reviewed_version_must_satisfy_project_specifier(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    manifest = tmp_path / "manifest.txt"
    pyproject.write_text(
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["example-pkg>=2"]

[project.optional-dependencies]
dev = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest.write_text("example-pkg==1.9\n", encoding="utf-8")

    errors = verify_project_dependency_policy.validate(pyproject, manifest, ["dev"])
    assert any("does not satisfy" in error for error in errors)
