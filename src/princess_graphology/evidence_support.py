"""Opt-in synthetic/research structural evidence guard (prototype evidence-support/1).

This guard identifies conspicuously non-glyph page ruling and collapsed low-res
segmentation. It does NOT recognize handwriting or certify a page to be blank.
On activation it withholds handwriting-dependent numerical claims rather than
silently asserting zero. Conservative false negatives are expected.
"""
from __future__ import annotations

from dataclasses import replace

GUARD_POLICY_VERSION = "evidence-support/1"
IMAGE_DIMENSION_FACTS = frozenset((
    "IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO",
))


def support_warning(ctx) -> str | None:
    """Return an explicit evidence *abstention* reason or None.

    All checks use existing deterministic primitives. No OCR, models or
    assumptions about which physical pixels were made by a human.
    """
    lines = ctx.lines
    if not lines:
        return None
    height, width = ctx.height, ctx.width
    # A page-sized connected contour is not defensible evidence of a text line.
    if len(lines) == 1:
        box = lines[0]
        if (box.width / width >= 0.92 and box.height / height >= 0.75
                and len(ctx.components) <= 8 and len(ctx.words) <= 5):
            return "page_spanning_nontext_artifact"
    # Printed rows spanning the entire canvas are not line-level handwriting.
    # Preserve writing on ruled paper: glyph strokes create tall, shorter boxes.
    if len(lines) >= 4 and not ctx.words:
        flat = sum(box.height <= max(4, min(9, height // 180))
                   and box.width / width >= 0.93 for box in lines)
        if flat >= max(4, int(0.9 * len(lines))):
            return "dominant_thin_page_ruling"
    # Only flag *compound* evidence collapse in very small captures. A short
    # legitimate note is not rejected merely for having few lines or components.
    if (min(ctx.original_width, ctx.original_height) < 720
            and len(lines) >= 2
            and ctx.x_height_px is None
            and len(ctx.components) < max(12, 3 * len(lines))
            and len(ctx.words) < max(8, 3 * len(lines))):
        return "low_resolution_structure_collapsed"
    return None


def withhold_unqualified(measurement, reason: str):
    """Keep feature identity/unit/method; remove unsupported numeric evidence."""
    if measurement.feature_id in IMAGE_DIMENSION_FACTS:
        return measurement
    return replace(measurement,
                   raw_value=None, normalized_value=None, std_dev=None,
                   confidence=None, confidence_kind="UNCALIBRATED",
                   n_observations=0, source_regions=[], quality_flag="MISSING",
                   missing_reason=reason,
                   method_metadata={"evidence_support_policy": GUARD_POLICY_VERSION,
                                    "evidence_support_status": "unqualified"})
