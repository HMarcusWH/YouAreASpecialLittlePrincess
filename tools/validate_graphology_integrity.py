#!/usr/bin/env python3
"""Validate ontology provenance, lifecycle, traceability, source gaps and stage boundaries."""
from __future__ import annotations
from pathlib import Path
import json, sys
from graphology_db_common import load, verify_research_baseline

def validate(repo: Path) -> list[str]:
    root=repo/"schema/graphology_interpretation/v1"
    errors=list(verify_research_baseline(repo))
    manifest=load(root/"manifest.json")
    stage_doc=load(root/"stage_contract.json")
    stage=stage_doc["stages"][stage_doc["current_stage"]]
    sources=load(root/"ontology/sources.json")
    schools=load(root/"ontology/schools.json")
    domains=load(root/"ontology/domains.json")
    concepts=load(root/"ontology/concepts.json")
    claims=load(root/"ontology/source_claims.json")
    rels=load(root/"ontology/concept_relationships.json")["relationships"]
    gaps=load(root/"traceability/source_gaps.json")["gaps"]
    exclusions=load(root/"traceability/exclusions.json")
    trace=load(root/"traceability/research_to_production.json")["records"]

    expected_manifest={
      "status":stage["manifest_status"],"production_scope":stage["production_scope"],
      "t26_status":stage["t26_status"],"compiled_runtime_artifact_status":stage["compiled_runtime_artifact_status"],
      "runtime_activation":stage["runtime_activation"],
    }
    for k,v in expected_manifest.items():
        if manifest.get(k)!=v: errors.append(f"manifest stage mismatch for {k}")
    if manifest.get("research_baseline_commit")!="f96aa6b54cfaf91f0a8243e7c7e266baa053eedc":
        errors.append("manifest research baseline is ambiguous or incorrect")

    if any(x.get("runtime_role")!="PROVENANCE_ONLY" for x in sources):
        errors.append("source registry contains non-provenance runtime role")
    if any(x.get("runtime_status")!="ONTOLOGY_ONLY" for x in schools):
        errors.append("school registry contains activated record")
    if any(x.get("runtime_status")!="ONTOLOGY_ONLY" for x in domains):
        errors.append("domain registry contains activated record")
    if any(x.get("runtime_status")!="ONTOLOGY_ONLY" for x in concepts):
        errors.append("concept registry contains activated record")
    if any(x.get("runtime_status")!="ONTOLOGY_ONLY" for x in rels):
        errors.append("concept relationship contains activated record")

    if len(rels)!=1 or rels[0]["left_concept_id"]!="IHAS_THREAD" or rels[0]["right_concept_id"]!="MORETTI_FILIFORME" or rels[0]["relationship_type"]!="UNMAPPED":
        errors.append("IHAS thread / Moretti Filiforme relationship must remain UNMAPPED")

    gap_ids=[x["gap_id"] for x in gaps]
    if len(gap_ids)!=len(set(gap_ids)): errors.append("duplicate source-gap ID")
    source_ids={x["source_id"] for x in sources}; concept_ids={x["concept_id"] for x in concepts}
    for g in gaps:
        if g["object_kind"]=="SOURCE" and g["object_id"] not in source_ids: errors.append(f"source gap does not resolve: {g['gap_id']}")
        if g["object_kind"]=="CONCEPT" and g["object_id"] not in concept_ids: errors.append(f"concept gap does not resolve: {g['gap_id']}")
        if g["object_kind"]=="UNRESOLVED_SOURCE_TERM" and g.get("source_id") not in source_ids: errors.append(f"term gap source does not resolve: {g['gap_id']}")
    expected_reuse={x["source_id"] for x in sources if str(x.get("reuse_clearance","")).startswith("NOT_ASSESSED")}
    actual_reuse={x["object_id"] for x in gaps if x["object_kind"]=="SOURCE" and x.get("gap_kind")=="REUSE_CLEARANCE_NOT_ASSESSED"}
    if actual_reuse!=expected_reuse: errors.append("reuse-clearance gap coverage differs from source registry")
    concept_blockers={x["object_id"] for x in gaps if x["object_kind"]=="CONCEPT" and x.get("blocks_runtime_activation")}
    if concept_blockers!=concept_ids: errors.append("concept blocker coverage differs from concept registry")
    currency=[x for x in gaps if x["object_kind"]=="UNRESOLVED_SOURCE_TERM" and x["object_id"]=="currency"]
    if len(currency)!=1 or currency[0].get("source_id")!="BIG26" or not currency[0].get("blocks_runtime_activation"):
        errors.append("currency source gap invalid")

    if exclusions.get("research_baseline_commit")!="f96aa6b54cfaf91f0a8243e7c7e266baa053eedc": errors.append("exclusions baseline mismatch")
    vals=exclusions.get("intentionally_not_in_scope",[])
    if len(vals)!=len(set(vals)): errors.append("duplicate exclusions")
    if set(vals)!=set(stage["required_exclusions"]): errors.append("exclusions differ from current stage contract")

    registry={
      "SOURCE":{x["source_id"] for x in sources},
      "SCHOOL":{x["school_id"] for x in schools},
      "DOMAIN":{x["domain_id"] for x in domains},
      "CONCEPT":{x["concept_id"] for x in concepts},
      "SOURCE_CLAIM":{x["assertion_id"] for x in claims},
      "SOURCE_GAP":{x["gap_id"] for x in gaps},
    }
    expected_kind={"SOURCE":"SOURCE","SCHOOL":"SCHOOL","DOMAIN":"DOMAIN","CONCEPT":"CONCEPT","SOURCE_ASSERTION":"SOURCE_CLAIM","UNRESOLVED_SOURCE_TERM":"SOURCE_GAP"}
    for r in trace:
        pk=r["production_kind"]; pid=r["production_id"]
        if pk not in registry or pid not in registry[pk]:
            errors.append(f"trace production endpoint does not resolve: {pk}:{pid}")
        rk=r["research_kind"]
        if rk in expected_kind and pk!=expected_kind[rk]:
            errors.append(f"trace production kind mismatch for {rk}:{r['research_id']}")
    return errors

def main():
    repo=Path(__file__).resolve().parents[1]
    errors=validate(repo)
    print(json.dumps({"status":"PASS" if not errors else "FAIL","errors":errors},indent=2))
    return 0 if not errors else 1
if __name__=="__main__": sys.exit(main())
