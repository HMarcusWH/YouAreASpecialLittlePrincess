"""R2 pure Free descriptor selection; no model, image grant or commerce runtime."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from princess_app.domain.content.presentation import presentation_registry
from princess_app.domain.content.reading import (
    MAX_DESCRIPTORS,
    MAX_RELATIONS,
    RELATION_POLICY_VERSION,
    ReadingDescriptor,
    select_descriptors,
    select_relations,
)

ROOT = Path(__file__).resolve().parents[1]


def saved_facts():
    source = ROOT / "fixtures" / "reports" / "report-document.v2.json"
    return json.loads(source.read_text(encoding="utf-8"))["facts"]


def available_descriptors():
    return select_descriptors(saved_facts(), presentation_registry())


def test_selection_reuses_installed_presentation_without_recomputing_facts():
    facts = saved_facts()
    before = copy.deepcopy(facts)
    descriptors = available_descriptors()
    assert 2 <= len(descriptors) <= MAX_DESCRIPTORS
    assert all(isinstance(d, ReadingDescriptor) for d in descriptors)
    assert descriptors == select_descriptors(facts, presentation_registry())
    assert facts == before
    assert list(descriptors) == sorted(descriptors, key=lambda d: (-d.strength, d.candidate_id))
    assert len({d.candidate_id for d in descriptors}) == len(descriptors)
    assert len({(d.family, d.correlation_group) for d in descriptors}) == len(descriptors)
    by_id = {fact["fact_id"]: fact for fact in facts}
    for item in descriptors:
        assert set(item.support_fact_ids) <= set(by_id)
        assert item.source_region_ids == tuple(sorted({
            rid for fid in item.support_fact_ids for rid in by_id[fid]["source_region_ids"]
        }))


def test_unreviewed_registry_cannot_change_salience_or_version():
    facts = saved_facts()
    tampered = presentation_registry()
    tampered["candidates"][0]["priority"] += 1000
    with pytest.raises(ValueError, match="reviewed source"):
        select_descriptors(facts, tampered)
    # The v2 registry now exists on this R1 source-import branch. An
    # incomplete/tampered copy must be rejected against the installed source,
    # while an unknown version still fails closed as unavailable.
    with pytest.raises(ValueError, match="reviewed source"):
        select_descriptors(facts, {"version": "presentation/2"})
    with pytest.raises(ValueError, match="unavailable"):
        select_descriptors(facts, {"version": "presentation/999"})
    with pytest.raises(ValueError, match="missing reading presentation"):
        select_descriptors(facts, {})


def test_invalid_and_duplicate_saved_fact_ids_are_not_reinterpreted():
    facts = saved_facts()
    with pytest.raises(ValueError, match="duplicate"):
        select_descriptors(facts + [dict(facts[0])], presentation_registry())
    broken = copy.deepcopy(facts)
    broken[0]["fact_id"] = "fact.NOT_THE_SAME_FEATURE"
    with pytest.raises(ValueError, match="unbound"):
        select_descriptors(broken, presentation_registry())
    broken = copy.deepcopy(facts)
    broken[0]["source_region_ids"] = ["page_0", 42]
    with pytest.raises(ValueError, match="region"):
        select_descriptors(broken, presentation_registry())


def test_unavailable_measurements_do_not_become_pseudovalues():
    facts = saved_facts()
    missing = copy.deepcopy(facts)
    for fact in missing:
        fact["availability"] = "MISSING"
        fact["value"] = None
    assert select_descriptors(missing, presentation_registry()) == ()


def _policy(rules):
    return {"policy_version": RELATION_POLICY_VERSION, "relations": rules}


def test_supported_cross_family_relation_has_exact_union_in_catalogue_order():
    descriptors = available_descriptors()
    pair = next(
        (left, right)
        for left in descriptors for right in descriptors
        if left.family != right.family
    )
    left, right = pair
    rule = {
        "relation_id": "synthetic.cross_family",
        "kind": "CONTRAST",
        "content_id": "content.synthetic.not_for_publication",
        "required_descriptors": [left.candidate_id, right.candidate_id],
    }
    unavailable = {
        "relation_id": "synthetic.not_applicable",
        "kind": "COOCCURRENCE",
        "content_id": "content.synthetic.unavailable",
        "required_descriptors": [left.candidate_id, "unavailable.candidate"],
    }
    before = copy.deepcopy(descriptors)
    relations = select_relations(descriptors, _policy([unavailable, rule]))
    assert descriptors == before
    assert len(relations) == 1 and len(relations) <= MAX_RELATIONS
    assert relations[0].relation_id == rule["relation_id"]
    assert relations[0].kind == "CONTRAST"
    assert relations[0].descriptor_ids == (left.candidate_id, right.candidate_id)
    assert relations[0].support_fact_ids == tuple(sorted(set(left.support_fact_ids)
                                                        | set(right.support_fact_ids)))


def test_relationships_fail_closed_on_bad_rules_and_foreign_support():
    descriptors = available_descriptors()
    left, right = next(
        (a, b) for a in descriptors for b in descriptors if a.family != b.family
    )
    valid = {"relation_id": "synthetic.one", "kind": "CONTRAST",
             "content_id": "content.synthetic.one",
             "required_descriptors": [left.candidate_id, right.candidate_id]}
    for invalid in (
        [{**valid, "kind": "PERSONALITY"}],
        [{**valid, "required_descriptors": [left.candidate_id]}],
        [{**valid, "required_descriptors": [left.candidate_id, left.candidate_id]}],
        [valid, valid],
    ):
        with pytest.raises(ValueError):
            select_relations(descriptors, _policy(invalid))
    with pytest.raises(ValueError, match="policy"):
        select_relations(descriptors, {"policy_version": "unapproved", "relations": [valid]})
    with pytest.raises(ValueError, match="invalid"):
        select_relations(descriptors, _policy([valid] * (MAX_RELATIONS + 1)))
    with pytest.raises(ValueError, match="duplicate"):
        select_relations((left, left), _policy([valid]))
    forged = replace(right, family=left.family)
    with pytest.raises(ValueError, match="same-family"):
        select_relations((left, forged), _policy([valid]))
