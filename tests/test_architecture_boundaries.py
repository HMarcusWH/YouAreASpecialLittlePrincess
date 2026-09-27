"""Static import-direction rules from docs/roadmap/09-connectors-and-provider-boundaries.md.

Imports are read from the AST, so modules that are never executed by tests
are still checked, including function-local imports.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}
PROVIDER_SDKS = frozenset({
    "openai", "anthropic", "stripe", "boto3", "botocore", "google", "firebase_admin", "jwt", "httpx",
    "requests", "urllib3", "aiohttp", "sqlalchemy", "psycopg", "psycopg2", "alembic", "fastapi",
    "starlette", "pydantic", "uvicorn", "torch", "tensorflow", "transformers", "resend", "sentry_sdk",
    "opentelemetry", "playwright", "jose", "cryptography",
})
NUMERIC = frozenset({"numpy", "cv2", "scipy", "sklearn", "skimage"})


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                found.add(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                found.add(node.module)
    return found


def files(package: str) -> list[Path]:
    root = SRC.joinpath(*package.split("."))
    return sorted(root.rglob("*.py")) if root.exists() else []


def top(name: str) -> str:
    return name.split(".", 1)[0]


def violations(package: str, allowed) -> list[str]:
    bad = []
    for path in files(package):
        if within(module_name(path), LEARNED_EXTRA):
            continue
        for name in imports(path):
            if not allowed(name):
                bad.append(f"{module_name(path)} imports {name}")
    return bad


def within(name: str, *prefixes: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


# The learned signature representation is the one declared non-Free extra
# (``pip install .[signature]``); the method capability manifest excludes it
# from the Free closure. No other core module may import it.
LEARNED_EXTRA = "princess_graphology.signature"


def core_allowed(name: str) -> bool:
    return (top(name) in STDLIB | NUMERIC or within(name, "princess_graphology")) and not within(name, LEARNED_EXTRA)


RULES = {
    # The numerical core never imports the product layer, provider SDKs or the learned extra.
    "princess_graphology": core_allowed,
    # Generated contracts are pure: no I/O libraries, no engine, no application.
    "princess_contracts": lambda n: top(n) in STDLIB or within(n, "princess_contracts"),
    # Ports and domain: standard library, contracts and each other only.
    "princess_app.ports": lambda n: top(n) in STDLIB or within(n, "princess_contracts", "princess_app.ports"),
    "princess_app.domain": lambda n: top(n) in STDLIB or within(
        n, "princess_contracts", "princess_app.domain", "princess_app.ports"),
    # Use cases never reach into adapters or SDKs.
    "princess_app.application": lambda n: (top(n) in STDLIB or within(
        n, "princess_contracts", "princess_graphology", "princess_app.domain", "princess_app.ports",
        "princess_app.application")) and not within(n, LEARNED_EXTRA),
    # Fakes are standard-library only so local/test composition needs no network or secret.
    "princess_app.adapters.fakes": lambda n: top(n) in STDLIB or within(
        n, "princess_contracts", "princess_app.ports", "princess_app.adapters.fakes"),
}


@pytest.mark.parametrize("package", sorted(RULES))
def test_import_directions(package):
    assert files(package) or package in {"princess_app.domain"}, f"{package} has no modules"
    assert violations(package, RULES[package]) == []


def test_provider_sdks_only_appear_under_named_adapters():
    offenders = []
    for path in SRC.rglob("*.py"):
        name = module_name(path)
        if within(name, LEARNED_EXTRA):
            continue
        for imported in imports(path):
            if top(imported) in PROVIDER_SDKS and not (
                name.startswith("princess_app.adapters.") and not name.startswith("princess_app.adapters.fakes")
            ):
                offenders.append(f"{name} imports {imported}")
    assert offenders == []


def test_report_read_paths_never_reach_the_model_port():
    """Viewing, projecting and exporting a saved report never imports a model port."""
    for package in ("princess_app.domain.reports", "princess_app.application.reports"):
        paths = files(package) or [SRC.joinpath(*package.split(".")).with_suffix(".py")]
        for path in paths:
            assert not any(within(n, "princess_app.ports.model", "princess_app.adapters") for n in imports(path)), path


def test_learned_extra_is_isolated_and_imports_only_its_declared_runtime():
    learned = files(LEARNED_EXTRA)
    assert learned, "signature extra moved; update the Free isolation rule"
    for path in learned:
        assert {top(n) for n in imports(path)} <= STDLIB | NUMERIC | {"torch", "princess_graphology"}


def test_boundary_checker_detects_a_reversed_import(tmp_path, monkeypatch):
    pkg = tmp_path / "princess_app" / "domain"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "bad.py").write_text("from ..adapters.fakes import FakeClock\nimport sqlalchemy\n")
    monkeypatch.setattr(sys.modules[__name__], "SRC", tmp_path)
    found = violations("princess_app.domain", RULES["princess_app.domain"])
    assert sorted(found) == ["princess_app.domain.bad imports princess_app.adapters.fakes",
                             "princess_app.domain.bad imports sqlalchemy"]
