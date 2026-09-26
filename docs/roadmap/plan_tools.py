#!/usr/bin/env python3
"""Validate and navigate the coding-agent plan; no network or third-party dependencies."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
STATUSES = {"PLANNED", "IN_PROGRESS", "IMPLEMENTED_PENDING_REVIEW", "DONE", "BLOCKED"}
LIST_FIELDS = (
    "depends_on", "platforms", "connectors", "required_docs", "owned_paths",
    "coding_steps", "acceptance", "negative_tests", "artifacts",
    "production_gates", "validation_profiles", "rollback",
)
NONEMPTY = {
    "platforms", "required_docs", "owned_paths", "coding_steps", "acceptance",
    "negative_tests", "artifacts", "validation_profiles", "rollback",
}
PORTS = {
    "IdentityProvider", "ObjectStore", "PremiumModelProvider", "PaymentProvider",
    "NativePurchaseClient", "TransactionalMailer", "PushProvider",
    "AbuseChallengeProvider", "AnalyticsSink", "TelemetryExporter",
}
PORT_DOCS = {
    "IdentityProvider": "docs/connectors/identity.md",
    "ObjectStore": "docs/connectors/object-storage.md",
    "PremiumModelProvider": "docs/connectors/premium-model.md",
    "PaymentProvider": "docs/connectors/payments.md",
    "NativePurchaseClient": "docs/connectors/payments.md",
    "TransactionalMailer": "docs/connectors/email.md",
    "PushProvider": "docs/connectors/push.md",
    "AbuseChallengeProvider": "docs/connectors/abuse-challenge.md",
    "AnalyticsSink": "docs/connectors/analytics.md",
    "TelemetryExporter": "docs/connectors/telemetry.md",
}


def validate_plan(data: dict, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ["tasks must be a nonempty list"]
    profiles = data.get("validation_profiles", {})
    gates = data.get("gate_registry", {})
    if not isinstance(profiles, dict) or not isinstance(gates, dict):
        return ["validation_profiles and gate_registry must be objects"]
    by_id: dict[str, dict] = {}
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("task must be an object")
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"T\d{2}[A-Z]?", task_id):
            errors.append(f"invalid task ID: {task_id!r}")
            continue
        if task_id in by_id:
            errors.append(f"duplicate task ID: {task_id}")
        by_id[task_id] = task
        if task.get("status") not in STATUSES:
            errors.append(f"{task_id}: invalid status; READY must be computed")
        for field in ("title", "owner_role", "milestone", "contract_handoff"):
            if not isinstance(task.get(field), str) or not task[field].strip():
                errors.append(f"{task_id}: missing text field {field}")
        for field in LIST_FIELDS:
            values = task.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                errors.append(f"{task_id}: {field} must be a string list")
                continue
            if field in NONEMPTY and not values:
                errors.append(f"{task_id}: empty {field}")
            if len(values) != len(set(values)):
                errors.append(f"{task_id}: duplicate values in {field}")
        for gate in task.get("production_gates", []) if isinstance(task.get("production_gates"), list) else []:
            if isinstance(gate, str) and gate not in gates:
                errors.append(f"{task_id}: unknown gate {gate}")
        for profile in task.get("validation_profiles", []) if isinstance(task.get("validation_profiles"), list) else []:
            if isinstance(profile, str) and profile not in profiles:
                errors.append(f"{task_id}: unknown validation profile {profile}")
        for port in task.get("connectors", []) if isinstance(task.get("connectors"), list) else []:
            if isinstance(port, str) and port not in PORTS:
                errors.append(f"{task_id}: unknown connector {port}")
            elif isinstance(port, str):
                required = PORT_DOCS.get(port)
                docs = task.get("required_docs", [])
                if required and isinstance(docs, list) and required not in docs:
                    errors.append(f"{task_id}: connector {port} requires canonical spec {required}")
        if root is not None and isinstance(task.get("required_docs"), list):
            for rel in task["required_docs"]:
                if not isinstance(rel, str):
                    continue
                target = (root / rel).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    errors.append(f"{task_id}: missing/unsafe required document {rel}")
    for task_id, task in by_id.items():
        deps = task.get("depends_on", [])
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if not isinstance(dep, str) or dep not in by_id:
                errors.append(f"{task_id}: unknown predecessor {dep!r}")
        if task.get("status") == "DONE":
            unfinished = [
                dep for dep in deps
                if isinstance(dep, str) and dep in by_id and by_id[dep].get("status") != "DONE"
            ]
            if unfinished:
                errors.append(f"{task_id}: DONE with unfinished predecessors: {', '.join(unfinished)}")
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append("dependency cycle: " + " -> ".join([*visiting, task_id]))
            return
        if task_id in visited:
            return
        visiting.append(task_id)
        deps = by_id[task_id].get("depends_on", [])
        for dep in deps if isinstance(deps, list) else []:
            if isinstance(dep, str) and dep in by_id:
                visit(dep)
        visiting.pop()
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            errors.append(f"invalid profile {name}")
            continue
        state = profile.get("state")
        commands = profile.get("commands")
        if state not in {"EXISTS", "EXISTS_IN_THIS_PR", "TO_IMPLEMENT"}:
            errors.append(f"invalid profile state: {name}")
        if not isinstance(commands, list) or any(not isinstance(c, str) for c in commands):
            errors.append(f"invalid profile commands: {name}")
        elif state == "TO_IMPLEMENT" and commands:
            errors.append(f"{name}: planned suite must not pretend to provide an existing command")
    return errors


def ready_tasks(data: dict) -> list[dict]:
    tasks = data["tasks"]
    done = {task["id"] for task in tasks if task["status"] == "DONE"}
    return [task for task in tasks if task["status"] == "PLANNED" and set(task["depends_on"]) <= done]


def doc_link(path: str) -> str:
    rel = Path(os.path.relpath(path, "docs/roadmap")).as_posix()
    return f"[{path}]({rel})"


def render_task(task: dict, data: dict) -> str:
    task_id = task["id"]
    lines = [f'<a id="{task_id.lower()}"></a>', f"## {task_id} — {task['title']}", ""]
    lines += [f"**Status:** `{task['status']}` · **Owner:** {task['owner_role']} · **Milestone:** {task['milestone']}", ""]
    deps = ", ".join(f"[{dep}](#{dep.lower()})" for dep in task["depends_on"]) or "None"
    lines += [f"**Hard predecessors:** {deps}", f"**Platforms:** {', '.join(task['platforms'])}"]
    lines += [f"**Connector ports:** {', '.join(task['connectors']) or 'None'}", ""]
    if task.get("optional"):
        lines += ["Optional only when omitted from the explicitly approved marketed scope.", ""]
    lines += ["### Required reading", ""]
    lines += [f"- {doc_link(path)}" for path in task["required_docs"]]
    lines += ["", "### Owned implementation surfaces", "", "Planned targets unless present in the code tree:", "", "```text", *task["owned_paths"], "```", ""]
    lines += ["### Coding sequence", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(task["coding_steps"], 1)]
    lines += ["", "### Contract and integration handoff", "", task["contract_handoff"], ""]
    for field, title in (("acceptance", "Acceptance evidence"), ("negative_tests", "Required failure and regression cases"), ("artifacts", "Deliverables"), ("rollback", "Rollback and compatibility")):
        lines += [f"### {title}", ""]
        lines += [f"- {value}" for value in task[field]]
        lines.append("")
    lines += ["### Validation and human gates", ""]
    links = ", ".join(f"[{name}](#validation-{name})" for name in task["validation_profiles"])
    lines += [f"Validation profiles: {links}. Planned suites must be implemented and their actual command documented by the owning task; they are not passing tests today.", ""]
    if task["production_gates"]:
        for gate in task["production_gates"]:
            lines.append(f"- `{gate}`: {data['gate_registry'][gate]}")
        lines += ["", "No approval is created by this task brief. Mock/disabled implementation is not authorization for live collection, charges, signing or release.", ""]
    else:
        lines += ["No task-specific production gate; all repository privacy/security and scope boundaries still apply.", ""]
    if task.get("completion_evidence"):
        lines += ["Historical completion evidence: " + task["completion_evidence"], ""]
    lines += ["[Back to task table](#task-table) · [Documentation index](00-index.md) · [Execution sequence](20-end-to-end-build-sequence.md)", ""]
    return "\n".join(lines)


def render_backlog(data: dict) -> str:
    lines = ["# 06 — Detailed coding-agent backlog", "", "<!-- GENERATED by plan_tools.py from tasks.json; do not edit this file directly. -->", "", "[Documentation index](00-index.md) · [Machine authority](tasks.json) · [Build sequence](20-end-to-end-build-sequence.md) · [Release gates](21-release-readiness-checklists.md)", "", f"Plan {data['plan_version']}; code baseline `{data['baseline_commit']}`. Statuses are implementation/history records, not production approvals. READY is computed from completed hard predecessors.", "", "Use `python docs/roadmap/plan_tools.py --ready` or `--task ID`. Edit tasks.json and run `--write` then `--check` when maintaining the plan.", "", '<a id="task-table"></a>', "## Task table", "", "| Task | Status | Hard predecessors | Owner |", "|---|---|---|---|"]
    for task in data["tasks"]:
        deps = ", ".join(task["depends_on"]) or "—"
        lines.append(f"| [{task['id']} — {task['title']}](#{task['id'].lower()}) | {task['status']} | {deps} | {task['owner_role']} |")
    lines += ["", "## Validation profiles", "", "Run only commands that actually exist. TO_IMPLEMENT profiles name required future suites, not completed tests. The full current CI workflow remains authoritative for environment installation and all core gates.", ""]
    for name, profile in data["validation_profiles"].items():
        lines += [f'<a id="validation-{name}"></a>', f"### {name}", "", f"State: `{profile['state']}`. {profile['description']}", ""]
        if profile["commands"]:
            lines += ["```bash", *profile["commands"], "```", ""]
    for task in data["tasks"]:
        lines.append(render_task(task, data))
    return "\n".join(lines).rstrip() + "\n"


def without_fences(text: str) -> str:
    lines: list[str] = []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def anchors(text: str) -> set[str]:
    clean = without_fences(text)
    found = set(re.findall(r'<a\s+[^>]*?id=["\']([^"\']+)["\']', clean))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", clean, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        n = counts.get(slug, 0)
        found.add(slug if n == 0 else f"{slug}-{n}")
        counts[slug] = n + 1
    return found


def markdown_paths(root: Path, data: dict | None = None) -> list[Path]:
    paths = [root / name for name in ("README.md", "ROADMAP.md", "AGENTS.md")]
    for folder in ("docs/roadmap", "docs/adr", "docs/connectors", "docs/release"):
        paths.extend(sorted((root / folder).glob("*.md")))

    if data is not None:
        for task in data.get("tasks", []):
            for rel in task.get("required_docs", []):
                candidate = root / rel
                if candidate.suffix.lower() == ".md":
                    paths.append(candidate)

    result: list[Path] = []
    seen: set[Path] = set()
    resolved_root = root.resolve()
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file() or resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return result


def validate_links(root: Path, paths: list[Path]) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for path in paths:
        clean = without_fences(path.read_text(encoding="utf-8"))
        links = re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", clean)
        links += re.findall(r"^\[[^\]]+\]:\s*(\S+)", clean, re.MULTILINE)
        for link in links:
            value = link.strip("<>")
            parts = urlsplit(value)
            if parts.scheme or parts.netloc:
                continue
            raw = unquote(parts.path)
            target = ((root / raw.lstrip("/")) if raw.startswith("/") else (path.parent / raw)).resolve() if raw else path.resolve()
            label = path.relative_to(root).as_posix()
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f"{label}: broken/unsafe local link {link}")
                continue
            if parts.fragment and target.is_file() and target.suffix == ".md":
                fragment = unquote(parts.fragment)
                if fragment not in anchors(target.read_text(encoding="utf-8")):
                    errors.append(f"{label}: missing anchor {link}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--ready", action="store_true")
    mode.add_argument("--task")
    args = parser.parse_args(argv)
    source = ROOT / "docs/roadmap/tasks.json"
    target = ROOT / "docs/roadmap/06-agent-backlog.md"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        errors = validate_plan(data, ROOT)
        if errors:
            raise ValueError("\n".join(errors))
        rendered = render_backlog(data)
        if args.write:
            target.write_text(rendered, encoding="utf-8")
            print(f"Generated {target.relative_to(ROOT)} from {len(data['tasks'])} tasks")
            return 0
        if args.ready:
            for task in ready_tasks(data):
                gates = ", ".join(task["production_gates"]) or "none"
                print(f"{task['id']}: {task['title']} | owner={task['owner_role']} | human gates={gates}")
            print("Readiness permits scoped implementation, not unapproved production actions.")
            return 0
        if args.task:
            matches = [task for task in data["tasks"] if task["id"] == args.task]
            if not matches:
                raise ValueError(f"Unknown task: {args.task}")
            print(render_task(matches[0], data))
            return 0
        errors = validate_links(ROOT, markdown_paths(ROOT, data))
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            errors.append("Generated backlog is stale: run python docs/roadmap/plan_tools.py --write")
        if errors:
            raise ValueError("\n".join(errors))
        print(f"PASS: {len(data['tasks'])} task records, acyclic dependencies, required documents, generated backlog and local links")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
