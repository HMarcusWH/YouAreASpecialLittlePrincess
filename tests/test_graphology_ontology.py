"""Tests for T26 PR1 graphology ontology/provenance foundation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO / "tools/validate_graphology_ontology.py"
SPEC = importlib.util.spec_from_file_location("graphology_ontology_validator", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


def load(relative: str):
    return json.loads((REPO / relative).read_text(encoding="utf-8"))


def test_foundation_validator_passes():
    assert validator.validate(REPO) == []


def test_production_scaffold_stays_unpopulated():
    assert load("schema/premium_interpretation_database_v1.json")["status"] == "UNPOPULATED"


def test_five_traditions_plus_application_namespace():
    schools = load("schema/graphology_interpretation/v1/ontology/schools.json")
    assert sum(x["school_kind"] == "GRAPHOLOGY_TRADITION_PROFILE" for x in schools) == 5
    assert [x["school_id"] for x in schools if x["school_kind"] == "APPLICATION_NAMESPACE"] == ["APPLICATION"]


def test_historical_examples_remain_non_executable():
    claims = load("schema/graphology_interpretation/v1/ontology/source_claims.json")
    historical = [x for x in claims if x["claim_kind"] == "HISTORICAL_INTERPRETIVE_ASSOCIATION"]
    assert historical
    assert all(x["runtime_role"] == "RESEARCH_ONLY_DO_NOT_EXECUTE" for x in historical)
    assert all(x["production_status"] == "REGISTERED_RESEARCH_ONLY" for x in historical)


def test_all_concepts_are_ontology_only_and_blocked():
    concepts = load("schema/graphology_interpretation/v1/ontology/concepts.json")
    gaps = load("schema/graphology_interpretation/v1/traceability/source_gaps.json")["gaps"]
    blocked = {x["object_id"] for x in gaps if x["object_kind"] == "CONCEPT" and x["blocks_runtime_activation"]}
    assert all(x["runtime_status"] == "ONTOLOGY_ONLY" for x in concepts)
    assert blocked == {x["concept_id"] for x in concepts}


def test_thread_and_filiforme_are_not_equated():
    rel = load("schema/graphology_interpretation/v1/ontology/concept_relationships.json")["relationships"]
    matches = [x for x in rel if {x["left_concept_id"], x["right_concept_id"]} == {"IHAS_THREAD", "MORETTI_FILIFORME"}]
    assert len(matches) == 1
    assert matches[0]["relationship_type"] == "NOT_EQUIVALENT"


def test_currency_stays_blocked_without_runtime_selector():
    gaps = load("schema/graphology_interpretation/v1/traceability/source_gaps.json")["gaps"]
    currency = [x for x in gaps if x["object_kind"] == "UNRESOLVED_SOURCE_TERM" and x["object_id"] == "currency"]
    assert len(currency) == 1
    assert currency[0]["blocks_runtime_activation"] is True


def test_traceability_covers_foundation_records_exactly():
    trace = load("schema/graphology_interpretation/v1/traceability/research_to_production.json")["records"]
    assert len(trace) == 15 + 6 + 16 + 11 + 6 + 1
    assert len({(x["research_kind"], x["research_id"]) for x in trace}) == len(trace)


def test_production_foundation_is_lossless_promotion_of_research():
    research_sources = load("research/graphology/foundations-v0.1/sources.json")
    research_meta = load("research/graphology/foundations-v0.1/blueprint/metadata.json")
    sources = load("schema/graphology_interpretation/v1/ontology/sources.json")
    schools = load("schema/graphology_interpretation/v1/ontology/schools.json")
    domains = load("schema/graphology_interpretation/v1/ontology/domains.json")
    concepts = load("schema/graphology_interpretation/v1/ontology/concepts.json")
    claims = load("schema/graphology_interpretation/v1/ontology/source_claims.json")

    assert [{k: v for k, v in x.items() if k not in {"production_status", "runtime_role"}} for x in sources] == research_sources
    assert [{k: v for k, v in x.items() if k not in {"school_kind", "runtime_status"}} for x in schools] == research_meta["schools"]
    assert [{k: v for k, v in x.items() if k != "runtime_status"} for x in domains] == research_meta["domains"]
    assert [{k: v for k, v in x.items() if k != "runtime_status"} for x in concepts] == research_meta["school_concepts"]
    assert [{k: v for k, v in x.items() if k != "production_status"} for x in claims] == research_meta["source_assertions"]
