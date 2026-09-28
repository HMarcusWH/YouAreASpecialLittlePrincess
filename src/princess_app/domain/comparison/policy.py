"""Deterministic, calibration-independent comparison policy (T18).

Only features with an approved T08A intrinsic/mathematical display domain are
comparison candidates. Missing or incompatible inputs are excluded explicitly;
they are never replaced with zero. This module does not compute aggregate
similarity, percent change, cosine, Euclidean or Mahalanobis scores.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from ..content import display_domain, presentation_registry

PRESENT = frozenset({"READY", "UNCALIBRATED"})
COMPARISON_METHOD_VERSION = "comparison-native-delta/1"
PAIR_ORDERING = "REQUEST_ORDER"
HISTORY_ORDERING = "REPORT_CREATED_AT"


@dataclass(frozen=True)
class FeatureAssessment:
    feature_id: str
    comparable: bool
    reason: str | None
    affected_positions: tuple[int, ...]
    facts: tuple[Mapping[str, Any], ...]
    domain: Mapping[str, Any]


def candidate_feature_ids() -> tuple[str, ...]:
    """Stable T08A comparison set; no population/reference domain is admitted."""
    registry = presentation_registry()
    return tuple(sorted(registry["display_domains"]))


def _numeric(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def _mismatch_positions(values: Sequence[object]) -> tuple[int, ...]:
    first = values[0]
    return tuple(index for index, value in enumerate(values) if value != first)


def assess_feature(feature_id: str, facts_by_position: Sequence[Mapping[str, Mapping[str, Any]]]) -> FeatureAssessment:
    domain = display_domain(feature_id)
    if domain is None:
        raise ValueError(f"feature {feature_id!r} has no approved comparison display domain")
    facts: list[Mapping[str, Any]] = []
    absent: list[int] = []
    for position, mapping in enumerate(facts_by_position):
        fact = mapping.get(feature_id)
        if fact is None:
            absent.append(position)
        else:
            facts.append(fact)
    if absent:
        return FeatureAssessment(feature_id, False, "ABSENT", tuple(absent), tuple(facts), domain)

    ordered = tuple(mapping[feature_id] for mapping in facts_by_position)
    unavailable = tuple(i for i, fact in enumerate(ordered) if fact.get("availability") not in PRESENT)
    if unavailable:
        return FeatureAssessment(feature_id, False, "UNAVAILABLE", unavailable, ordered, domain)

    non_numeric = tuple(i for i, fact in enumerate(ordered) if not _numeric(fact.get("value")))
    if non_numeric:
        return FeatureAssessment(feature_id, False, "NON_NUMERIC", non_numeric, ordered, domain)

    units = [fact.get("unit") for fact in ordered]
    if len(set(units)) != 1:
        return FeatureAssessment(feature_id, False, "UNIT_MISMATCH", _mismatch_positions(units), ordered, domain)
    if units[0] != domain["unit"]:
        return FeatureAssessment(feature_id, False, "DOMAIN_UNIT_MISMATCH", tuple(range(len(ordered))), ordered, domain)

    method_ids = [fact.get("method_id") for fact in ordered]
    if len(set(method_ids)) != 1:
        return FeatureAssessment(feature_id, False, "METHOD_ID_MISMATCH", _mismatch_positions(method_ids), ordered, domain)

    method_versions = [fact.get("method_version") for fact in ordered]
    if len(set(method_versions)) != 1:
        return FeatureAssessment(
            feature_id, False, "METHOD_VERSION_MISMATCH", _mismatch_positions(method_versions), ordered, domain
        )

    formatting = [(fact.get("formatting_key"), fact.get("precision")) for fact in ordered]
    if len(set(formatting)) != 1:
        return FeatureAssessment(feature_id, False, "FORMATTING_MISMATCH", _mismatch_positions(formatting), ordered, domain)

    return FeatureAssessment(feature_id, True, None, (), ordered, domain)


def native_delta(value_from: float, value_to: float) -> tuple[float, float, str]:
    """Return signed/absolute native-unit delta and non-evaluative direction."""
    signed = float(value_to) - float(value_from)
    if signed == 0.0:
        return 0.0, 0.0, "EQUAL"
    return signed, abs(signed), "TO_GREATER" if signed > 0 else "FROM_GREATER"
