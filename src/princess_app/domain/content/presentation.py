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
from functools import lru_cache
from typing import Any, Mapping, Sequence

_DATA = json.loads(Path(__file__).with_name("_presentation_v1.json").read_text(encoding="utf-8"))
PRESENTATION_VERSION: str = _DATA["version"]
HIGHLIGHT_POLICY_VERSION: str = _DATA["policy_version"]
PRESENT = frozenset({"READY", "UNCALIBRATED"})

_V2_PATH = Path(__file__).with_name("_presentation_v2.json")
V2_PRESENTATION_VERSION = "presentation/2"
V2_HIGHLIGHT_POLICY_VERSION = "highlight-policy/2"


@lru_cache(maxsize=1)
def _load_v2_registry() -> dict[str, Any]:
    """Load only generated content, preserving historical predicate semantics."""
    if _V2_PATH.is_symlink() or not _V2_PATH.is_file():
        raise ValueError("presentation/2 registry is not installed")

    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate presentation/2 key")
            result[key] = value
        return result

    try:
        data = json.loads(
            _V2_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite presentation/2")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("presentation/2 registry could not be loaded") from exc

    if not isinstance(data, dict) or set(data) != set(_DATA):
        raise ValueError("presentation/2 registry shape mismatch")
    if (data.get("version"), data.get("policy_version")) != (
        V2_PRESENTATION_VERSION, V2_HIGHLIGHT_POLICY_VERSION
    ):
        raise ValueError("presentation/2 registry identity mismatch")
    for name in ("locales", "family_order", "primary_families", "threshold_policy",
                 "selection_strength_semantics", "display_domains"):
        if data.get(name) != _DATA[name]:
            raise ValueError("presentation/2 modifies frozen selection semantics")
    if data.get("feature_labels") != _DATA["feature_labels"]:
        raise ValueError("presentation/2 modifies frozen feature labels")

    source = {row["candidate_id"]: row for row in _DATA["candidates"]}
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(source) or len(source) != 54:
        raise ValueError("presentation/2 candidate-count drift")
    seen: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError("presentation/2 candidate invalid")
        candidate_id = row.get("candidate_id")
        if candidate_id in seen or candidate_id not in source:
            raise ValueError("presentation/2 candidate identity drift")
        seen.add(candidate_id)
        old_rule = {key: value for key, value in source[candidate_id].items() if key != "content_id"}
        new_rule = {key: value for key, value in row.items() if key != "content_id"}
        if old_rule != new_rule:
            raise ValueError("presentation/2 modifies a frozen highlight predicate")

    content = data.get("content")
    if (not isinstance(content, dict)
            or not all(isinstance(cid, str) and cid.startswith("content.highlight.v2.")
                       for cid in content)):
        raise ValueError("presentation/2 content must use versioned copy IDs")
    reachable = {data.get("fallback_content_id"), *(row.get("content_id") for row in candidates)}
    if set(content) != reachable:
        raise ValueError("presentation/2 copy-id closure failed")
    for records in (data["feature_labels"], content):
        for localized in records.values():
            if (not isinstance(localized, dict) or set(localized) != {"en", "sv"}
                    or any(not isinstance(value, str) or not value.strip()
                           for value in localized.values())):
                raise ValueError("presentation/2 locale closure failed")
    return data


def _registry_for_version(version: str) -> Mapping[str, Any]:
    if version == PRESENTATION_VERSION:
        return _DATA
    if version == V2_PRESENTATION_VERSION:
        return _load_v2_registry()
    raise ValueError("unsupported presentation version")



@dataclass(frozen=True)
class HighlightCandidate:
    candidate_id: str
    family: str
    content_id: str
    support_fact_ids: tuple[str, ...]
    strength: float


def presentation_registry(*, version: str = PRESENTATION_VERSION) -> Mapping[str, Any]:
    """Return a defensive copy of the reviewed registry.

    Callers may inspect presentation authority but cannot mutate process-global
    selection/content state for later reports.
    """
    return copy.deepcopy(_registry_for_version(version))


def feature_label(feature_id: str, locale: str, *, version: str = PRESENTATION_VERSION) -> str:
    registry = _registry_for_version(version)
    language = locale.split("-", 1)[0].lower()
    if language not in registry["locales"]:
        language = "en"
    try:
        return registry["feature_labels"][feature_id][language]
    except KeyError as exc:
        raise KeyError(f"unreviewed presentation feature {feature_id!r}") from exc


def content_text(content_id: str, locale: str, *, version: str = PRESENTATION_VERSION) -> str:
    registry = _registry_for_version(version)
    language = locale.split("-", 1)[0].lower()
    if language not in registry["locales"]:
        language = "en"
    try:
        return registry["content"][content_id][language]
    except KeyError as exc:
        raise KeyError(f"unknown presentation content {content_id!r}") from exc


def display_domain(feature_id: str, *, version: str = PRESENTATION_VERSION) -> Mapping[str, Any] | None:
    domain = _registry_for_version(version)["display_domains"].get(feature_id)
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

def eligible_candidates(facts: Sequence[Mapping[str, Any]], *, version: str = PRESENTATION_VERSION) -> tuple[HighlightCandidate, ...]:
    """Evaluate every reviewed candidate against saved report facts."""
    by_feature = _numeric_fact_map(facts)
    result: list[HighlightCandidate] = []
    for row in _registry_for_version(version)["candidates"]:
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


def group_nominees(facts: Sequence[Mapping[str, Any]], *, version: str = PRESENTATION_VERSION) -> tuple[HighlightCandidate, ...]:
    """Collapse mutually related states to one nominee per correlation group."""
    candidates = eligible_candidates(facts, version=version)
    spec = {row["candidate_id"]: row for row in _registry_for_version(version)["candidates"]}
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


def family_nominees(facts: Sequence[Mapping[str, Any]], *, version: str = PRESENTATION_VERSION) -> tuple[HighlightCandidate, ...]:
    """Return at most one candidate per family after correlation collapse."""
    candidates = group_nominees(facts, version=version)
    spec = {row["candidate_id"]: row for row in _registry_for_version(version)["candidates"]}
    nominees: list[HighlightCandidate] = []
    for family in _registry_for_version(version)["family_order"]:
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


def select_highlights(facts: Sequence[Mapping[str, Any]], limit: int = 3, *, version: str = PRESENTATION_VERSION) -> tuple[HighlightCandidate, ...]:
    """Select one hero plus diverse secondaries deterministically.

    Capture-sensitive image-proxy families may be useful supporting observations
    without being allowed to become the primary first-reveal statement.
    """
    registry = _registry_for_version(version)
    if type(limit) is not int or limit < 1 or limit > len(registry["family_order"]):
        raise ValueError("highlight limit must be 1..number of families")
    order = {family: index for index, family in enumerate(registry["family_order"])}
    nominees = list(family_nominees(facts, version=version))
    nominees.sort(key=lambda candidate: (-candidate.strength, order[candidate.family], candidate.candidate_id))
    primary_families = set(registry["primary_families"])
    primary = next((candidate for candidate in nominees if candidate.family in primary_families), None)
    if primary is None:
        return ()
    substantive = [candidate for candidate in nominees
                   if candidate != primary and candidate.family in primary_families]
    fallback = [candidate for candidate in nominees
                if candidate != primary and candidate.family not in primary_families]
    secondaries = [*substantive, *fallback]
    return tuple([primary, *secondaries[:max(0, limit - 1)]])
