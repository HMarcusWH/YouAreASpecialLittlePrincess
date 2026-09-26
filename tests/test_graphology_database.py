"""Complete compiled-database regressions."""

from pathlib import Path
import importlib.util
import json

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"


def mod(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(m)
    return m


m = mod("dbv", "validate_graphology_database.py")
compiler = mod("compiler", "compile_premium_interpretation_db.py")


def load(p):
    return json.loads((REPO / p).read_text())


def test_database_validator_passes():
    assert m.validate(REPO) == []


def test_compiler_bytes_match_committed_artifact():
    assert (
        compiler.encoded(compiler.build_database(REPO))
        == (REPO / "schema/premium_interpretation_database_v1.json").read_bytes()
    )


def test_compiled_contract_is_self_contained_and_inactive():
    db = load("schema/premium_interpretation_database_v1.json")
    for key in [
        "sources",
        "source_claims",
        "answer_state_policy",
        "selection_contract",
        "observation_envelope",
        "observation_definitions",
        "feature_mappings",
        "candidate_generator_contracts",
        "selector_generator_map",
    ]:
        assert key in db
    assert db["runtime_activation"] is False


def test_runtime_selection_axes_are_independent():
    e = load("schema/premium_interpretation_database_v1.json")["enums"]
    assert "selection_mode" not in e
    assert e["selection_domain"] == ["FIXED", "DYNAMIC"]
    assert e["cardinality"] == ["SINGLE", "MULTIPLE"]


def test_all_soft_prompt_keys_resolve_and_remain_safe():
    db = load("schema/premium_interpretation_database_v1.json")
    en = db["localization"]["en"]
    assert all(x["prompt_template_key"] in en and x["label_key"] in en for x in db["soft_field_definitions"])
    assert all(
        x["allow_new_numbers"] is False and x["no_source_no_claim"] is True for x in db["soft_field_definitions"]
    )


def test_compiled_feature_and_candidate_contracts_are_complete():
    db = load("schema/premium_interpretation_database_v1.json")
    assert len(db["feature_mappings"]) == 50
    assert len(db["candidate_generator_contracts"]) == 33
    assert len(db["selector_generator_map"]) == 35
