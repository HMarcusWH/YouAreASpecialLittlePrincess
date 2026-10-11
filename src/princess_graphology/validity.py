"""Structural measurement dependency gate for qualified-v2 only.

A numerical algorithm returning a value is not proof the source region was
handwriting. Missing values retain canonical IDs, units and method identities.
"""
from __future__ import annotations

from dataclasses import replace

from .measurements import baseline, ink, layout, quality, size, slant, spacing

QUALITY_INPUT_ONLY = frozenset(quality.FEATURE_IDS[:4])
WORD_DEPENDENT = frozenset({"PAGE_WORD_COUNT", "WORD_SPACING_PX",
                            "WORD_SPACING_REL", "WORD_SPACING_CV"})
PAGE_SCOPE_DEPENDENT = frozenset({
    "MARGIN_TOP_REL", "MARGIN_BOTTOM_REL", "MARGIN_LEFT_REL", "MARGIN_RIGHT_REL",
    "MARGIN_LEFT_VARIABILITY", "MARGIN_RIGHT_VARIABILITY", "MARGIN_SYMMETRY",
})
LINE_DEPENDENT = frozenset(layout.FEATURE_IDS + baseline.FEATURE_IDS
                           + spacing.FEATURE_IDS[:3] + ("PAGE_LINE_COUNT", "PAGE_TEXT_AREA_RATIO",
                                                        "IMG_ROTATION_DEG"))
FOREGROUND_DEPENDENT = frozenset(ink.FEATURE_IDS + size.FEATURE_IDS
                                 + slant.FEATURE_IDS
                                 + ("PAGE_INK_AREA_RATIO", "PAGE_COMPONENT_COUNT"))


def qualification_reason(feature_id: str, qualification: dict) -> str | None:
    if feature_id in QUALITY_INPUT_ONLY:
        return None
    if qualification.get("foreground") != "qualified":
        return "foreground_unqualified"
    if feature_id in WORD_DEPENDENT and qualification.get("words") != "qualified":
        return "word_segmentation_unqualified"
    if feature_id in LINE_DEPENDENT and qualification.get("lines") != "qualified":
        return "line_segmentation_unqualified"
    if feature_id in PAGE_SCOPE_DEPENDENT and qualification.get("page") != "qualified":
        return "physical_page_scope_unqualified"
    return None


def gate(measurement, qualification: dict):
    reason = qualification_reason(measurement.feature_id, qualification)
    if reason is None or measurement.raw_value is None:
        return measurement
    return replace(measurement, raw_value=None, normalized_value=None,
                   std_dev=None, confidence=None, confidence_kind="UNCALIBRATED",
                   n_observations=0, source_regions=[], quality_flag="MISSING",
                   missing_reason=reason)
