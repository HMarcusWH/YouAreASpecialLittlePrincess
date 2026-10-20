"""Private, opt-in structural evidence audit (research evidence-support/2).

A conservative guard against contaminating handwriting aggregates with ruling,
page borders and failed geometric word grouping. It neither recognizes text nor
certifies blank paper. It never deletes source pixels or repairs segmentation.
The production default remains the historical, guard-off measurement pipeline.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

GUARD_POLICY_VERSION = "evidence-support/2"
WORD_AUDIT_VERSION = "word-stage-audit/1"
IMAGE_DIMENSION_FACTS = frozenset((
    "IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO",
))
# Only pre-existing bounded counter names may leave a private research worker.
WORD_COUNTERS = (
    "raw_contours", "raw_proposals", "after_geometry_filter",
    "reject_low_area_or_extent", "reject_small_relative_proposal",
    "reject_oversized_proposal", "reject_no_unique_line",
    "reject_ambiguous_lines", "reject_empty_line_intersection",
    "reject_no_ink_in_crop", "reject_exact_duplicate", "reject_nested_duplicate",
    "detector_accepted_groups", "gap_candidates",
    "qualified_gap_candidates", "accepted_geometry_groups",
)
MAX_TRACE_COUNT = 1_000_000


def _word_audit(ctx, trace) -> dict:
    """Unavailable proposal stages are None, never an asserted zero.

    Only fixed count names are allowed; no boxes, coordinates, pixels, raw
    transcription, provider response, specimen identifier or arbitrary trace.
    """
    trace = trace if isinstance(trace, dict) else {}
    counts = {}
    for name in WORD_COUNTERS:
        value = trace.get(name)
        counts[name] = value if type(value) is int and 0 <= value <= MAX_TRACE_COUNT else None
    lines = bool(ctx.lines)
    status = ("not_invoked" if not lines else
              "accepted_groups" if ctx.words else "no_accepted_groups")
    return {
        "version": WORD_AUDIT_VERSION,
        "status": status,
        "accepted_geometric_groups": min(len(ctx.words), MAX_TRACE_COUNT),
        "counts": counts,
    }


def _ruling_audit(ctx) -> dict:
    """Independently inspect *retained* foreground, not detector line labels.

    Long continuous horizontal ink bands can be printed ruling even when the
    word detector returns spurious groups. This does not try to reconstruct
    pen pixels at crossings, and does not crop near-page handwriting.
    """
    h, w = ctx.height, ctx.width
    suspicious = sum(box.width >= 0.83 * w
                     and box.height <= max(12, 0.10 * h) for box in ctx.lines)
    compact = sum(
        5 <= box.height <= max(14, 0.18 * h)
        and 2 <= box.width <= max(12, 0.22 * w)
        and 0.1 <= box.width / box.height <= 6.0
        for box in ctx.components
    )
    mask = getattr(ctx, "mask", None)
    bands = 0
    # Synthetic unit contexts may have no mask; their pre-existing geometry
    # guard still works, but the independent foreground audit is unavailable.
    if (isinstance(mask, np.ndarray) and mask.ndim == 2
            and mask.shape == (h, w) and w >= 64):
        row_counts = np.count_nonzero(mask, axis=1)
        dense = np.flatnonzero(row_counts >= 0.70 * w)
        if dense.size:
            bands = 1 + int(np.count_nonzero(np.diff(dense) > 1))
    return {
        "dense_horizontal_bands": bands,
        "page_spanning_line_boxes": suspicious,
        "compact_component_boxes": compact,
    }


def assess_support(ctx, word_trace=None) -> dict:
    """Return a bounded audit and an abstention reason, never accuracy claims.

    Every full abstention withholds the 60 handwriting-dependent aggregates.
    Decisions operate on already-observed pixels and existing segmentation.
    False negatives and conservative refusals require empirical evaluation.
    """
    lines, words = ctx.lines, ctx.words
    h, w = ctx.height, ctx.width
    ruling = _ruling_audit(ctx)
    reason = None

    if len(lines) == 1:
        box = lines[0]
        if (box.width / w >= 0.92 and box.height / h >= 0.75
                and len(ctx.components) <= 8 and len(words) <= 5):
            reason = "page_spanning_nontext_artifact"

    if reason is None and len(lines) >= 4 and not words:
        flat = sum(box.height <= max(4, min(9, h // 180))
                   and box.width / w >= 0.93 for box in lines)
        if flat >= max(4, int(0.9 * len(lines))):
            reason = "dominant_thin_page_ruling"

    # V2: two or more wide horizontal foreground bands are suspect even when
    # the word detector admitted apparent groups. A page border can survive
    # periodic grid removal and then contaminate unrelated baseline/layout.
    if reason is None and ruling["dense_horizontal_bands"] >= 2:
        reason = "residual_page_ruling"

    # Line boxes and accepted words are *not* independent handwriting proof.
    # Reject repeated page-span candidates only if compact glyph-like support
    # is scarce, rather than treating full-width legitimate writing as ruling.
    if (reason is None and ruling["page_spanning_line_boxes"] >= 2
            and ruling["compact_component_boxes"] < max(5, 2 * len(lines))
            and len(words) <= 1):
        reason = "residual_page_ruling"

    if (reason is None and min(ctx.original_width, ctx.original_height) < 720
            and len(lines) >= 2 and ctx.x_height_px is None
            and len(ctx.components) < max(12, 3 * len(lines))
            and len(words) < max(8, 3 * len(lines))):
        reason = "low_resolution_structure_collapsed"

    # There is no defensible physical-page blank classification in this guard.
    # A failed word detector with foreground is NOT evidence of zero words.
    if reason is None and not lines:
        reason = "no_verified_text_lines"
    if reason is None and not words:
        reason = "word_groups_unqualified"

    return {
        "policy": GUARD_POLICY_VERSION,
        "status": "unqualified" if reason else "no_abstention_not_calibrated",
        "reason": reason,
        "ruling": ruling,
        "word_stages": _word_audit(ctx, word_trace),
    }


def support_warning(ctx) -> str | None:
    """Compatibility helper for callers that only need the abstention code."""
    return assess_support(ctx)["reason"]


def withhold_unqualified(measurement, reason: str):
    """Keep canonical identity/method/units; discard unsupported observations."""
    if measurement.feature_id in IMAGE_DIMENSION_FACTS:
        return measurement
    # Processing lineage is retained, per-feature numeric estimates are not.
    source = measurement.method_metadata
    safe = {name: source[name] for name in
            ("processing_profile", "grid_preprocessing", "quality_policy")
            if name in source}
    if "qualified_support" in source:
        safe["qualified_support"] = False
    return replace(measurement,
                   raw_value=None, normalized_value=None, std_dev=None,
                   confidence=None, confidence_kind="UNCALIBRATED",
                   n_observations=0, source_regions=[], quality_flag="MISSING",
                   missing_reason=reason,
                   method_metadata={**safe, "evidence_support_policy": GUARD_POLICY_VERSION,
                                    "evidence_support_status": "unqualified"})
