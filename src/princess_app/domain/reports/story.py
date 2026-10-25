"""Pure /4 Free Dossier section composition from saved canonical facts.

Inactive until the reviewed R1 presentation/2 and six-chapter content
catalogues are installed. The application assembles/persists the immutable
ReportDocument and authorizes evidence separately; this domain module never
reads a source image, creates a report revision or calls any provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..content.presentation import (
    family_nominees,
    presentation_registry,
    select_highlights,
)
from ..content.reading import select_descriptors, select_relations
from .suitability import ReportSuitability, assess_report_suitability
from .template import FACT_SECTIONS

STORY_TEMPLATE_VERSION = "individual-report/4"
STORY_PRESENTATION_VERSION = "presentation/2"
CHAPTER_ORDER = (
    "section.slant", "section.baseline", "section.spacing",
    "section.size", "section.layout", "section.ink",
)
FAMILY_NAMES = {
    "section.slant": "slant",
    "section.baseline": "baseline",
    "section.spacing": "spacing",
    "section.size": "size",
    "section.layout": "layout",
    "section.ink": "ink",
}
PRESENT = frozenset({"READY", "UNCALIBRATED"})


@dataclass(frozen=True)
class ChapterCopy:
    """Opaque approved content IDs, supplied by the versioned R1 compiler."""

    section_id: str
    neutral_content_id: str
    unavailable_content_id: str


@dataclass(frozen=True)
class StoryPolicy:
    """Version-pinned, already-validated server content authority.

    This module cannot validate editorial language itself. The R1 content
    compiler is responsible for source digests, EN/SV closure, and approved
    chapter and relation copy. No web or mobile client may construct it.
    """

    presentation_version: str
    chapters: tuple[ChapterCopy, ...]
    neutral_overview_content_id: str
    unqualified_overview_content_id: str
    relation_registry: Mapping[str, Any]


def _fact_map(facts: object) -> dict[str, Mapping[str, Any]]:
    expected = {feature_id for _, _, ids in FACT_SECTIONS for feature_id in ids}
    if not isinstance(facts, (tuple, list)) or len(facts) != len(expected):
        raise ValueError("story must retain all 64 canonical Free facts")
    by_feature: dict[str, Mapping[str, Any]] = {}
    for row in facts:
        if not isinstance(row, Mapping):
            raise ValueError("invalid story fact")
        feature_id = row.get("feature_id")
        if (not isinstance(feature_id, str) or feature_id not in expected
                or row.get("fact_id") != f"fact.{feature_id}"
                or feature_id in by_feature
                or row.get("availability") not in {"READY", "UNCALIBRATED", "MISSING"}):
            raise ValueError("unknown, repeated or malformed story fact")
        if row["availability"] == "MISSING" and row.get("value") is not None:
            raise ValueError("missing fact cannot have a numeric value")
        by_feature[feature_id] = row
    if set(by_feature) != expected:
        raise ValueError("story Free fact coverage is incomplete")
    return by_feature


def _availability(rows: Sequence[Mapping[str, Any]]) -> str:
    present = [row for row in rows if row["availability"] in PRESENT]
    if not present:
        return "MISSING"
    return "READY" if all(row["availability"] == "READY" for row in present) else "UNCALIBRATED"


def _section(section_id: str, template: str, availability: str,
             fact_ids: Sequence[str], content_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "template": template,
        "availability": availability,
        "fact_ids": list(fact_ids),
        "content_ids": list(content_ids),
        "premium_section_id": None,
    }


def build_neutral_overview(
    facts: Sequence[Mapping[str, Any]], policy: StoryPolicy, suitability: ReportSuitability,
) -> dict[str, Any]:
    """Return an honest fallback, not a fabricated eligible standout."""
    by_feature = _fact_map(facts)
    usable = [
        by_feature[feature_id]["fact_id"]
        for feature_id in ("PAGE_LINE_COUNT", "PAGE_WORD_COUNT")
        if by_feature[feature_id]["availability"] in PRESENT
        and type(by_feature[feature_id]["value"]) in (int, float)
        and by_feature[feature_id]["value"] > 0
    ]
    unqualified = suitability is ReportSuitability.UNQUALIFIED
    return _section(
        "section.highlight.primary", "HIGHLIGHT_PRIMARY",
        "INELIGIBLE" if unqualified else "UNCALIBRATED",
        [] if unqualified else usable,
        [policy.unqualified_overview_content_id if unqualified
         else policy.neutral_overview_content_id],
    )


def build_story_sections(
    report_input: Mapping[str, Any], policy: StoryPolicy,
) -> tuple[dict[str, Any], ...]:
    """Compose a first reveal, technical specimen and six chapters.

    Free sections reuse existing ReportSection shapes; they do not create a
    parallel truth store. The caller appends reference/Premium sections using
    separately resolved authority. This does not enable the /4 writer.
    """
    if not isinstance(report_input, Mapping) or not isinstance(policy, StoryPolicy):
        raise ValueError("invalid /4 story input or policy")
    analysis = report_input.get("analysis")
    versions = analysis.get("versions") if isinstance(analysis, Mapping) else None
    if not isinstance(versions, Mapping) or versions.get("template") != STORY_TEMPLATE_VERSION:
        raise ValueError("story compiler requires an explicit /4 analysis pin")
    if policy.presentation_version != STORY_PRESENTATION_VERSION:
        raise ValueError("story requires reviewed presentation/2")
    if (len(policy.chapters) != len(CHAPTER_ORDER)
            or tuple(ch.section_id for ch in policy.chapters) != CHAPTER_ORDER
            or any(not isinstance(ch, ChapterCopy)
                   or not ch.neutral_content_id or not ch.unavailable_content_id
                   for ch in policy.chapters)
            or not policy.neutral_overview_content_id
            or not policy.unqualified_overview_content_id):
        raise ValueError("incomplete or misordered six-chapter content policy")

    facts = report_input.get("facts")
    by_feature = _fact_map(facts)
    sample_sections = report_input.get("sections", ())
    if not isinstance(sample_sections, (tuple, list)):
        raise ValueError("invalid saved sample state")
    provisional = {"analysis": analysis, "facts": facts, "sections": sample_sections}
    suitability = assess_report_suitability(provisional)
    if suitability is ReportSuitability.UNSUPPORTED_TEMPLATE:
        raise ValueError("unsupported suitability for /4 story")

    registry = presentation_registry(version=policy.presentation_version)
    sections: list[dict[str, Any]] = []
    highlights = () if suitability is ReportSuitability.UNQUALIFIED else select_highlights(
        facts, limit=3, version=policy.presentation_version,
    )
    if highlights:
        by_id = {fact["fact_id"]: fact for fact in facts}
        for index, highlight in enumerate(highlights):
            members = [by_id[fid] for fid in highlight.support_fact_ids]
            sections.append(_section(
                "section.highlight.primary" if index == 0 else f"section.highlight.secondary.{index}",
                "HIGHLIGHT_PRIMARY" if index == 0 else "HIGHLIGHT_SECONDARY",
                _availability(members), highlight.support_fact_ids, [highlight.content_id],
            ))
    else:
        sections.append(build_neutral_overview(facts, policy, suitability))

    specs = {section_id: (template, feature_ids)
             for section_id, template, feature_ids in FACT_SECTIONS}
    sample_template, sample_ids = specs["section.sample"]
    sample_members = [by_feature[fid] for fid in sample_ids]
    sections.append(_section(
        "section.sample", sample_template,
        "INELIGIBLE" if suitability is ReportSuitability.UNQUALIFIED else _availability(sample_members),
        [row["fact_id"] for row in sample_members], [],
    ))

    family_winners = {} if suitability is ReportSuitability.UNQUALIFIED else {
        nominee.family: nominee for nominee in family_nominees(
            facts, version=policy.presentation_version,
        )
    }
    for chapter in policy.chapters:
        template, ids = specs[chapter.section_id]
        members = [by_feature[fid] for fid in ids]
        availability = _availability(members)
        if suitability is ReportSuitability.UNQUALIFIED:
            availability = "INELIGIBLE"
        selected = family_winners.get(FAMILY_NAMES[chapter.section_id])
        content = (selected.content_id if selected is not None and availability != "INELIGIBLE"
                   else chapter.neutral_content_id if availability in PRESENT
                   else chapter.unavailable_content_id)
        sections.append(_section(
            chapter.section_id, template, availability,
            [row["fact_id"] for row in members], [content],
        ))

    if suitability is not ReportSuitability.UNQUALIFIED:
        descriptors = select_descriptors(facts, registry)
        for index, relation in enumerate(select_relations(descriptors, policy.relation_registry)):
            sections.append(_section(
                f"section.connection.{index + 1}", "PATTERN_CONNECTION", "UNCALIBRATED",
                relation.support_fact_ids, [relation.content_id],
            ))
    # Highlights and relations may refer to facts, but the seven technical
    # section buckets own every canonical fact exactly once.
    technical_ids = [
        fid for section in sections
        if section["section_id"] in {"section.sample", *CHAPTER_ORDER}
        for fid in section["fact_ids"]
    ]
    if len(technical_ids) != 64 or len(set(technical_ids)) != 64:
        raise ValueError("story technical sections lost or duplicated a Free fact")
    return tuple(sections)
