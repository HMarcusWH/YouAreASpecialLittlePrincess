"""Ontology/provenance regression tests after the T26 repair round."""

from pathlib import Path
import importlib.util
import json

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(m)
    return m


v = module("ont", "validate_graphology_ontology.py")


def load(p):
    return json.loads((REPO / p).read_text())


def test_validator_passes():
    assert v.validate(REPO) == []


def test_cross_school_relation_is_unmapped():
    r = load("schema/graphology_interpretation/v1/ontology/concept_relationships.json")["relationships"][0]
    assert r["relationship_type"] == "UNMAPPED"


def test_research_baseline_is_pinned():
    m = load("schema/graphology_interpretation/v1/manifest.json")
    assert m["research_baseline_commit"] == "f96aa6b54cfaf91f0a8243e7c7e266baa053eedc"


def test_all_ontology_records_remain_inactive():
    assert all(
        x["runtime_role"] == "PROVENANCE_ONLY"
        for x in load("schema/graphology_interpretation/v1/ontology/sources.json")
    )
    assert all(
        x["runtime_status"] == "ONTOLOGY_ONLY"
        for x in load("schema/graphology_interpretation/v1/ontology/schools.json")
    )
    assert all(
        x["runtime_status"] == "ONTOLOGY_ONLY"
        for x in load("schema/graphology_interpretation/v1/ontology/domains.json")
    )
    assert all(
        x["runtime_status"] == "ONTOLOGY_ONLY"
        for x in load("schema/graphology_interpretation/v1/ontology/concepts.json")
    )
