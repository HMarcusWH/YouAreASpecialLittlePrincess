"""Regression tests for safe GitHub Actions workflow-level concurrency.

Local tests verify policy shape and event isolation. Live GitHub Actions
scheduling, path filtering and run-order behavior require separate inspection.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
AUTOMATIC = (
    "ci.yml",
    "app.yml",
    "native.yml",
    "runtime.yml",
    "release-compat.yml",
    "documentation.yml",
    "roadmap.yml",
)
GROUP_EXPRESSION = "${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}"
CANCEL_EXPRESSION = "${{ github.event_name == 'pull_request' }}"
POLICY = (
    "concurrency:\n"
    f"  group: {GROUP_EXPRESSION}\n"
    f"  cancel-in-progress: {CANCEL_EXPRESSION}\n"
)


def require_workflow_policy(source: str) -> None:
    """Reject duplicates, job-level placement, and any policy deviation."""
    declarations = list(re.finditer(r"(?m)^([ \t]*)concurrency[ \t]*:", source))
    assert len(declarations) == 1, "expected exactly one concurrency declaration"
    assert declarations[0].group(1) == "", "concurrency must be workflow-root"
    assert source.count(POLICY) == 1, "incorrect concurrency group or cancellation rule"
    assert "\npermissions:\n" in source and "\njobs:\n" in source
    assert (
        source.index("\npermissions:\n")
        < declarations[0].start()
        < source.index("\njobs:\n")
    )

    lines = source.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("concurrency:"))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", lines[i])
        ),
        len(lines),
    )
    assert "".join(lines[start:end]).rstrip("\n") + "\n" == POLICY


@pytest.mark.parametrize("filename", AUTOMATIC)
def test_all_automatic_workflows_have_exact_root_policy(filename: str) -> None:
    source = (WORKFLOWS / filename).read_text(encoding="utf-8")
    require_workflow_policy(source)
    assert re.search(r"(?m)^on:\n", source)
    assert re.search(r"(?m)^  pull_request:[ \t]*$", source)
    assert re.search(r"(?m)^  push:[ \t]*$", source)


def test_workflow_names_are_unique_case_insensitively() -> None:
    # GitHub compares concurrency group names without case sensitivity.
    names = []
    for filename in AUTOMATIC:
        source = (WORKFLOWS / filename).read_text(encoding="utf-8")
        matches = re.findall(r"(?m)^name:[ \t]*(.+)[ \t]*$", source)
        assert len(matches) == 1 and matches[0].strip(), filename
        names.append(matches[0].strip().casefold())
    assert len(names) == len(set(names)), "two workflows could cancel each other"


def group_identity(
    workflow: str, event_name: str, run_id: int, pr_number: int | None = None
) -> str:
    """Reference evaluation of the approved expression, not a GitHub simulator."""
    return f"{workflow}-{event_name}-{pr_number or run_id}".casefold()


def cancel_enabled(event_name: str) -> bool:
    return event_name == "pull_request"


def test_same_pr_same_workflow_supersedes_older_commits() -> None:
    assert group_identity("CI", "pull_request", 101, 100) == group_identity(
        "CI", "pull_request", 102, 100
    )
    assert cancel_enabled("pull_request")


def test_different_pr_numbers_are_isolated() -> None:
    assert group_identity("CI", "pull_request", 101, 100) != group_identity(
        "CI", "pull_request", 102, 101
    )


def test_different_workflows_are_isolated() -> None:
    assert group_identity("CI", "pull_request", 101, 100) != group_identity(
        "Native foundation", "pull_request", 101, 100
    )


def test_prs_and_pushes_are_isolated() -> None:
    assert group_identity("CI", "pull_request", 101, 100) != group_identity(
        "CI", "push", 101
    )


def test_distinct_main_pushes_preserve_independent_pending_runs() -> None:
    assert group_identity("CI", "push", 201) != group_identity("CI", "push", 202)
    assert not cancel_enabled("push")
    # cancel-in-progress: false alone would not protect shared pending groups.


def test_distinct_manual_dispatches_have_independent_groups() -> None:
    assert group_identity("manual", "workflow_dispatch", 301) != group_identity(
        "manual", "workflow_dispatch", 302
    )
    assert not cancel_enabled("workflow_dispatch")


def test_railway_apk_remains_manual_only_and_uncancelled() -> None:
    source = (WORKFLOWS / "railway-guest-apk.yml").read_text(encoding="utf-8")
    triggers = source.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert triggers.strip() == "workflow_dispatch:"
    assert not re.search(r"(?m)^[ \t]*concurrency[ \t]*:", source)
    for preserved in ("REVIEWED_RAILWAY_BACKEND_SHA", "GITHUB_SHA", "/health/build"):
        assert preserved in source


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.replace(POLICY, "", 1),
        lambda s: s.replace("concurrency:\n", "  concurrency:\n", 1),
        lambda s: s.replace("github.event.pull_request.number", "github.sha", 1),
        lambda s: s.replace("github.run_id", "github.ref", 1),
        lambda s: s.replace("github.workflow", "global", 1),
        lambda s: s.replace(
            f"  cancel-in-progress: {CANCEL_EXPRESSION}",
            "  cancel-in-progress: true",
            1,
        ),
        lambda s: s.replace(POLICY, POLICY + POLICY, 1),
        lambda s: s.replace(POLICY, "", 1).replace(
            "  test:\n", "  test:\n    concurrency:\n      group: orphan\n", 1
        ),
        lambda s: s.replace(
            f"  cancel-in-progress: {CANCEL_EXPRESSION}\n",
            f"  cancel-in-progress: {CANCEL_EXPRESSION}\n  queue: max\n",
            1,
        ),
    ],
)
def test_mutated_policy_is_rejected(mutation) -> None:
    original = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    changed = mutation(original)
    assert changed != original, "test mutation must actually change the workflow"
    with pytest.raises(AssertionError):
        require_workflow_policy(changed)


def test_canonical_ci_generator_and_output_agree() -> None:
    import render_ci_workflow as renderer

    targets = renderer.verified_targets(ROOT)
    generated = renderer.render_workflow(targets)
    assert generated == (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    require_workflow_policy(generated)
