#!/usr/bin/env python3
"""Check runtime-release/1 compatibility and emit rollout-qualification/1."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

STATUS = ("PASS", "FAIL", "NOT_RUN")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class CompatibilityError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompatibilityError(f"{path}: expected JSON object")
    return value


def canonical_sha256(value: dict[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def major(version: str) -> str:
    return version.split(".", 1)[0]


def compare_manifests(base: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, bool]:
    checks = {
        "product_contract_major_compatible": False,
        "route_surface_backward_compatible": False,
        "report_read_forward_compatible": False,
        "report_write_rollback_compatible": False,
        "runtime_platform_compatible": False,
    }
    if policy.get("database_downgrade_on_application_rollback") is not False:
        raise CompatibilityError("release policy must forbid database downgrade during application rollback")
    if policy.get("queue_state_requirement") != "DRAINED_OR_FENCED":
        raise CompatibilityError("release policy must require DRAINED_OR_FENCED queues")
    base_contract = str(base["product_contract"]["version"])
    candidate_contract = str(candidate["product_contract"]["version"])
    if major(base_contract) != major(candidate_contract):
        raise CompatibilityError(f"product contract major changed: base={base_contract} candidate={candidate_contract}")
    checks["product_contract_major_compatible"] = True
    missing_routes = sorted(set(base["api"]["public_v1_routes"]) - set(candidate["api"]["public_v1_routes"]))
    if missing_routes:
        raise CompatibilityError("candidate removed public method+route operations: " + ", ".join(missing_routes))
    checks["route_surface_backward_compatible"] = True
    base_write = base["reports"]["write_template"]
    if base_write not in set(candidate["reports"]["read_templates"]):
        raise CompatibilityError(f"candidate cannot read base report template {base_write}")
    checks["report_read_forward_compatible"] = True
    candidate_write = candidate["reports"]["write_template"]
    if candidate_write not in set(base["reports"]["read_templates"]):
        raise CompatibilityError(f"rollback base cannot read candidate report template {candidate_write}")
    checks["report_write_rollback_compatible"] = True
    if base["runtime"]["platform"] != candidate["runtime"]["platform"]:
        raise CompatibilityError(
            f"runtime platform changed: base={base['runtime']['platform']} candidate={candidate['runtime']['platform']}"
        )
    checks["runtime_platform_compatible"] = True
    return checks


def receipt(
    base: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any], *,
    event_kind: str, candidate_head_sha: str | None,
    candidate_on_candidate_db: str = "NOT_RUN", rollback_base_on_candidate_db: str = "NOT_RUN",
    base_write_candidate_read: str = "NOT_RUN", candidate_write_base_read: str = "NOT_RUN",
    historical_expand_witness: str = "NOT_RUN",
) -> dict[str, Any]:
    checks = compare_manifests(base, candidate, policy)
    dynamic = [candidate_on_candidate_db, rollback_base_on_candidate_db, base_write_candidate_read,
               candidate_write_base_read, historical_expand_witness]
    if any(value not in STATUS for value in dynamic):
        raise CompatibilityError(f"invalid dynamic status: {dynamic}")
    result = "FAIL" if any(value == "FAIL" for value in dynamic) else (
        "PASS" if all(value == "PASS" for value in dynamic) else "STATIC_PASS"
    )
    if event_kind not in {"PREMERGE", "PUSH"}:
        raise CompatibilityError(f"invalid event kind: {event_kind}")
    if candidate_head_sha is not None and not SHA40.fullmatch(candidate_head_sha):
        raise CompatibilityError("candidate head SHA must be 40 lowercase hex characters")
    return {
        "version":"rollout-qualification/1","event_kind":event_kind,
        "candidate_sha":candidate["source_sha"],"candidate_head_sha":candidate_head_sha,
        "rollback_base_sha":base["source_sha"],
        "candidate_manifest_sha256":canonical_sha256(candidate),
        "rollback_base_manifest_sha256":canonical_sha256(base),
        "database_revision":candidate["database"]["head_revision"],"checks":checks,
        "candidate_on_candidate_db":candidate_on_candidate_db,
        "rollback_base_on_candidate_db":rollback_base_on_candidate_db,
        "base_write_candidate_read":base_write_candidate_read,
        "candidate_write_base_read":candidate_write_base_read,
        "historical_expand_witness":historical_expand_witness,
        "database_downgrade_performed":False,
        "queue_state_requirement":policy["queue_state_requirement"],
        "scope":["API","FREE_ANALYSIS_WORKER","REPORT_PERSISTENCE_READ"],"result":result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--event-kind", choices=("PREMERGE","PUSH"), required=True)
    parser.add_argument("--candidate-head-sha")
    parser.add_argument("--candidate-on-candidate-db", choices=STATUS, default="NOT_RUN")
    parser.add_argument("--rollback-base-on-candidate-db", choices=STATUS, default="NOT_RUN")
    parser.add_argument("--base-write-candidate-read", choices=STATUS, default="NOT_RUN")
    parser.add_argument("--candidate-write-base-read", choices=STATUS, default="NOT_RUN")
    parser.add_argument("--historical-expand-witness", choices=STATUS, default="NOT_RUN")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        document = receipt(
            load_json(args.base), load_json(args.candidate), load_json(args.policy),
            event_kind=args.event_kind, candidate_head_sha=args.candidate_head_sha,
            candidate_on_candidate_db=args.candidate_on_candidate_db,
            rollback_base_on_candidate_db=args.rollback_base_on_candidate_db,
            base_write_candidate_read=args.base_write_candidate_read,
            candidate_write_base_read=args.candidate_write_base_read,
            historical_expand_witness=args.historical_expand_witness,
        )
    except (KeyError, TypeError, CompatibilityError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if document["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
