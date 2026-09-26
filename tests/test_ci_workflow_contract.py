"""Mandatory CI means exact executable jobs, not matrix-shaped metadata."""
import copy
import json
from pathlib import Path

import pytest

import render_ci_workflow as renderer
import verify_project_dependency_policy as policy
from test_ci_lock import write_reviewed_interpreters


@pytest.mark.parametrize("mutation", [
    lambda s: s.replace("    runs-on: ubuntu-24.04", "    continue-on-error: true\n    runs-on: ubuntu-24.04"),
    lambda s: s.replace("    runs-on: ubuntu-24.04", "    continue-on-error: ${{ matrix.experimental }}\n    runs-on: ubuntu-24.04"),
    lambda s: s.replace("    runs-on: ubuntu-24.04", "    if: false\n    runs-on: ubuntu-24.04"),
    lambda s: s.replace("      - run: python -m pytest -q", "      - run: python -m pytest -q\n        continue-on-error: true"),
    lambda s: s.replace("      - run: python -m pytest -q", "      - run: python -m pytest -q\n        if: false"),
    lambda s: s.replace("python -m pytest -q", "python -m pytest -q || true"),
    lambda s: s.replace("python -m pytest -q", "echo skipped tests"),
    lambda s: s.replace("python-version: ${{ matrix.python }}", "python-version: '3.12'"),
    lambda s: s.replace("${{ matrix.lock }}", "requirements/ci-py312.lock"),
    lambda s: s.replace("  pull_request:", "  pull_request:\n    paths: [never/**]"),
    lambda s: s.replace("      - run: python tools/validate_consent_protocol.py\n", ""),
    lambda s: s.replace("--require-hashes", "--no-cache-dir"),
    lambda s: s.replace("python tools/render_ci_workflow.py --check", "true"),
    lambda s: s.replace("    env:", "    concurrency:\n      group: ignored\n      cancel-in-progress: true\n    env:"),
])
def test_optional_skipped_masked_or_wrong_interpreter_jobs_never_count(tmp_path, mutation):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12))
    original = workflow.read_text()
    changed = mutation(original)
    assert changed != original  # mutation must reach the intended code
    workflow.write_text(changed)
    covered, errors = policy.interpreter_coverage(requirements, workflow)
    assert covered == set() and "canonical mandatory-job policy" in errors[0]


@pytest.mark.parametrize("change", [
    lambda d: d["targets"][0].update(experimental=True),
    lambda d: d["targets"][0].update(python=3.10),
    lambda d: d["targets"][0].update(python="3.10'\nrun: malicious"),
    lambda d: d["targets"][0].update(lock="requirements/ci-py311.lock"),
    lambda d: d["targets"][0].update(manifest="../../outside.txt"),
    lambda d: d["targets"][0].update(system="Windows"),
    lambda d: d["targets"][0].update(machine="aarch64"),
    lambda d: d["targets"].append(copy.deepcopy(d["targets"][0])),
    lambda d: d.update(version=True),
    lambda d: d.update(targets=[]),
])
def test_target_config_is_closed_typed_unique_and_injection_safe(tmp_path, change):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11, 12))
    path = requirements / "ci-targets.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    covered, errors = policy.interpreter_coverage(requirements, workflow)
    assert covered == set() and errors


def test_duplicate_json_keys_cannot_choose_a_target_configuration(tmp_path):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11))
    path = requirements / "ci-targets.json"
    path.write_text(path.read_text().replace('"version": 1', '"version": 1, "version": 1'))
    covered, errors = policy.interpreter_coverage(requirements, workflow)
    assert covered == set() and "duplicate target JSON key" in errors[0]


@pytest.mark.parametrize("which", ["workflow", "target_config", "lock"])
def test_symlinks_are_not_reviewed_workflow_or_lock_artifacts(tmp_path, which):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10,))
    path = {"workflow": workflow, "target_config": requirements / "ci-targets.json", "lock": requirements / "ci-py310.lock"}[which]
    outside = tmp_path / "outside"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    covered, errors = policy.interpreter_coverage(requirements, workflow)
    assert covered == set() and errors


def test_target_without_lock_never_counts_and_blocks_the_policy(tmp_path):
    requirements, workflow = write_reviewed_interpreters(tmp_path, (10, 11))
    (requirements / "ci-py311.lock").unlink()
    covered, errors = policy.interpreter_coverage(requirements, workflow)
    assert (3, 11) not in covered
    assert any("lacks its manifest/lock" in error for error in errors)


def test_range_is_compared_structurally_not_by_sampling_a_finite_grid():
    for raw in (">=3.10,<99", ">=3.10", ">=3.10,<3.9999999999999999", ">=3.10,<3.13,!=3.11.9000"):
        assert policy.requires_python_errors({"project": {"requires-python": raw}}, {(3, 10), (3, 11), (3, 12)})
    assert not policy.requires_python_errors({"project": {"requires-python": ">=3.10,<3.13"}}, {(3, 10), (3, 11), (3, 12)})


def test_reviewed_renderer_keeps_all_mandatory_steps_and_has_no_failure_masks():
    root = Path(__file__).resolve().parents[1]
    targets = renderer.verified_targets(root)
    text = renderer.render_workflow(targets)
    assert "  pull_request:\n" in text
    assert "continue-on-error" not in text and "\n    if:" not in text and "|| true" not in text
    for command in (
        "python tools/render_ci_workflow.py --check", "python tools/verify_project_dependency_policy.py",
        "--backend-requirements", "python tools/verify_ci_lock.py", "python tools/validate_consent_protocol.py",
        "python -m pytest -q", "ruff check src tests tools", "python tools/check_graphology_research.py",
        "python tools/test_graphology_research.py", "python -m pip wheel . --no-deps --no-build-isolation --no-index",
    ):
        assert command in text
    assert "python-version: ${{ matrix.python }}" in text and '"${{ matrix.lock }}"' in text
