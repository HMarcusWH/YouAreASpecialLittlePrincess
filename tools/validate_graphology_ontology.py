#!/usr/bin/env python3
"""Validate lossless ontology promotion on top of the immutable research baseline."""

from __future__ import annotations
from pathlib import Path
import json
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from graphology_db_common import load

from validate_graphology_integrity import validate as validate_integrity


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    errors = validate_integrity(repo)
    rs = load(repo / "research/graphology/foundations-v0.1/sources.json")
    rm = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")
    sources = load(root / "ontology/sources.json")
    schools = load(root / "ontology/schools.json")
    domains = load(root / "ontology/domains.json")
    concepts = load(root / "ontology/concepts.json")
    claims = load(root / "ontology/source_claims.json")
    if [{k: v for k, v in x.items() if k not in {"production_status", "runtime_role"}} for x in sources] != rs:
        errors.append("source promotion drift")
    if [{k: v for k, v in x.items() if k not in {"school_kind", "runtime_status"}} for x in schools] != rm["schools"]:
        errors.append("school promotion drift")
    if [{k: v for k, v in x.items() if k != "runtime_status"} for x in domains] != rm["domains"]:
        errors.append("domain promotion drift")
    if [{k: v for k, v in x.items() if k != "runtime_status"} for x in concepts] != rm["school_concepts"]:
        errors.append("concept promotion drift")
    if [{k: v for k, v in x.items() if k != "production_status"} for x in claims] != rm["source_assertions"]:
        errors.append("source-claim promotion drift")
    historical = [x for x in claims if x["claim_kind"] == "HISTORICAL_INTERPRETIVE_ASSOCIATION"]
    if any(
        x["runtime_role"] != "RESEARCH_ONLY_DO_NOT_EXECUTE" or x["production_status"] != "REGISTERED_RESEARCH_ONLY"
        for x in historical
    ):
        errors.append("historical source assertion became executable")
    manifest = load(root / "manifest.json")
    for key, actual in {
        "sources": len(sources),
        "schools": len(schools),
        "domains": len(domains),
        "concepts": len(concepts),
        "source_claims": len(claims),
    }.items():
        if manifest["counts"].get(key) != actual:
            errors.append(f"manifest count mismatch: {key}")
    return list(dict.fromkeys(errors))


def main():
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
