"""Deterministic T08A presentation registry and first-reveal selector.

This module reads the generated copy of the reviewed presentation/1 registry.
It never consults a cohort, user identity, random source or current client.
Selection strength is an internal content-selection signal, never a population
rank, calibrated confidence or user-visible score.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

_DATA = json.loads(Path(__file__).with_name("_presentation_v1.json").read_text(encoding="utf-8"))
PRESENTATION_VERSION: str = _DATA["version"]
HIGHLIGHT_POLICY_VERSION: str = _DATA["policy_version"]
PRESENT = frozenset({"READY", "UNCALIBRATED"})


@dataclass(frozen=True)
class HighlightCandidate:
    candidate_id: str
    family: str
    content_id: str
    support_fact_ids: tuple[str, ...]
    strength: float


def presentation_registry() -> Mapping[str, Any]:
    """Return a defensive copy of the reviewed registry.

    Callers may inspect presentation authority but cannot mutate process-global
    selection/content state for later reports.
    """
    return copy.deepcopy(_DATA)


def feature_label(feature_id: str, locale: str) -> str:
    language = locale.split("-", 1)[0].lower()
    if language not in _DATA["locales"]:
        language = "en"
    try:
        return _DATA["feature_labels"][feature_id][language]
    except KeyError as exc:
        raise KeyError(f"unreviewed presentation feature {feature_id!r}") from exc


def content_text(content_id: str, locale: str) -> str:
    language = locale.split("-", 1)[0].lower()
    if language not in _DATA["locales"]:
        language = "en"
    try:
        return _DATA["content"][content_id][language]
    except KeyError as exc:
        raise KeyError(f"unknown presentation content {content_id!r}") from exc


def display_domain(feature_id: str) -> Mapping[str, Any] | None:
    domain = _DATA["display_domains"].get(feature_id)
    return copy.deepcopy(domain) if domain is not None else None


def _numeric_fact_map(facts: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(fact["feature_id"]): fact for fact in facts}


def _eligible_value(fact: Mapping[str, Any] | None, minimum_observations: int) -> float | None:
    if fact is None or fact.get("availability") not in PRESENT:
        return None
    value = fact.get("value")
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        return None
    quality = fact.get("quality") or {}
    observations = quality.get("n_observations")
    if type(observations) is not int or observations < minimum_observations:
        return None
    return float(value)


def _values_for(row: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]]) -> dict[str, float] | None:
    values: dict[str, float] = {}
    minimum = int(row["minimum_observations"])
    for feature_id in row["support_features"]:
        value = _eligible_value(facts.get(feature_id), minimum)
        if value is None:
            return None
        values[feature_id] = value
    return values


def _bound(value: float, clause: Mapping[str, Any]) -> bool:
    if "min" in clause and value < float(clause["min"]):
        return False
    if "max" in clause:
        maximum = float(clause["max"])
        if clause.get("max_inclusive", False):
            if value > maximum:
                return False
        elif value >= maximum:
            return False
    return True


def _matches(clause: Mapping[str, Any], values: Mapping[str, float]) -> bool:
    op = clause["op"]
    if op == "range":
        return _bound(values[clause["feature"]], clause)
    if op == "abs_range":
        return _bound(abs(values[clause["feature"]]), clause)
    if op == "difference_range":
        return _bound(values[clause["left"]] - values[clause["right"]], clause)
    if op == "max_range":
        return _bound(max(values[feature] for feature in clause["features"]), clause)
    if op == "count_at_least":
        return sum(values[feature] >= float(clause["threshold"]) for feature in clause["features"]) >= int(clause["count"])
    raise ValueError(f"unsupported presentation clause {op!r}")


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def _strength(spec: Mapping[str, Any], values: Mapping[str, float]) -> float:
    op = spec["op"]
    weight = float(spec.get("weight", 1.0))
    if op == "normalize":
        low, high = float(spec["min"]), float(spec["max"])
        value = (values[spec["feature"]] - low) / (high - low)
        raw = 1.0 - value if spec.get("invert") else value
    elif op == "distance_from":
        value = abs(values[spec["feature"]] - float(spec["center"])) / float(spec["max_distance"])
        raw = 1.0 - value if spec.get("invert") else value
    elif op == "relative_difference":
        left, right = values[spec["left"]], values[spec["right"]]
        raw = abs(left - right) / max(abs(left) + abs(right), 1e-12)
    elif op == "max_feature":
        value = max(values[feature] for feature in spec["features"])
        raw = 1.0 - value if spec.get("invert") else value
    elif op == "abs_normalize":
        value = abs(values[spec["feature"]]) / float(spec["max_abs"])
        raw = 1.0 - value if spec.get("invert") else value
    elif op == "max_abs_features":
        raw = max(abs(values[feature]) for feature in spec["features"]) / float(spec["max_abs"])
    else:
        raise ValueError(f"unsupported presentation strength {op!r}")
    return _clip(raw * weight)

def eligible_candidates(facts: Sequence[Mapping[str, Any]]) -> tuple[HighlightCandidate, ...]:
    """Evaluate every reviewed candidate against saved report facts."""
    by_feature = _numeric_fact_map(facts)
    result: list[HighlightCandidate] = []
    for row in _DATA["candidates"]:
        values = _values_for(row, by_feature)
        if values is None or not all(_matches(clause, values) for clause in row["clauses"]):
            continue
        result.append(HighlightCandidate(
            candidate_id=row["candidate_id"],
            family=row["family"],
            content_id=row["content_id"],
            support_fact_ids=tuple(by_feature[feature]["fact_id"] for feature in row["support_features"]),
            strength=_strength(row["strength"], values),
        ))
    return tuple(result)


def group_nominees(facts: Sequence[Mapping[str, Any]]) -> tuple[HighlightCandidate, ...]:
    """Collapse mutually related states to one nominee per correlation group."""
    candidates = eligible_candidates(facts)
    spec = {row["candidate_id"]: row for row in _DATA["candidates"]}
    groups: dict[tuple[str, str], list[HighlightCandidate]] = {}
    for candidate in candidates:
        row = spec[candidate.candidate_id]
        groups.setdefault((candidate.family, row["correlation_group"]), []).append(candidate)
    nominees: list[HighlightCandidate] = []
    for key in sorted(groups):
        pool = groups[key]
        pool.sort(key=lambda candidate: (
            -candidate.strength,
            -int(spec[candidate.candidate_id].get("priority", 0)),
            candidate.candidate_id,
        ))
        nominees.append(pool[0])
    return tuple(nominees)


def family_nominees(facts: Sequence[Mapping[str, Any]]) -> tuple[HighlightCandidate, ...]:
    """Return at most one candidate per family after correlation collapse."""
    candidates = group_nominees(facts)
    spec = {row["candidate_id"]: row for row in _DATA["candidates"]}
    nominees: list[HighlightCandidate] = []
    for family in _DATA["family_order"]:
        pool = [candidate for candidate in candidates if candidate.family == family]
        if not pool:
            continue
        pool.sort(key=lambda candidate: (
            -candidate.strength,
            -int(spec[candidate.candidate_id].get("priority", 0)),
            candidate.candidate_id,
        ))
        nominees.append(pool[0])
    return tuple(nominees)


def select_highlights(facts: Sequence[Mapping[str, Any]], limit: int = 3) -> tuple[HighlightCandidate, ...]:
    """Select one hero plus diverse secondaries deterministically.

    Capture-sensitive image-proxy families may be useful supporting observations
    without being allowed to become the primary first-reveal statement.
    """
    if type(limit) is not int or limit < 1 or limit > len(_DATA["family_order"]):
        raise ValueError("highlight limit must be 1..number of families")
    order = {family: index for index, family in enumerate(_DATA["family_order"])}
    nominees = list(family_nominees(facts))
    nominees.sort(key=lambda candidate: (-candidate.strength, order[candidate.family], candidate.candidate_id))
    primary_families = set(_DATA["primary_families"])
    primary = next((candidate for candidate in nominees if candidate.family in primary_families), None)
    if primary is None:
        return ()
    substantive = [candidate for candidate in nominees
                   if candidate != primary and candidate.family in primary_families]
    fallback = [candidate for candidate in nominees
                if candidate != primary and candidate.family not in primary_families]
    secondaries = [*substantive, *fallback]
    return tuple([primary, *secondaries[:max(0, limit - 1)]])
