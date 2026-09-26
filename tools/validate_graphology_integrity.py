#!/usr/bin/env python3
"""Validate graphology database provenance, lifecycle, source gaps and complete foundation traceability."""

from __future__ import annotations
from pathlib import Path
import json
import sys

from graphology_db_common import load, verify_research_baseline

EXPECTED_PENDING_STAGE = {
    "manifest_status": "POPULATED_PENDING_REVIEW",
    "production_scope": "COMPLETE_DATABASE_PENDING_REVIEW",
    "t26_status": "IMPLEMENTED_PENDING_REVIEW",
    "compiled_runtime_artifact_status": "POPULATED_PENDING_REVIEW",
    "runtime_activation": False,
    "artifact_status": "POPULATED_PENDING_REVIEW",
    "artifact_runtime_activation": False,
    "required_exclusions": [
        "Runtime OpenAI adapter and dynamic Structured Output request compilation (T15)",
        "Candidate generator implementations owned by later engine/reference/comparison tasks",
        "Runtime activation of traditional associations or school rule packs",
        "Resolution of source/morphology gaps explicitly recorded as blocked",
        "Non-English translations beyond stable localization keys and English canonical copy",
        "Live model evaluation, pricing, payment and deployment",
    ],
}

EXPECTED_REVIEWED_STAGE = {
    "manifest_status": "REVIEWED_READY_FOR_T15",
    "production_scope": "COMPLETE_DATABASE_REVIEWED",
    "t26_status": "DONE",
    "compiled_runtime_artifact_status": "REVIEWED_READY_FOR_T15",
    "runtime_activation": False,
    "artifact_status": "REVIEWED_READY_FOR_T15",
    "artifact_runtime_activation": False,
    "required_exclusions": EXPECTED_PENDING_STAGE["required_exclusions"],
}
EXPECTED_LINEAGE = {
    "research_import_merge": "f96aa6b54cfaf91f0a8243e7c7e266baa053eedc",
    "ontology_foundation_merge": "ee2a92c7388bcf5b9aec225a093aef315e300987",
    "selector_foundation_merge": "8d6003c24473a6cefb2ac13211c778701748d0d3",
    "traditional_structure_merge": "48897ff35949710d870d0b16096ada5d63c3626d",
    "database_completion_merge": "c6561b0e7748545751d0107c284810de788c03d5",
}


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    errors = list(verify_research_baseline(repo))
    manifest = load(root / "manifest.json")
    stage_doc = load(root / "stage_contract.json")
    if stage_doc.get("version") != "graphology-database-stage-contract/1":
        errors.append("stage contract version drift")
    if stage_doc.get("current_stage") != "REVIEWED_READY_FOR_T15":
        errors.append("stage contract current stage must remain reviewed ready for T15")
    if stage_doc.get("stages", {}).get("POPULATED_PENDING_REVIEW") != EXPECTED_PENDING_STAGE:
        errors.append("pending-review stage contract drift")
    if stage_doc.get("stages", {}).get("REVIEWED_READY_FOR_T15") != EXPECTED_REVIEWED_STAGE:
        errors.append("reviewed-ready stage contract drift")
    if set(stage_doc.get("stages", {})) != {"POPULATED_PENDING_REVIEW", "REVIEWED_READY_FOR_T15"}:
        errors.append("unexpected stage contract entry")
    stage = EXPECTED_REVIEWED_STAGE
    artifact = load(repo / "schema/premium_interpretation_database_v1.json")
    tasks = load(repo / "docs/roadmap/tasks.json")
    sources = load(root / "ontology/sources.json")
    schools = load(root / "ontology/schools.json")
    domains = load(root / "ontology/domains.json")
    concepts = load(root / "ontology/concepts.json")
    claims = load(root / "ontology/source_claims.json")
    rels = load(root / "ontology/concept_relationships.json")["relationships"]
    gaps = load(root / "traceability/source_gaps.json")["gaps"]
    exclusions = load(root / "traceability/exclusions.json")
    trace = load(root / "traceability/research_to_production.json")["records"]
    research_sources = load(repo / "research/graphology/foundations-v0.1/sources.json")
    research_meta = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")

    for key, expected in {
        "status": stage["manifest_status"],
        "production_scope": stage["production_scope"],
        "t26_status": stage["t26_status"],
        "compiled_runtime_artifact_status": stage["compiled_runtime_artifact_status"],
        "runtime_activation": stage["runtime_activation"],
    }.items():
        if manifest.get(key) != expected:
            errors.append(f"manifest stage mismatch: {key}")
    expected_manifest_identity = {
        "database_id": "graphology-interpretation",
        "version": "1.0.0-rc.1",
        "research_snapshot": "research/graphology/foundations-v0.1",
        "canonical_feature_database": "schema/graphology_feature_database_v1.json",
        "compiled_runtime_artifact": "schema/premium_interpretation_database_v1.json",
        "next_pr": "T15 — downstream consumer after T00/T01/T05/T09 prerequisites",
    }
    for key, val in expected_manifest_identity.items():
        if manifest.get(key) != val:
            errors.append(f"manifest identity/path drift: {key}")
    if manifest.get("construction_lineage") != EXPECTED_LINEAGE:
        errors.append("manifest construction lineage drift")
    if manifest.get("research_baseline_commit") != "f96aa6b54cfaf91f0a8243e7c7e266baa053eedc":
        errors.append("manifest research baseline mismatch")
    if (
        artifact.get("status") != stage["artifact_status"]
        or artifact.get("runtime_activation") != stage["artifact_runtime_activation"]
    ):
        errors.append("artifact stage mismatch")
    if next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] != stage["t26_status"]:
        errors.append("T26 task stage mismatch")

    if any(x.get("runtime_role") != "PROVENANCE_ONLY" for x in sources):
        errors.append("source runtime role activated")
    if any(x.get("runtime_status") != "ONTOLOGY_ONLY" for x in schools):
        errors.append("school activated")
    if any(x.get("runtime_status") != "ONTOLOGY_ONLY" for x in domains):
        errors.append("domain activated")
    if any(x.get("runtime_status") != "ONTOLOGY_ONLY" for x in concepts):
        errors.append("concept activated")
    if any(x.get("runtime_status") != "ONTOLOGY_ONLY" for x in rels):
        errors.append("concept relationship activated")
    if (
        len(rels) != 1
        or rels[0]["left_concept_id"] != "IHAS_THREAD"
        or rels[0]["right_concept_id"] != "MORETTI_FILIFORME"
        or rels[0]["relationship_type"] != "UNMAPPED"
    ):
        errors.append("IHAS thread / Moretti Filiforme must remain UNMAPPED")

    source_ids = {x["source_id"] for x in sources}
    concept_ids = {x["concept_id"] for x in concepts}
    gap_ids = [x["gap_id"] for x in gaps]
    if len(gap_ids) != len(set(gap_ids)):
        errors.append("duplicate source-gap ID")
    for g in gaps:
        if g["object_kind"] == "SOURCE" and g["object_id"] not in source_ids:
            errors.append(f"orphan source gap: {g['gap_id']}")
        if g["object_kind"] == "CONCEPT" and g["object_id"] not in concept_ids:
            errors.append(f"orphan concept gap: {g['gap_id']}")
        if g["object_kind"] == "UNRESOLVED_SOURCE_TERM" and g.get("source_id") not in source_ids:
            errors.append(f"orphan term gap: {g['gap_id']}")
    expected_reuse = {x["source_id"] for x in sources if str(x.get("reuse_clearance", "")).startswith("NOT_ASSESSED")}
    actual_reuse = {
        x["object_id"]
        for x in gaps
        if x["object_kind"] == "SOURCE" and x.get("gap_kind") == "REUSE_CLEARANCE_NOT_ASSESSED"
    }
    if expected_reuse != actual_reuse:
        errors.append("source reuse-gap coverage mismatch")
    blockers = {x["object_id"] for x in gaps if x["object_kind"] == "CONCEPT" and x.get("blocks_runtime_activation")}
    if blockers != concept_ids:
        errors.append("concept blocker coverage mismatch")
    currency = [x for x in gaps if x["object_kind"] == "UNRESOLVED_SOURCE_TERM" and x["object_id"] == "currency"]
    if (
        len(currency) != 1
        or currency[0].get("source_id") != "BIG26"
        or not currency[0].get("blocks_runtime_activation")
    ):
        errors.append("currency gap invalid")

    vals = exclusions.get("intentionally_not_in_scope", [])
    if len(vals) != len(set(vals)):
        errors.append("duplicate exclusions")
    if set(vals) != set(stage["required_exclusions"]):
        errors.append("current exclusions differ from stage contract")
    if exclusions.get("research_baseline_commit") != "f96aa6b54cfaf91f0a8243e7c7e266baa053eedc":
        errors.append("exclusions baseline mismatch")

    expected_pairs = {
        *{("SOURCE", x["source_id"], "SOURCE", x["source_id"]) for x in research_sources},
        *{("SCHOOL", x["school_id"], "SCHOOL", x["school_id"]) for x in research_meta["schools"]},
        *{("DOMAIN", x["domain_id"], "DOMAIN", x["domain_id"]) for x in research_meta["domains"]},
        *{("CONCEPT", x["concept_id"], "CONCEPT", x["concept_id"]) for x in research_meta["school_concepts"]},
        *{
            ("SOURCE_ASSERTION", x["assertion_id"], "SOURCE_CLAIM", x["assertion_id"])
            for x in research_meta["source_assertions"]
        },
        *{
            ("UNRESOLVED_SOURCE_TERM", x["term"], "SOURCE_GAP", "GAP_UNRESOLVED_TERM_1")
            for x in research_meta["unresolved_source_terms"]
        },
    }
    actual_pairs = [(x["research_kind"], x["research_id"], x["production_kind"], x["production_id"]) for x in trace]
    if len(actual_pairs) != len(set(actual_pairs)):
        errors.append("duplicate foundation trace mapping")
    if set(actual_pairs) != expected_pairs:
        missing = sorted(expected_pairs - set(actual_pairs))
        extra = sorted(set(actual_pairs) - expected_pairs)
        if missing:
            errors.append("foundation trace mapping missing: " + repr(missing))
        if extra:
            errors.append("foundation trace mapping unexpected: " + repr(extra))

    registry = {
        "SOURCE": {x["source_id"] for x in sources},
        "SCHOOL": {x["school_id"] for x in schools},
        "DOMAIN": {x["domain_id"] for x in domains},
        "CONCEPT": {x["concept_id"] for x in concepts},
        "SOURCE_CLAIM": {x["assertion_id"] for x in claims},
        "SOURCE_GAP": {x["gap_id"] for x in gaps},
    }
    kind_map = {
        "SOURCE": "SOURCE",
        "SCHOOL": "SCHOOL",
        "DOMAIN": "DOMAIN",
        "CONCEPT": "CONCEPT",
        "SOURCE_ASSERTION": "SOURCE_CLAIM",
        "UNRESOLVED_SOURCE_TERM": "SOURCE_GAP",
    }
    for r in trace:
        pk = r["production_kind"]
        pid = r["production_id"]
        if pk not in registry or pid not in registry[pk]:
            errors.append(f"trace endpoint missing: {pk}:{pid}")
        if r["research_kind"] in kind_map and pk != kind_map[r["research_kind"]]:
            errors.append(f"trace kind mismatch: {r['research_kind']}:{r['research_id']}")
    return errors


def main():
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
