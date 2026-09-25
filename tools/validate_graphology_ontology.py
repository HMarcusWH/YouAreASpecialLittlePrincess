#!/usr/bin/env python3
"""Validate T26 PR1 graphology ontology/provenance foundation."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def load(path: Path):
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"Duplicate JSON key in {path}: {key}")
            out[key] = value
        return out
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON constant in {path}: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    manifest = load(root / "manifest.json")
    sources = load(root / "ontology/sources.json")
    schools = load(root / "ontology/schools.json")
    domains = load(root / "ontology/domains.json")
    claims = load(root / "ontology/source_claims.json")
    concepts = load(root / "ontology/concepts.json")
    relations_doc = load(root / "ontology/concept_relationships.json")
    trace = load(root / "traceability/research_to_production.json")
    gaps = load(root / "traceability/source_gaps.json")
    scaffold = load(repo / "schema/premium_interpretation_database_v1.json")
    research_sources = load(repo / "research/graphology/foundations-v0.1/sources.json")
    research_meta = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")

    errors = []
    def unique(values, label):
        values = list(values)
        if len(values) != len(set(values)):
            errors.append(f"duplicate {label}")

    unique((x["source_id"] for x in sources), "source_id")
    unique((x["school_id"] for x in schools), "school_id")
    unique((x["domain_id"] for x in domains), "domain_id")
    unique((x["assertion_id"] for x in claims), "assertion_id")
    unique((x["concept_id"] for x in concepts), "concept_id")

    source_ids = {x["source_id"] for x in sources}
    school_ids = {x["school_id"] for x in schools}
    domain_ids = {x["domain_id"] for x in domains}
    concept_ids = {x["concept_id"] for x in concepts}

    if any(set(x["source_ids"]) - source_ids for x in schools):
        errors.append("school source reference does not resolve")
    if any(set(x["source_ids"]) - source_ids for x in domains):
        errors.append("domain source reference does not resolve")
    if any(x["school_id"] is not None and x["school_id"] not in school_ids for x in concepts):
        errors.append("concept school reference does not resolve")
    if any({r["source_id"] for r in x["source_refs"]} - source_ids for x in concepts):
        errors.append("concept source reference does not resolve")
    if any(x["source_id"] not in source_ids for x in claims):
        errors.append("source claim reference does not resolve")

    # Production ontology must be a faithful promotion of the frozen research fields in PR1.
    stripped_sources = [
        {k: v for k, v in x.items() if k not in {"production_status", "runtime_role"}}
        for x in sources
    ]
    if stripped_sources != research_sources:
        errors.append("production source registry drifted from frozen research")
    stripped_schools = [
        {k: v for k, v in x.items() if k not in {"school_kind", "runtime_status"}}
        for x in schools
    ]
    if stripped_schools != research_meta["schools"]:
        errors.append("production school registry drifted from frozen research")
    stripped_domains = [
        {k: v for k, v in x.items() if k != "runtime_status"}
        for x in domains
    ]
    if stripped_domains != research_meta["domains"]:
        errors.append("production domain registry drifted from frozen research")
    stripped_concepts = [
        {k: v for k, v in x.items() if k != "runtime_status"}
        for x in concepts
    ]
    if stripped_concepts != research_meta["school_concepts"]:
        errors.append("production concept registry drifted from frozen research")
    stripped_claims = [
        {k: v for k, v in x.items() if k != "production_status"}
        for x in claims
    ]
    if stripped_claims != research_meta["source_assertions"]:
        errors.append("production source claims drifted from frozen research")

    rels = relations_doc["relationships"]
    if any(x["relationship_type"] not in relations_doc["allowed_relationship_types"] for x in rels):
        errors.append("unknown concept relationship type")
    if any(x["left_concept_id"] not in concept_ids or x["right_concept_id"] not in concept_ids for x in rels):
        errors.append("concept relationship endpoint does not resolve")
    if any({r["source_id"] for r in x["source_refs"]} - source_ids for x in rels):
        errors.append("concept relationship source does not resolve")

    expected = {
        ("SOURCE", x["source_id"]) for x in research_sources
    } | {
        ("SCHOOL", x["school_id"]) for x in research_meta["schools"]
    } | {
        ("DOMAIN", x["domain_id"]) for x in research_meta["domains"]
    } | {
        ("CONCEPT", x["concept_id"]) for x in research_meta["school_concepts"]
    } | {
        ("SOURCE_ASSERTION", x["assertion_id"]) for x in research_meta["source_assertions"]
    } | {
        ("UNRESOLVED_SOURCE_TERM", x["term"]) for x in research_meta["unresolved_source_terms"]
    }
    actual = {(x["research_kind"], x["research_id"]) for x in trace["records"]}
    if actual != expected:
        errors.append("research-to-production traceability coverage differs from foundation records")

    historical = [x for x in claims if x["claim_kind"] == "HISTORICAL_INTERPRETIVE_ASSOCIATION"]
    if any(x["runtime_role"] != "RESEARCH_ONLY_DO_NOT_EXECUTE" or x["production_status"] != "REGISTERED_RESEARCH_ONLY" for x in historical):
        errors.append("historical interpretive association became executable")
    if any(x["runtime_status"] != "ONTOLOGY_ONLY" for x in concepts):
        errors.append("concept activated beyond ontology scope")

    concept_gap_ids = {x["object_id"] for x in gaps["gaps"] if x["object_kind"] == "CONCEPT" and x["blocks_runtime_activation"]}
    if concept_gap_ids != concept_ids:
        errors.append("not every concept has an explicit runtime-blocking gap in PR1")
    if not any(x["object_kind"] == "UNRESOLVED_SOURCE_TERM" and x["object_id"] == "currency" and x["blocks_runtime_activation"] for x in gaps["gaps"]):
        errors.append("unresolved currency term is not blocked")

    expected_counts = {
        "sources": len(sources),
        "schools": len(schools),
        "historical_tradition_profiles": sum(x["school_kind"] == "GRAPHOLOGY_TRADITION_PROFILE" for x in schools),
        "application_namespaces": sum(x["school_kind"] == "APPLICATION_NAMESPACE" for x in schools),
        "domains": len(domains),
        "concepts": len(concepts),
        "source_claims": len(claims),
        "concept_relationships": len(rels),
        "unresolved_source_terms": 1,
    }
    for key, value in expected_counts.items():
        if manifest["counts"].get(key) != value:
            errors.append(f"manifest foundation count differs for {key}")
    allowed_scopes = {
        "ONTOLOGY_AND_PROVENANCE_ONLY",
        "ONTOLOGY_PROVENANCE_OBSERVATIONS_SELECTORS_VALUES",
    }
    if manifest["runtime_activation"] is not False or manifest["production_scope"] not in allowed_scopes:
        errors.append("manifest scope/runtime activation invalid")
    if scaffold.get("status") != "UNPOPULATED":
        errors.append("compiled Premium scaffold must remain UNPOPULATED in PR1")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "scope": "T26_PR1_ONTOLOGY_PROVENANCE"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
