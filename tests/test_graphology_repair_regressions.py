"""Negative regressions for the Codex T26 repair rounds."""
from __future__ import annotations
import importlib.util, json, shutil
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]; TOOLS=REPO/"tools"
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,TOOLS/file); m=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(m); return m
common=module("common","graphology_db_common.py")
integrity=module("integrity","validate_graphology_integrity.py")
selector=module("selector","validate_graphology_selector_foundation.py")
traditional=module("traditional","validate_graphology_traditional_rules.py")
database=module("database","validate_graphology_database.py")

def copy_validation_repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO/"research",tmp_path/"research")
    shutil.copytree(REPO/"schema/graphology_interpretation",tmp_path/"schema/graphology_interpretation")
    (tmp_path/"schema").mkdir(exist_ok=True)
    shutil.copy2(REPO/"schema/premium_interpretation_database_v1.json",tmp_path/"schema/premium_interpretation_database_v1.json")
    shutil.copy2(REPO/"schema/graphology_feature_database_v1.json",tmp_path/"schema/graphology_feature_database_v1.json")
    (tmp_path/"docs/roadmap").mkdir(parents=True)
    shutil.copy2(REPO/"docs/roadmap/tasks.json",tmp_path/"docs/roadmap/tasks.json")
    (tmp_path/"tools").mkdir()
    shutil.copy2(REPO/"tools/compile_premium_interpretation_db.py",tmp_path/"tools/compile_premium_interpretation_db.py")
    shutil.copy2(REPO/"tools/graphology_db_common.py",tmp_path/"tools/graphology_db_common.py")
    return tmp_path

def rewrite(path: Path, fn):
    data=json.loads(path.read_text()); fn(data); path.write_text(json.dumps(data,indent=2)+"\n")

def test_mutated_original_import_file_is_detected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"research/graphology/foundations-v0.1/sources.json"
    rewrite(path,lambda d:d[0].__setitem__("title",d[0]["title"]+" MUTATED"))
    assert any("mismatch" in e for e in common.verify_research_baseline(repo))

def test_mutated_snapshot_only_file_is_detected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"research/graphology/foundations-v0.1/README.md"
    path.write_text(path.read_text()+"\nMUTATED\n")
    assert any("Git blob mismatch" in e for e in common.verify_research_baseline(repo))

def test_unexpected_snapshot_file_is_detected(tmp_path):
    repo=copy_validation_repo(tmp_path); (repo/"research/graphology/foundations-v0.1/UNEXPECTED.md").write_text("x")
    assert any("unexpected files added" in e for e in common.verify_research_baseline(repo))

def test_invalid_trace_endpoint_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traceability/research_to_production.json"
    rewrite(path,lambda d:d["records"][0].__setitem__("production_id","DOES_NOT_EXIST"))
    assert any("trace endpoint missing" in e for e in integrity.validate(repo))

def test_missing_trace_record_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traceability/research_to_production.json"
    rewrite(path,lambda d:d["records"].pop())
    assert any("foundation trace missing" in e for e in integrity.validate(repo))

def test_overstrong_cross_school_relation_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/ontology/concept_relationships.json"
    rewrite(path,lambda d:d["relationships"][0].__setitem__("relationship_type","NOT_EQUIVALENT"))
    assert any("must remain UNMAPPED" in e for e in integrity.validate(repo))

def test_missing_reuse_gap_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traceability/source_gaps.json"
    rewrite(path,lambda d:d.__setitem__("gaps",[g for g in d["gaps"] if g["gap_id"]!="GAP_REUSE_IHAS"]))
    assert any("reuse-gap coverage" in e for e in integrity.validate(repo))

def test_premature_manifest_promotion_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/manifest.json"
    rewrite(path,lambda d:d.__setitem__("status","ACTIVE"))
    assert any("manifest stage mismatch" in e for e in integrity.validate(repo))

def test_nested_value_set_activation_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/values/value_sets.json"
    rewrite(path,lambda d:d[0].__setitem__("runtime_activation",True))
    assert any("value-set lifecycle" in e for e in selector.validate(repo))

def test_reference_generator_requires_authoritative_results(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/candidates/generator_contracts.json"
    def mutate(d):
        g=next(x for x in d["records"] if x["candidate_kind_id"]=="ELIGIBLE_REFERENCE_CLAIM"); g["required_inputs"]=[]
    rewrite(path,mutate)
    assert any("reference-service inputs" in e for e in selector.validate(repo))

def test_duplicate_generator_contract_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/candidates/generator_contracts.json"
    rewrite(path,lambda d:d["records"].append(dict(d["records"][0])))
    assert any("duplicate candidate generator" in e for e in selector.validate(repo))

def test_duplicate_selector_generator_mapping_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/candidates/selector_generator_map.json"
    rewrite(path,lambda d:d["records"].append(dict(d["records"][0])))
    assert any("duplicate selector-generator mapping" in e for e in selector.validate(repo))

def test_moretti_decimi_activation_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traditional/method_policies.json"
    def mutate(d):
        p=next(x for x in d["records"] if x["policy_id"]=="POLICY_MORETTI_TYPED_RELATIONS_V1"); p["constraints"]["enable_decimi_scoring"]=True
    rewrite(path,mutate)
    assert any("Moretti blocked scoring" in e for e in traditional.validate(repo))

def test_jamin_inverse_inference_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traditional/method_policies.json"
    def mutate(d):
        p=next(x for x in d["records"] if x["policy_id"]=="POLICY_CJ_ABSENCE_GUARD_V1"); p["constraints"]["absent_positive_sign_activates_opposite"]=True
    rewrite(path,mutate)
    assert any("absence guard permits" in e for e in traditional.validate(repo))

def test_association_locator_drift_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/traditional/associations/jaminian.json"
    rewrite(path,lambda d:d[0].__setitem__("locator","WRONG"))
    assert any("association provenance drift locator" in e for e in traditional.validate(repo))

def test_soft_field_new_numbers_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/narrative/soft_fields.json"
    rewrite(path,lambda d:d["records"][0].__setitem__("allow_new_numbers",True))
    assert any("soft field" in e and "guard" in e for e in database.validate(repo))

def test_question_model_role_drift_is_rejected(tmp_path):
    repo=copy_validation_repo(tmp_path); path=repo/"schema/graphology_interpretation/v1/questions/01-context.json"
    rewrite(path,lambda d:d[0].__setitem__("model_call_role","ANSWER"))
    assert any("production question drift model_call_role" in e for e in database.validate(repo))
