#!/usr/bin/env python3
"""Exercise T01 invariants by removing one enforcement predicate at a time.

A control counts only when the weakened predicate is actually called and a
pytest assertion fails. Import/collection errors and unexercised mutations are
not accepted as evidence. Production files are never modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "feature_value_type": ("test_product_contracts.py", "bool_is_not_a_number"),
    "fact_quality": ("test_product_contracts.py", "product_fact_quality_preserves"),
    "analysis_authority": ("test_product_contracts.py", "METHOD_MANIFEST_DRIFT"),
    "evidence_graph": ("test_product_contracts.py", "evidence_coordinate_graph"),
    "report_authority": ("test_product_contracts.py", "reference_claims_bind"),
    "view_authority": ("test_product_contracts.py", "view_model_identity_sets"),
    "self_digest": ("test_product_contracts.py", "self_digest_binds"),
    "premium_packet_authority": ("test_product_contracts.py", "premium_packet_is_frozen"),
    "premium_output_boundary": ("test_product_contracts.py", "premium_output_is_complete"),
    "grant_authority": ("test_product_contracts.py", "grant_snapshots_reference"),
    "projection_identity": ("test_product_contracts.py", "projection_is_exact_subset"),
    "schema_source_policy": ("test_product_contract_codegen.py", "schema_source_subset"),
    "capability_closure": ("test_product_contract_codegen.py", "method_capability_resolver"),
}


def worker(name: str) -> int:
    import pytest
    import princess_contracts.runtime as runtime
    import product_contract_common as common

    calls = 0

    def counted(function):
        def replacement(*args, **kwargs):
            nonlocal calls
            calls += 1
            return function(*args, **kwargs)
        return replacement

    if name == "feature_value_type":
        runtime._feature_value_ok = counted(lambda data_type, value: True)
    elif name == "fact_quality":
        runtime._fact_semantics = counted(lambda fact, issues, path: runtime._feature_method_semantics(fact, issues, path))
    elif name == "analysis_authority":
        runtime._analysis_semantics = counted(lambda data, issues, path="": None)
    elif name == "evidence_graph":
        runtime._evidence_semantics = counted(lambda data, issues: None)
    elif name == "report_authority":
        runtime._report_semantics = counted(lambda data, issues: None)
    elif name == "view_authority":
        runtime._view_semantics = counted(lambda data, issues: None)
    elif name == "self_digest":
        runtime._self_digest_semantics = counted(lambda data, field, issues, path="": None)
    elif name == "premium_packet_authority":
        runtime._packet_semantics = counted(lambda data, issues: None)
    elif name == "premium_output_boundary":
        import princess_contracts
        weakened = counted(lambda packet, output: ())
        runtime.validate_premium_output = weakened
        princess_contracts.validate_premium_output = weakened
    elif name == "grant_authority":
        runtime._grant_semantics = counted(lambda data, issues: None)
    elif name == "projection_identity":
        runtime._same_json = counted(lambda a, b: True)
    elif name == "schema_source_policy":
        common._validate_schema_bundle = counted(lambda schemas: None)
    elif name == "capability_closure":
        original = common.resolve_method_capabilities
        def weakened(features):
            resolved = original(features)
            for method in resolved["methods"]:
                if method["method_id"] == "sigver_representation_v1":
                    method["free_eligible"] = True
                    resolved["features"]["SIG_EMBEDDING"]["free_available"] = True
            return resolved
        common.resolve_method_capabilities = counted(weakened)

    file, selection = CASES[name]
    result = pytest.main([
        str(ROOT / "tests" / file), "-q", "-k", selection,
        "--tb=short", "-p", "no:cacheprovider",
    ])
    print("FAULT_CALLS=" + str(calls))
    return int(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worker", choices=sorted(CASES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((
        str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests"),
        environment.get("PYTHONPATH", ""),
    ))
    results = []
    for name in CASES:
        try:
            run = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", name],
                cwd=ROOT, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90,
            )
            line = next((x for x in run.stdout.splitlines() if x.startswith("FAULT_CALLS=")), "FAULT_CALLS=0")
            calls = int(line.partition("=")[2])
            detected = run.returncode == 1 and calls > 0 and " failed" in run.stdout and "ERROR " not in run.stdout
            detail = next((x for x in reversed(run.stdout.splitlines()) if " failed" in x), run.stdout[-500:])
        except subprocess.TimeoutExpired:
            detected, calls, detail = False, 0, "timeout (not counted as detection)"
        results.append({"fault": name, "detected": detected, "calls": calls, "pytest": detail})
        print(("PASS " if detected else "FAIL ") + name + f" (predicate calls={calls})")
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0 if all(item["detected"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
