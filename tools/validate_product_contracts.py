#!/usr/bin/env python3
"""Validate T01 schemas, generated artifacts, semantic fixtures and Free isolation."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from princess_contracts import (  # noqa: E402
    METHOD_CAPABILITIES,
    compile_document,
    free_feature_ids,
    free_method_ids,
    parse_json,
    validate_premium_output,
    validate_projection,
)

FIXTURES = ROOT / "contracts" / "product" / "v1" / "fixtures"


def load(path: Path):
    return parse_json(path.read_text(encoding="utf-8"))


def validate_fixtures() -> tuple[int, int]:
    index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
    valid_docs = {}
    for case in index["valid"]:
        value = load(FIXTURES / case["path"])
        result = compile_document(case["schema"], value)
        if not result.ok:
            raise AssertionError(f"valid fixture {case['path']} failed: {result.issues}")
        valid_docs[case["schema"]] = result.value
    projection_issues = validate_projection(valid_docs["ReportDocument"], valid_docs["ReportViewModel"])
    if projection_issues:
        raise AssertionError(f"valid report projection failed: {projection_issues}")
    premium_issues = validate_premium_output(valid_docs["PremiumPacket"], valid_docs["PremiumOutput"])
    if premium_issues:
        raise AssertionError(f"valid Premium output failed: {premium_issues}")
    for case in index["invalid"]:
        value = load(FIXTURES / case["path"])
        result = compile_document(case["schema"], value)
        codes = {issue.code for issue in result.issues}
        if result.value is not None or case["expected_code"] not in codes:
            raise AssertionError(f"invalid fixture {case['path']} did not fail closed with {case['expected_code']}: {result.issues}")
    for case in index["raw_invalid"]:
        text = (FIXTURES / case["path"]).read_text(encoding="utf-8")
        try:
            parse_json(text)
        except ValueError as exc:
            if case["expected"] not in str(exc):
                raise AssertionError(f"raw invalid fixture {case['path']} failed for wrong reason: {exc}") from exc
        else:
            raise AssertionError(f"raw invalid fixture {case['path']} was accepted")
    return len(index["valid"]), len(index["invalid"]) + len(index["raw_invalid"])


def validate_free_runtime() -> tuple[int, int]:
    # The capability graph is authority; the legacy feature-database free flag is deliberately ignored.
    free_methods = set(free_method_ids())
    free_features = set(free_feature_ids())
    if len(free_features) != 64:
        raise AssertionError(f"expected current deterministic engine surface of 64 features, got {len(free_features)}")
    learned = {m["method_id"] for m in METHOD_CAPABILITIES["methods"] if m["requires_learned_inference"]}
    if "sigver_representation_v1" not in learned or learned & free_methods:
        raise AssertionError("learned method was not isolated from Free capability closure")

    # Fail any attempted socket construction while executing the Free engine.
    original_socket = socket.socket
    original_create = socket.create_connection

    def blocked(*args, **kwargs):
        raise AssertionError("Free runtime attempted network access")

    socket.socket = blocked
    socket.create_connection = blocked
    try:
        import numpy as np
        from princess_graphology import GraphologyEngine
        result = GraphologyEngine().analyze(np.full((80, 120), 255, np.uint8))
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create

    if set(result.measurements) != free_features:
        extra = sorted(set(result.measurements) - free_features)
        missing = sorted(free_features - set(result.measurements))
        raise AssertionError(f"engine/capability disagreement extra={extra} missing={missing}")
    for feature_id, measurement in result.measurements.items():
        if measurement.method_version not in free_methods:
            raise AssertionError(f"{feature_id}: engine emitted undeclared/non-Free method {measurement.method_version}")
    forbidden = ("torch", "openai", "anthropic", "transformers", "tensorflow")
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in forbidden)
    if imported:
        raise AssertionError(f"Free engine imported forbidden learned/provider runtime modules: {imported[:10]}")
    return len(free_methods), len(free_features)


def validate_contract_import_boundary() -> None:
    allowed_absolute = {"__future__", "ast", "dataclasses", "datetime", "hashlib", "json", "math", "re", "types", "typing"}
    root = ROOT / "src" / "princess_contracts"
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top not in allowed_absolute:
                        raise AssertionError(f"contracts runtime imports non-stdlib dependency {alias.name} in {path.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                top = (node.module or "").split(".", 1)[0]
                if top not in allowed_absolute:
                    raise AssertionError(f"contracts runtime imports non-stdlib dependency {node.module} in {path.name}")


def main() -> int:
    valid, invalid = validate_fixtures()
    methods, features = validate_free_runtime()
    validate_contract_import_boundary()
    print(f"PASS product contract fixtures: {valid} valid, {invalid} invalid")
    print(f"PASS Free capability closure: {methods} methods, {features} emitted features; provider egress denied")
    print("PASS princess_contracts import boundary: stdlib/generated runtime only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
