"""Selector/observation/candidate regression tests after the T26 repair round."""

from pathlib import Path
import importlib.util
import json

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
spec = importlib.util.spec_from_file_location("sel", TOOLS / "validate_graphology_selector_foundation.py")
m = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(m)


def load(p):
    return json.loads((REPO / p).read_text())


def concat(rel):
    return [x for n in m.DOMAINS for x in load(f"{rel}/{n}.json")]


def test_validator_passes():
    assert m.validate(REPO) == []


def test_observation_boundary_is_policy_derived():
    rq = concat("research/graphology/foundations-v0.1/blueprint/questions")
    obs = concat("schema/graphology_interpretation/v1/ontology/observations")
    assert {x["source_question_id"] for x in obs} == {q["question_id"] for q in rq if m.observation_question(q)}


def test_spacing_variability_never_drives_spacing_magnitude():
    maps = concat("schema/graphology_interpretation/v1/ontology/feature_mappings")
    by = {x["canonical_feature_id"]: x for x in maps}
    assert by["WORD_SPACING_REL"]["mapping_role"] == "PRIMARY_VALUE"
    assert by["WORD_SPACING_CV"]["mapping_role"] == "VARIABILITY_CONTEXT"
    assert by["LINE_SPACING_REL"]["mapping_role"] == "PRIMARY_VALUE"
    assert by["LINE_SPACING_CV"]["mapping_role"] == "VARIABILITY_CONTEXT"


def test_dynamic_mapped_descriptors_have_observations():
    maps = concat("schema/graphology_interpretation/v1/ontology/feature_mappings")
    for sid in {"SEL_SPACE_MARGINS", "SEL_STROKE_WIDTH", "SEL_SIG_SLANT"}:
        assert all(x["observation_id"] for x in maps if x["selector_id"] == sid)


def test_all_dynamic_selectors_have_generator_contracts():
    sels = concat("schema/graphology_interpretation/v1/selectors")
    dyn = {x["selector_id"] for x in sels if x["selection_domain"] == "DYNAMIC"}
    mp = load("schema/graphology_interpretation/v1/candidates/selector_generator_map.json")["records"]
    assert {x["selector_id"] for x in mp} == dyn


def test_database_is_reviewed_ready_and_inactive():
    db = load("schema/premium_interpretation_database_v1.json")
    tasks = load("docs/roadmap/tasks.json")
    assert db["status"] == "REVIEWED_READY_FOR_T15" and db["runtime_activation"] is False
    assert next(x for x in tasks["tasks"] if x["id"] == "T26")["status"] == "DONE"
