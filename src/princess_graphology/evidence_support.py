"""Private, opt-in structural evidence audit (research evidence-support/3).

A conservative guard against contaminating handwriting aggregates with ruling,
page borders and failed geometric word grouping. It neither recognizes text nor
certifies blank paper. It never deletes source pixels or repairs segmentation.
The production default remains the historical, guard-off measurement pipeline.
"""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

GUARD_POLICY_VERSION = "evidence-support/3"
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


def _safe_stage_counts(trace) -> dict:
    trace = trace if isinstance(trace, dict) else {}
    counts = {}
    for name in WORD_COUNTERS:
        value = trace.get(name)
        counts[name] = value if type(value) is int and 0 <= value <= MAX_TRACE_COUNT else None
    return counts


def _word_audit(ctx, trace, attachment_trace=None) -> dict:
    """Do not conflate an unrun detector with measured empty proposals.

    WordDetector/qualified_words and the later canonical word-box attachment
    are separate stages, and their rejection counters must not overwrite one
    another. Unknown counters always remain JSON null, never invented zero.
    """
    invoked = bool(ctx.lines)
    counts = _safe_stage_counts(trace) if invoked else _safe_stage_counts(None)
    # Keep final attachment diagnostics ephemeral. Only fixed, bounded
    # counters from this allowlist may enter result metadata.
    attached = invoked and isinstance(attachment_trace, dict)
    return {
        "version": WORD_AUDIT_VERSION,
        "status": ("not_invoked" if not invoked else
                   "accepted_groups" if ctx.words else "no_accepted_groups"),
        "accepted_geometric_groups": min(len(ctx.words), MAX_TRACE_COUNT) if invoked else None,
        "counts": counts,
        "reattachment": {
            "status": "not_invoked" if not invoked else "performed" if attached else "unavailable",
            "counts": _safe_stage_counts(attachment_trace if attached else None),
        },
    }

MAX_HOUGH_SEGMENTS = 8192
# Whole-group support matching is quadratic: exceeding this fixed bound
# means the research audit is unavailable, never a partial negative finding.
MAX_RULING_CANDIDATES = 512
BAND_SAMPLE_COLUMNS = 17


def _distinct_hough_bands(segments, mask: np.ndarray) -> tuple[int | None, bool]:
    """Group actual ink ribbons, not adjacent Hough fragments.

    Detections of a thick stroke share vertical foreground runs over their
    horizontal overlap; shallow crossing lines diverge outside the crossing.
    Complete-link group compatibility prevents a bridge fragment merging
    two otherwise independent physical strokes.
    """
    if segments is None:
        return 0, False
    height, width = mask.shape
    try:
        raw = np.asarray(segments).reshape(-1, 4)
    except (ValueError, TypeError):
        return None, True
    if len(raw) > MAX_HOUGH_SEGMENTS:
        return None, True

    candidates = []
    for x1, y1, x2, y2 in raw:
        dx = int(x2) - int(x1)
        if abs(dx) < 0.67 * width:
            continue
        slope = (int(y2) - int(y1)) / dx
        if abs(slope) > 0.15:
            continue
        left, right = sorted((int(x1), int(x2)))
        if right <= left:
            continue
        intercept = int(y1) - slope * int(x1)
        candidates.append((intercept, slope, left, right))
    if len(candidates) > MAX_RULING_CANDIDATES:
        return None, True
    if not candidates:
        return 0, False

    columns = np.unique(np.rint(np.linspace(0, width - 1, BAND_SAMPLE_COLUMNS)).astype(int))
    column_labels = []
    for x in columns:
        rows = np.flatnonzero(mask[:, x])
        labels = np.zeros(height, dtype=np.int32)
        if rows.size:
            labels[rows] = np.cumsum(np.r_[True, np.diff(rows) > 1])
        column_labels.append(labels)

    signatures = []
    for intercept, slope, left, right in candidates:
        signature = []
        for x, labels in zip(columns, column_labels):
            if x < left or x > right:
                signature.append(0)
                continue
            y = int(round(intercept + slope * x))
            if y < 0 or y >= height:
                signature.append(0)
                continue
            run = int(labels[y])
            if not run:
                adjacent = labels[max(0, y - 1):min(height, y + 2)]
                located = np.flatnonzero(adjacent)
                run = int(adjacent[located[0]]) if located.size else 0
            signature.append(run)
        if sum(bool(run) for run in signature) < 3:
            return None, True
        signatures.append(tuple(signature))

    def same_ribbon(i, j):
        first, second = candidates[i], candidates[j]
        overlap = max(0, min(first[3], second[3]) - max(first[2], second[2]))
        if overlap < 0.45 * min(first[3] - first[2], second[3] - second[2]):
            return False
        shared = matching = 0
        for left_run, right_run in zip(signatures[i], signatures[j]):
            if left_run and right_run:
                shared += 1
                matching += left_run == right_run
        return shared >= 3 and matching >= 3 and 4 * matching >= 3 * shared

    ordered = sorted(range(len(candidates)), key=lambda i: (*candidates[i], i))
    groups = []
    for i in ordered:
        for group in groups:
            if all(same_ribbon(i, member) for member in group):
                group.append(i)
                break
        else:
            groups.append([i])
    return len(groups), False


def foreground_ruling_counts(mask: np.ndarray) -> dict:
    """Bounded visual evidence; an unperformed Hough stage is never zero."""
    height, width = mask.shape
    if width < 64:
        return {"dense_horizontal_bands": None, "near_horizontal_long_bands": None,
                "hough_status": "skipped_small_canvas", "audit_limit_reached": False}

    dense = np.flatnonzero(np.count_nonzero(mask, axis=1) >= 0.70 * width)
    bands = (1 + int(np.count_nonzero(np.diff(dense) > 1))) if dense.size else 0
    if np.count_nonzero(mask) > 0.35 * mask.size:
        return {"dense_horizontal_bands": bands, "near_horizontal_long_bands": None,
                "hough_status": "skipped_dense_foreground", "audit_limit_reached": False}

    scale = min(1.0, 1024.0 / max(height, width))
    reduced_width = max(1, round(width * scale))
    reduced_height = max(1, round(height * scale))
    small = (cv2.resize(mask, (reduced_width, reduced_height),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else mask)
    binary = (small > 0).astype(np.uint8) * 255
    # Quarter-degree voting retains shallow, thin paper rules which the
    # previous one-degree Hough step could miss on synthetic inputs.
    segments = cv2.HoughLinesP(
        binary, rho=1, theta=np.pi / 720,
        threshold=max(20, int(0.16 * reduced_width)),
        minLineLength=max(25, int(0.67 * reduced_width)),
        maxLineGap=max(3, int(0.03 * reduced_width)),
    )
    angled, exceeded = _distinct_hough_bands(segments, binary)
    return {"dense_horizontal_bands": bands, "near_horizontal_long_bands": angled,
            "hough_status": "budget_exceeded" if exceeded else "checked",
            "audit_limit_reached": exceeded}


def _ruling_audit(ctx) -> dict:
    """Read post-selection foreground, explicitly separating preselection."""
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
    signals = (foreground_ruling_counts(mask)
               if isinstance(mask, np.ndarray) and mask.ndim == 2
               and mask.shape == (h, w) else
               {"dense_horizontal_bands": None, "near_horizontal_long_bands": None,
                "hough_status": "unavailable_foreground",
                "audit_limit_reached": False})
    metadata = getattr(ctx, "metadata", {})
    profile = metadata.get("segmentation_profile") if isinstance(metadata, dict) else None
    preselection = metadata.get("pre_line_ruling_audit") if isinstance(metadata, dict) else None
    return {
        **signals,
        "foreground_stage": ("qualified_line_selected" if profile == "qualified-v2"
                             else "denoised_foreground"),
        "pre_line_selection": preselection,
        "page_spanning_line_boxes": suspicious,
        "compact_component_boxes": compact,
    }

def assess_support(ctx, word_trace=None, reattachment_trace=None) -> dict:
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
    if reason is None and ruling["audit_limit_reached"]:
        reason = "residual_ruling_audit_budget"
    if (reason is None and ((ruling["dense_horizontal_bands"] or 0) >= 2
                           or (ruling["near_horizontal_long_bands"] or 0) >= 2)):
        reason = "residual_page_ruling"
    if reason is None and ruling["hough_status"] != "checked":
        reason = "residual_ruling_audit_unavailable"

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
        "word_stages": _word_audit(ctx, word_trace, reattachment_trace),
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
