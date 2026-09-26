#!/usr/bin/env python3
"""Run named fault-injection controls in isolated pytest subprocesses.

The worker temporarily replaces one enforcement predicate in memory. Production
files are never edited. A fault is detected only by an assertion failure after
its mutated predicate was actually called; collection/import errors do not count.
This is a bounded set of defense-removal controls, not an overall mutation score.
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
    "duplicate_index": ("test_consent_invariants.py", "duplicate_canonical_keys"),
    "lineage_validation": ("test_consent_invariants.py", "a_matching_digest_never_replaces_semantic_validation"),
    "retention_chronology": ("test_consent_invariants.py", "retention_must_precede"),
    "notice_activation": ("test_consent_invariants.py", "even_rebound_activation"),
    "account_history": ("test_consent_invariants.py", "overlapping_links"),
    "capture_ancestors": ("test_consent_protocol.py", "repeat_chain_through_an_invalid_capture"),
    "publication_evidence": ("test_consent_invariants.py", "no_deletion_attestation"),
    "approval_binding": ("test_consent_invariants.py", "mutating_decision_metadata"),
    "mandatory_workflow": ("test_ci_workflow_contract.py", "optional_skipped_masked"),
}


def worker(name: str) -> int:
    import pytest

    import validate_consent_protocol as consent
    import verify_project_dependency_policy as dependency
    from consent_primitives import ValidationResult
    import render_ci_workflow as renderer

    calls = 0

    def counted(function):
        def replacement(*args, **kwargs):
            nonlocal calls
            calls += 1
            return function(*args, **kwargs)
        return replacement

    if name == "duplicate_index":
        consent.unique_index = counted(lambda rows, key, **kw: ValidationResult({key(row): row for row in rows}))
    elif name == "lineage_validation":
        consent.check_lineage = counted(lambda *a, **kw: [])
    elif name == "retention_chronology":
        consent.check_purpose_retention = counted(lambda *a, **kw: [])
    elif name == "notice_activation":
        consent.check_notices = counted(lambda *a, **kw: [])
    elif name == "account_history":
        consent.account_link_issues = counted(lambda *a, **kw: [])
    elif name == "capture_ancestors":
        consent.rooted_nodes = counted(lambda parents, excluded: set(parents) - excluded)
    elif name == "publication_evidence":
        consent.release_evidence_issues = counted(lambda *a, **kw: [])
    elif name == "approval_binding":
        consent.approval_recorded = counted(lambda *a, **kw: True)
        consent.approval_issues = counted(lambda *a, **kw: [])
    elif name == "mandatory_workflow":
        dependency.verified_targets = counted(lambda root, workflow=None: renderer.load_targets(root / "requirements/ci-targets.json"))
    file, selection = CASES[name]
    result = pytest.main([str(ROOT / "tests" / file), "-q", "-k", selection, "--tb=short", "-p", "no:cacheprovider"])
    print("FAULT_CALLS=" + str(calls))
    return int(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worker", choices=sorted(CASES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)
    results = []
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tools"), str(ROOT / "tests"), environment.get("PYTHONPATH", "")))
    for name in CASES:
        try:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", name],
                                 cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            call_line = next((line for line in run.stdout.splitlines() if line.startswith("FAULT_CALLS=")), "FAULT_CALLS=0")
            calls = int(call_line.partition("=")[2])
            detected = run.returncode == 1 and calls > 0 and " failed" in run.stdout and "ERROR " not in run.stdout
            detail = next((line for line in reversed(run.stdout.splitlines()) if " failed" in line), run.stdout[-500:])
        except subprocess.TimeoutExpired:
            detected, calls, detail = False, 0, "timeout (not counted as detection)"
        results.append({"fault": name, "detected": detected, "calls": calls, "pytest": detail})
        print(("PASS " if detected else "FAIL ") + name + f" (predicate calls={calls})")
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0 if all(item["detected"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
