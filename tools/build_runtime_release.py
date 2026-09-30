#!/usr/bin/env python3
"""Generate runtime-release/1 from one exact source checkout using stdlib only."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA40 = re.compile(r"^[0-9a-f]{40}$")
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def python_constants(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            items = [evaluate(item) for item in node.elts]
            return set(items) if isinstance(node, ast.Set) else items
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset"
            and len(node.args) == 1
            and not node.keywords
        ):
            return frozenset(evaluate(node.args[0]))
        raise ValueError("unsupported constant expression")

    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = evaluate(statement.value)
        except ValueError:
            continue
    return values


def migration_head(root: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted((root / "migrations" / "versions").glob("*.py")):
        constants = python_constants(path)
        revision = constants.get("revision")
        parent = constants.get("down_revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError(f"{path}: missing literal revision")
        revisions.add(revision)
        if isinstance(parent, str):
            parents.add(parent)
        elif isinstance(parent, (tuple, list, set, frozenset)):
            parents.update(item for item in parent if isinstance(item, str))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise ValueError(f"expected one Alembic head, found {heads}")
    return heads[0]


def public_routes(root: Path, policy: dict[str, Any]) -> list[str]:
    path = root / "apps" / "api" / "princess_api" / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    exclusions = tuple(policy["api_route_exclusion_prefixes"])
    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            method = decorator.func.attr.lower()
            if not isinstance(owner, ast.Name) or owner.id != "app" or method not in METHODS or not decorator.args:
                continue
            raw_path = decorator.args[0]
            if not isinstance(raw_path, ast.Constant) or not isinstance(raw_path.value, str):
                continue
            route = raw_path.value
            if not route.startswith("/v1/"):
                continue
            if any(route.startswith(prefix) for prefix in exclusions):
                continue
            routes.add(f"{method.upper()} {route}")
    return sorted(routes)


def project_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    if not project:
        raise ValueError("pyproject.toml: missing [project]")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', project.group(1))
    if not match:
        raise ValueError("pyproject.toml: missing project version")
    return match.group(1)


def render_template_version(root: Path) -> str:
    text = (root / "apps" / "render" / "src" / "render.tsx").read_text(encoding="utf-8")
    match = re.search(r'export const TEMPLATE_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError("apps/render/src/render.tsx: TEMPLATE_VERSION not found")
    return match.group(1)


def build_manifest(root: Path, source_sha: str, policy: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    if not SHA40.fullmatch(source_sha):
        raise ValueError("source SHA must be 40 lowercase hex characters")
    product = load_json(root / "contracts" / "product" / "v1" / "manifest.json")
    authorities = product["authorities"]
    reports = python_constants(root / "src" / "princess_app" / "domain" / "reports" / "template.py")
    write_template = reports.get("TEMPLATE_VERSION")
    read_templates = reports.get("SUPPORTED_TEMPLATE_VERSIONS")
    presentation = reports.get("HIGHLIGHT_PRESENTATION_VERSION")
    highlight_policy = reports.get("HIGHLIGHT_POLICY_VERSION")
    if not isinstance(write_template, str) or not isinstance(read_templates, (set, frozenset)):
        raise ValueError("report template write/read authorities are not resolvable")
    if not isinstance(presentation, str) or not isinstance(highlight_policy, str):
        raise ValueError("report presentation authorities are not resolvable")
    feature = authorities["feature_database"]
    methods = authorities["method_capabilities"]
    interpretation = authorities["premium_interpretation_database"]
    return {
        "version": "runtime-release/1",
        "source_sha": source_sha,
        "database": {"head_revision": migration_head(root)},
        "product_contract": {"version": product["contract_version"], "bundle_sha256": product["bundle_sha256"]},
        "engine": {"version": project_version(root)},
        "measurement": {
            "feature_schema_version": feature["version"],
            "feature_source_sha256": feature["sha256"],
            "method_manifest_sha256": methods["resolved_sha256"],
        },
        "interpretation": {"version": interpretation["version"], "sha256": interpretation["sha256"]},
        "reports": {
            "write_template": write_template,
            "read_templates": sorted(read_templates),
            "presentation": presentation,
            "highlight_policy": highlight_policy,
            "render_template": render_template_version(root),
        },
        "api": {"public_v1_routes": public_routes(root, policy)},
        "runtime": {
            "platform": "linux/amd64",
            "python_lock_sha256": sha256_file(root / "infra" / "runtime" / "python-py312.lock"),
            "dockerfile_sha256": sha256_file(root / "infra" / "runtime" / "Dockerfile"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    policy_path = args.policy or args.root / "infra" / "release" / "release-policy.json"
    manifest = build_manifest(args.root, args.source_sha, load_json(policy_path))
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
