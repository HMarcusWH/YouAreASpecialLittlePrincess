"""Pure, bounded handwriting descriptor and relation selection.

This module does not authorize a report, image, purchase or Premium job. Its
inputs are saved report facts and versioned, reviewed registries; all wording
is owned by those registries rather than produced here. The new reading-v2
catalogues are not yet installed, so no new report writer invokes this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .presentation import group_nominees, presentation_registry

MAX_DESCRIPTORS = 12
MAX_RELATIONS = 8
RELATION_POLICY_VERSION = "combination-policy/1"
RELATION_KINDS = frozenset({"CONTRAST", "COOCCURRENCE"})


@dataclass(frozen=True)
class ReadingDescriptor:
    """A selected existing highlight candidate, with its original fact support."""

    candidate_id: str
    family: str
    correlation_group: str
    content_id: str
    strength: float
    support_fact_ids: tuple[str, ...]
    source_region_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReadingRelation:
    """A reviewed noncausal relationship; never a new measurement or score."""

    relation_id: str
    kind: str
    content_id: str
    descriptor_ids: tuple[str, ...]
    support_fact_ids: tuple[str, ...]


def _facts_by_id(facts: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(facts, (tuple, list)):
        raise ValueError("reading facts must be a saved ordered sequence")
    by_id: dict[str, Mapping[str, Any]] = {}
    seen_features: set[str] = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            raise ValueError("reading fact must be a mapping")
        fact_id = fact.get("fact_id")
        feature_id = fact.get("feature_id")
        if (not isinstance(fact_id, str) or not isinstance(feature_id, str)
                or fact_id != f"fact.{feature_id}"
                or fact_id in by_id or feature_id in seen_features):
            raise ValueError("duplicate or unbound reading fact")
        regions = fact.get("source_region_ids")
        if not isinstance(regions, (tuple, list)) or any(
                not isinstance(region, str) or not region for region in regions):
            raise ValueError("reading fact has invalid source region IDs")
        by_id[fact_id] = fact
        seen_features.add(feature_id)
    return by_id


def select_descriptors(
    facts: Sequence[Mapping[str, Any]], registry: Mapping[str, Any],
) -> tuple[ReadingDescriptor, ...]:
    """Select at most twelve factual descriptions using approved highlight rules.

    The supplied presentation registry must match the installed version
    exactly; callers cannot inject a new rule or lower a threshold. Selection
    reuses the existing observed-fact eligibility and per-correlation-group
    winner logic. This function is intentionally pure and has no fallback to
    another version when the requested registry is not installed.
    """
    if not isinstance(registry, Mapping):
        raise ValueError("reading presentation registry must be a mapping")
    version = registry.get("version")
    if not isinstance(version, str):
        raise ValueError("missing reading presentation version")
    try:
        reviewed = presentation_registry(version=version)
    except (ValueError, KeyError, OSError) as exc:
        raise ValueError("reading presentation version is unavailable") from exc
    if registry != reviewed:
        raise ValueError("reading presentation registry differs from reviewed source")

    by_fact = _facts_by_id(facts)
    specifications = {row["candidate_id"]: row for row in reviewed["candidates"]}
    selected = sorted(
        group_nominees(facts, version=version),
        key=lambda candidate: (-candidate.strength, candidate.candidate_id),
    )[:MAX_DESCRIPTORS]
    descriptors: list[ReadingDescriptor] = []
    for candidate in selected:
        spec = specifications[candidate.candidate_id]
        support = tuple(candidate.support_fact_ids)
        if not support or any(fid not in by_fact for fid in support):
            raise ValueError("reading descriptor has foreign fact support")
        regions = tuple(sorted({
            region_id
            for fid in support
            for region_id in by_fact[fid]["source_region_ids"]
        }))
        if not isfinite(candidate.strength) or not 0 <= candidate.strength <= 1:
            raise ValueError("reading descriptor has invalid strength")
        descriptors.append(ReadingDescriptor(
            candidate_id=candidate.candidate_id,
            family=candidate.family,
            correlation_group=spec["correlation_group"],
            content_id=candidate.content_id,
            strength=candidate.strength,
            support_fact_ids=support,
            source_region_ids=regions,
        ))
    return tuple(descriptors)


def select_relations(
    descriptors: Sequence[ReadingDescriptor], registry: Mapping[str, Any],
) -> tuple[ReadingRelation, ...]:
    """Apply only supplied, reviewed relation rules in stable catalogue order.

    A missing operand removes a relationship. Every relationship must involve
    two different feature families and carry the exact union of participating
    fact IDs. The authoritative generator/manifest validates the registry
    before it can be activated; this pure function does not activate it.
    """
    if (not isinstance(registry, Mapping)
            or registry.get("policy_version") != RELATION_POLICY_VERSION):
        raise ValueError("unsupported reading relation policy")
    rules = registry.get("relations")
    if not isinstance(rules, (list, tuple)) or len(rules) > MAX_RELATIONS:
        raise ValueError("invalid reading relation catalogue")
    if not isinstance(descriptors, (tuple, list)) or len(descriptors) > MAX_DESCRIPTORS:
        raise ValueError("invalid reading descriptor selection")
    selected: dict[str, ReadingDescriptor] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, ReadingDescriptor) or descriptor.candidate_id in selected:
            raise ValueError("invalid or duplicate reading descriptor")
        if (not descriptor.support_fact_ids
                or not isfinite(descriptor.strength)
                or any(not isinstance(fid, str) or not fid for fid in descriptor.support_fact_ids)):
            raise ValueError("invalid relation descriptor support")
        selected[descriptor.candidate_id] = descriptor

    results: list[ReadingRelation] = []
    seen_relations: set[str] = set()
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise ValueError("invalid reading relation rule")
        relation_id = rule.get("relation_id")
        kind = rule.get("kind")
        content_id = rule.get("content_id")
        required = rule.get("required_descriptors")
        if (not isinstance(relation_id, str) or not relation_id
                or relation_id in seen_relations
                or kind not in RELATION_KINDS
                or not isinstance(content_id, str) or not content_id
                or not isinstance(required, (list, tuple))
                or len(required) < 2
                or any(not isinstance(cid, str) or not cid for cid in required)
                or len(required) != len(set(required))):
            raise ValueError("invalid or duplicate reading relation")
        seen_relations.add(relation_id)
        if any(cid not in selected for cid in required):
            continue
        operands = [selected[cid] for cid in required]
        if len({operand.family for operand in operands}) < 2:
            raise ValueError("same-family relation is not a cross-feature observation")
        facts = tuple(sorted({
            fact_id for operand in operands for fact_id in operand.support_fact_ids
        }))
        if not facts:
            raise ValueError("reading relation lacks observed fact support")
        results.append(ReadingRelation(
            relation_id=relation_id, kind=kind, content_id=content_id,
            descriptor_ids=tuple(required), support_fact_ids=facts,
        ))
    return tuple(results)
