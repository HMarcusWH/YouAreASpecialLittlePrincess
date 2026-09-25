"""Negative regressions for the Codex T26 repair round."""
from __future__ import annotations
import importlib.util, json, shutil
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]; TOOLS=REPO/"tools"
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,TOOLS/file); m=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(m); return m
common=module("common","graphology_db_common.py"); integrity=module("integrity","validate_graphology_integrity.py")

def copy_integrity_repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO/"research",tmp_path/"research")
    shutil.copytree(REPO/"schema/graphology_interpretation",tmp_path/"schema/graphology_interpretation")
    (tmp_path/"schema").mkdir(exist_ok=True)
    shutil.copy2(REPO/"schema/premium_interpretation_database_v1.json",tmp_path/"schema/premium_interpretation_database_v1.json")
    (tmp_path/"docs/roadmap").mkdir(parents=True)
    shutil.copy2(REPO/"docs/roadmap/tasks.json",tmp_path/"docs/roadmap/tasks.json")
    return tmp_path

def test_mutated_frozen_research_is_detected_even_before_production_compare(tmp_path):
    repo=copy_integrity_repo(tmp_path)
    path=repo/"research/graphology/foundations-v0.1/sources.json"
    data=json.loads(path.read_text()); data[0]["title"]=data[0]["title"]+" MUTATED"; path.write_text(json.dumps(data,indent=2)+"\n")
    assert any("SHA-256 mismatch" in e for e in common.verify_research_baseline(repo))

def test_invalid_trace_endpoint_is_rejected(tmp_path):
    repo=copy_integrity_repo(tmp_path)
    path=repo/"schema/graphology_interpretation/v1/traceability/research_to_production.json"
    data=json.loads(path.read_text()); data["records"][0]["production_id"]="DOES_NOT_EXIST"; path.write_text(json.dumps(data,indent=2)+"\n")
    assert any("trace endpoint missing" in e for e in integrity.validate(repo))

def test_overstrong_cross_school_relation_is_rejected(tmp_path):
    repo=copy_integrity_repo(tmp_path)
    path=repo/"schema/graphology_interpretation/v1/ontology/concept_relationships.json"
    data=json.loads(path.read_text()); data["relationships"][0]["relationship_type"]="NOT_EQUIVALENT"; path.write_text(json.dumps(data,indent=2)+"\n")
    assert any("must remain UNMAPPED" in e for e in integrity.validate(repo))

def test_missing_reuse_gap_is_rejected(tmp_path):
    repo=copy_integrity_repo(tmp_path)
    path=repo/"schema/graphology_interpretation/v1/traceability/source_gaps.json"
    data=json.loads(path.read_text()); data["gaps"]=[g for g in data["gaps"] if g["gap_id"]!="GAP_REUSE_IHAS"]; path.write_text(json.dumps(data,indent=2)+"\n")
    assert any("reuse-gap coverage" in e for e in integrity.validate(repo))

def test_premature_manifest_promotion_is_rejected(tmp_path):
    repo=copy_integrity_repo(tmp_path)
    path=repo/"schema/graphology_interpretation/v1/manifest.json"
    data=json.loads(path.read_text()); data["status"]="ACTIVE"; path.write_text(json.dumps(data,indent=2)+"\n")
    assert any("manifest stage mismatch" in e for e in integrity.validate(repo))
