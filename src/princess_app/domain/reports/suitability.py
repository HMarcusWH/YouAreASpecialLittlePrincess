"""Version-aware, read-only specimen suitability for the new report reading.

This is an operational content precondition, not a calibration statement or
payment permission. It does not enable report/4, purchase, model execution,
asset retention, or report mutation. Historical display is not changed.
"""
from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Mapping

from .template import (
    BASE_TEMPLATE_VERSION,
    EVIDENCE_SUPPORT_TEMPLATE_VERSION,
    HIGHLIGHT_TEMPLATE_VERSION,
)

# Future /4 readers may inspect suitability before the /4 writer is enabled.
# Historical template acceptance remains exactly as in template.py.
STORY_TEMPLATE_VERSION = "individual-report/4"
SUPPORT_ASSESSMENT_TEMPLATES = frozenset({
    BASE_TEMPLATE_VERSION,
    HIGHLIGHT_TEMPLATE_VERSION,
    EVIDENCE_SUPPORT_TEMPLATE_VERSION,
    STORY_TEMPLATE_VERSION,
})
PRESENT_FACT_STATES = frozenset({"READY", "UNCALIBRATED"})


class ReportSuitability(str, Enum):
    UNSUPPORTED_TEMPLATE = "UNSUPPORTED_TEMPLATE"
    UNQUALIFIED = "UNQUALIFIED"
    PARTIAL = "PARTIAL"
    SUPPORTED = "SUPPORTED"


def _source(report: object) -> Mapping[str, Any] | None:
    if isinstance(report, Mapping):
        return report
    # ValidatedDocument.to_dict() is a read-only snapshot copy, never a write.
    to_dict = getattr(report, "to_dict", None)
    if not callable(to_dict):
        return None
    document = to_dict()
    return document if isinstance(document, Mapping) else None


def _positive_fact(facts: object, feature_id: str) -> bool:
    """Accept only one present, finite, positive canonical numeric fact."""
    if not isinstance(facts, (tuple, list)):
        return False
    matches = [row for row in facts if isinstance(row, Mapping)
               and row.get("feature_id") == feature_id]
    if len(matches) != 1:
        return False
    fact = matches[0]
    value = fact.get("value")
    return (fact.get("availability") in PRESENT_FACT_STATES
            and type(value) in (int, float) and isfinite(value) and value > 0)


def assess_report_suitability(report: object) -> ReportSuitability:
    """Inspect an already saved report without normalizing or inferring facts.

    Check order is intentional: unknown template, explicit saved ineligibility,
    absent/nonpositive line count, then absent/nonpositive word count.
    A SUPPORTED result only means the specimen passes this mechanical gate;
    provider, evidence, consent, permissions, entitlement and credit gates are
    independent and remain mandatory before any new Premium job.
    """
    source = _source(report)
    if source is None:
        return ReportSuitability.UNSUPPORTED_TEMPLATE
    analysis = source.get("analysis")
    versions = analysis.get("versions") if isinstance(analysis, Mapping) else None
    template = versions.get("template") if isinstance(versions, Mapping) else None
    if template not in SUPPORT_ASSESSMENT_TEMPLATES:
        return ReportSuitability.UNSUPPORTED_TEMPLATE

    sections = source.get("sections")
    if not isinstance(sections, (list, tuple)):
        return ReportSuitability.UNQUALIFIED
    sample_sections = [section for section in sections if isinstance(section, Mapping)
                       and section.get("section_id") == "section.sample"]
    if len(sample_sections) > 1 or any(
        section.get("availability") == "INELIGIBLE" for section in sample_sections
    ):
        return ReportSuitability.UNQUALIFIED

    facts = source.get("facts")
    if not _positive_fact(facts, "PAGE_LINE_COUNT"):
        return ReportSuitability.UNQUALIFIED
    if not _positive_fact(facts, "PAGE_WORD_COUNT"):
        return ReportSuitability.PARTIAL
    return ReportSuitability.SUPPORTED


def assess_sample_support(report: object) -> ReportSuitability:
    """Canonical alias for content-side consumers of suitability."""
    return assess_report_suitability(report)


def premium_sample_eligible(report: object) -> bool:
    """This one mechanical precondition only; not an offer or authorization."""
    return assess_report_suitability(report) is ReportSuitability.SUPPORTED
