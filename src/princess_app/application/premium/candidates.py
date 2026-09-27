"""Deterministic T15 candidate producers and explicit support dispositions.

T26 defines legal dynamic candidate kinds and generator IDs; this module decides
which of those contracts the current deterministic product evidence can actually
supply. Unsupported is an explicit state, never an invitation to infer a value
from a similarly named feature or from the handwriting image.

Supported producers expose existing report facts as neutral editorial candidates.
They do not classify values into buckets, invent calibration thresholds, compute
reference statistics, activate traditional graphology, or infer physical pressure.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    kind: str
    label_key: str
    label_en: str
    support_fact_ids: tuple[str, ...] = ()


CandidateProducer = Callable[[Mapping[str, Mapping[str, Any]]], Sequence[Candidate]]


@dataclass(frozen=True)
class GeneratorDisposition:
    generator_id: str
    candidate_kind: str
    state: str
    reason: str | None
    source_feature_ids: tuple[str, ...] = ()
    producer: CandidateProducer | None = None


def _by_feature(
    facts: Mapping[str, Mapping[str, Any]],
    feature_ids: tuple[str, ...],
) -> dict[str, tuple[str, Mapping[str, Any]]]:
    wanted = set(feature_ids)
    found: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for fact_id, fact in facts.items():
        feature_id = fact.get("feature_id")
        if feature_id in wanted:
            found[feature_id] = (fact_id, fact)
    return found


def _line_edge_trend(facts: Mapping[str, Mapping[str, Any]]) -> tuple[Candidate, ...]:
    found = _by_feature(facts, ("LINE_START_DRIFT", "LINE_END_DRIFT"))
    out = []
    for feature_id, label_key, label_en in (
        ("LINE_START_DRIFT", "candidate.line_edge_trend.start", "Observed line-start trend"),
        ("LINE_END_DRIFT", "candidate.line_edge_trend.end", "Observed line-end trend"),
    ):
        item = found.get(feature_id)
        if item is not None:
            out.append(Candidate(
                f"GEN_LINE_EDGE_TREND_V1:{feature_id}",
                "LINE_EDGE_TREND",
                label_key,
                label_en,
                (item[0],),
            ))
    return tuple(out)


def _ink_appearance(facts: Mapping[str, Mapping[str, Any]]) -> tuple[Candidate, ...]:
    found = _by_feature(facts, ("INK_DARKNESS_CV", "INK_DARKNESS_MEAN"))
    variation = found.get("INK_DARKNESS_CV")
    if variation is None:
        return ()
    support = [variation[0]]
    mean = found.get("INK_DARKNESS_MEAN")
    if mean is not None:
        support.append(mean[0])
    return (Candidate(
        "GEN_INK_APPEARANCE_FACT_V1:INK_DARKNESS_VARIATION",
        "INK_APPEARANCE_FACT",
        "candidate.ink_appearance.variation",
        "Computed ink-darkness variation (image proxy)",
        tuple(support),
    ),)


def _thickness_fact(facts: Mapping[str, Mapping[str, Any]]) -> tuple[Candidate, ...]:
    found = _by_feature(facts, ("STROKE_WIDTH_MEAN", "STROKE_WIDTH_CV"))
    mean = found.get("STROKE_WIDTH_MEAN")
    if mean is None:
        return ()
    support = [mean[0]]
    variation = found.get("STROKE_WIDTH_CV")
    if variation is not None:
        support.append(variation[0])
    return (Candidate(
        "GEN_THICKNESS_FACT_V1:STROKE_WIDTH_PROFILE",
        "THICKNESS_FACT",
        "candidate.stroke_width.profile",
        "Computed stroke-thickness profile (image proxy)",
        tuple(support),
    ),)


def _supported(generator_id: str, candidate_kind: str, source_feature_ids: tuple[str, ...],
               producer: CandidateProducer) -> GeneratorDisposition:
    return GeneratorDisposition(generator_id, candidate_kind, SUPPORTED, None, source_feature_ids, producer)


def _unsupported(generator_id: str, candidate_kind: str, reason: str) -> GeneratorDisposition:
    return GeneratorDisposition(generator_id, candidate_kind, UNSUPPORTED, reason)


# Exhaustive for the 18 unique dynamic generator contracts used by
# PREMIUM_INDIVIDUAL_GRAPHIC_V1. A T26 change that adds another generator to that
# pack must receive an explicit disposition in tests before it can pass.
GENERATOR_DISPOSITIONS: Mapping[str, GeneratorDisposition] = MappingProxyType({
    "GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1": _unsupported(
        "GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1", "MEASUREMENT_CONFLICT_CANDIDATE",
        "conflict_detector_unavailable"),
    "GEN_MARGIN_DESCRIPTION_V1": _unsupported(
        "GEN_MARGIN_DESCRIPTION_V1", "MARGIN_DESCRIPTION", "verified_page_boundaries_unavailable"),
    "GEN_LINE_EDGE_TREND_V1": _supported(
        "GEN_LINE_EDGE_TREND_V1", "LINE_EDGE_TREND",
        ("LINE_START_DRIFT", "LINE_END_DRIFT"), _line_edge_trend),
    "GEN_ORNAMENT_DESCRIPTION_V1": _unsupported(
        "GEN_ORNAMENT_DESCRIPTION_V1", "ORNAMENT_DESCRIPTION", "glyph_feature_not_implemented"),
    "GEN_REPEATED_FORM_DESCRIPTION_V1": _unsupported(
        "GEN_REPEATED_FORM_DESCRIPTION_V1", "REPEATED_FORM_DESCRIPTION",
        "repeated_form_detector_unavailable"),
    "GEN_COPYBOOK_DIFFERENCE_V1": _unsupported(
        "GEN_COPYBOOK_DIFFERENCE_V1", "COPYBOOK_DIFFERENCE", "copybook_context_unavailable"),
    "GEN_INK_APPEARANCE_FACT_V1": _supported(
        "GEN_INK_APPEARANCE_FACT_V1", "INK_APPEARANCE_FACT",
        ("INK_DARKNESS_CV",), _ink_appearance),
    "GEN_THICKNESS_FACT_V1": _supported(
        "GEN_THICKNESS_FACT_V1", "THICKNESS_FACT",
        ("STROKE_WIDTH_MEAN",), _thickness_fact),
    "GEN_INITIAL_STROKE_DESCRIPTION_V1": _unsupported(
        "GEN_INITIAL_STROKE_DESCRIPTION_V1", "INITIAL_STROKE_DESCRIPTION",
        "glyph_feature_not_implemented"),
    "GEN_TERMINAL_STROKE_DESCRIPTION_V1": _unsupported(
        "GEN_TERMINAL_STROKE_DESCRIPTION_V1", "TERMINAL_STROKE_DESCRIPTION",
        "glyph_feature_not_implemented"),
    "GEN_PPI_FORM_DESCRIPTION_V1": _unsupported(
        "GEN_PPI_FORM_DESCRIPTION_V1", "PPI_FORM_DESCRIPTION", "ppi_context_unavailable"),
    "GEN_SIGNATURE_TEXT_DIFFERENCE_V1": _unsupported(
        "GEN_SIGNATURE_TEXT_DIFFERENCE_V1", "SIGNATURE_TEXT_DIFFERENCE",
        "signature_regions_unavailable"),
    "GEN_SIGNATURE_TEXT_PATTERN_V1": _unsupported(
        "GEN_SIGNATURE_TEXT_PATTERN_V1", "SIGNATURE_TEXT_PATTERN",
        "signature_regions_unavailable"),
    "GEN_GRAPHIC_SIGN_V1": _unsupported(
        "GEN_GRAPHIC_SIGN_V1", "GRAPHIC_SIGN", "graphic_sign_detector_unavailable"),
    "GEN_SUPPORT_GROUP_V1": _unsupported(
        "GEN_SUPPORT_GROUP_V1", "SUPPORT_GROUP", "traditional_runtime_inactive"),
    "GEN_COUNTEREVIDENCE_GROUP_V1": _unsupported(
        "GEN_COUNTEREVIDENCE_GROUP_V1", "COUNTEREVIDENCE_GROUP", "traditional_runtime_inactive"),
    "GEN_LOCAL_ONLY_SIGN_V1": _unsupported(
        "GEN_LOCAL_ONLY_SIGN_V1", "LOCAL_ONLY_SIGN", "graphic_sign_detector_unavailable"),
    "GEN_GRAPHIC_COMBINATION_V1": _unsupported(
        "GEN_GRAPHIC_COMBINATION_V1", "GRAPHIC_COMBINATION", "graphic_sign_detector_unavailable"),
})

DEFAULT_CANDIDATE_PRODUCERS: Mapping[str, CandidateProducer] = MappingProxyType({
    generator_id: disposition.producer
    for generator_id, disposition in GENERATOR_DISPOSITIONS.items()
    if disposition.state == SUPPORTED and disposition.producer is not None
})


__all__ = [
    "Candidate", "CandidateProducer", "DEFAULT_CANDIDATE_PRODUCERS", "GENERATOR_DISPOSITIONS",
    "GeneratorDisposition", "SUPPORTED", "UNSUPPORTED",
]
