"""Private, opt-in structural evidence audit (research evidence-support/5).

A conservative guard against contaminating handwriting aggregates with ruling,
page borders and failed geometric word grouping. It neither recognizes text nor
certifies blank paper. It never deletes source pixels or repairs segmentation.
The production default remains the historical, guard-off measurement pipeline.
"""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

GUARD_POLICY_VERSION = "evidence-support/5"
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


def _distinct_hough_bands(segments, mask: np.ndarray) -> tuple[int | None, str]:
    """Bounded grouping of independently supported physical ink ribbons.

    Only native OpenCV N×4 and N×1×4 *integer* line arrays are accepted.
    Bad provenance, exhausted budgets and unsupported geometric evidence
    are different states. None from OpenCV is a valid, measured zero.
    """
    if segments is None:
        return 0, "checked"
    height, width = mask.shape
    try:
        raw = np.asarray(segments)
    except (TypeError, ValueError):
        return None, "malformed_response"
    if raw.ndim == 2 and raw.shape[1] == 4:
        pass
    elif raw.ndim == 3 and raw.shape[1:] == (1, 4):
        raw = raw[:, 0, :]
    else:
        return None, "malformed_response"
    if raw.dtype.kind not in ("i", "u"):
        return None, "malformed_response"
    if len(raw) > MAX_HOUGH_SEGMENTS:
        return None, "budget_exceeded"
    if (np.any(raw[:, 0] < 0) or np.any(raw[:, 0] >= width)
            or np.any(raw[:, 2] < 0) or np.any(raw[:, 2] >= width)
            or np.any(raw[:, 1] < 0) or np.any(raw[:, 1] >= height)
            or np.any(raw[:, 3] < 0) or np.any(raw[:, 3] >= height)):
        return None, "malformed_response"

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
        return None, "budget_exceeded"
    if not candidates:
        return 0, "checked"

    # Probe vertical connected ink at and beside each fixed sample column.
    # A thin vertical graph-paper connector must not make two separate
    # horizontal strokes look like one 70-pixel-thick ink ribbon.
    columns = np.unique(np.rint(np.linspace(
        0, width - 1, BAND_SAMPLE_COLUMNS,
    )).astype(int))
    offsets = (-7, 0, 7)
    probe_columns = sorted(set(
        max(0, min(width - 1, int(x + shift)))
        for x in columns for shift in offsets
    ))
    column_runs = {}
    for x in probe_columns:
        rows = np.flatnonzero(mask[:, x])
        labels = np.zeros(height, dtype=np.int32)
        if rows.size:
            labels[rows] = np.cumsum(np.r_[True, np.diff(rows) > 1])
        column_runs[x] = labels, np.bincount(labels)[1:]

    def ink_run(x, y):
        labels, lengths = column_runs[x]
        if not 0 <= y < height:
            return 0, 0
        run = int(labels[y])
        if not run:
            nearby = labels[max(0, y - 2):min(height, y + 3)]
            found = np.flatnonzero(nearby)
            run = int(nearby[found[0]]) if found.size else 0
        return run, int(lengths[run - 1]) if run else 0

    signatures = []
    for intercept, slope, left, right in candidates:
        signature = []
        for x in columns:
            if x < left or x > right:
                signature.append((0, 0., 0))
                continue
            y = int(round(intercept + slope * x))
            run, _ = ink_run(int(x), y)
            nearby_thicknesses = []
            for shift in offsets:
                shifted = max(0, min(width - 1, int(x + shift)))
                sample_y = int(round(intercept + slope * shifted))
                _, thickness = ink_run(shifted, sample_y)
                if thickness:
                    nearby_thicknesses.append(thickness)
            thickness = (float(np.median(nearby_thicknesses))
                         if nearby_thicknesses else 0.)
            signature.append((run, thickness, y))
        if sum(bool(value[0]) for value in signature) < 3:
            return None, "insufficient_support"
        signatures.append(tuple(signature))

    def same_ribbon(i, j):
        first, second = candidates[i], candidates[j]
        overlap = max(0, min(first[3], second[3]) - max(first[2], second[2]))
        if overlap < 0.45 * min(first[3] - first[2], second[3] - second[2]):
            return False
        shared = matching = 0
        for left_support, right_support in zip(signatures[i], signatures[j]):
            if left_support[0] and right_support[0]:
                shared += 1
                # Ink connectivity is insufficient when caused by a narrow
                # perpendicular bridge. Require geometrical separation to be
                # compatible with the robust local ink-ribbon thickness too.
                if (left_support[0] == right_support[0]
                        and abs(left_support[2] - right_support[2])
                        <= max(3., 1.2 * max(left_support[1], right_support[1]))):
                    matching += 1
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

    # When Hough reports strongly incompatible directions but the foreground
    # merges them into a single connected ribbon, the physical band count is
    # not identifiable. Reject that contradictory evidence instead of
    # certifying one line. Not every visually merged crossing is separable.
    if len(groups) == 1:
        slopes = [candidate[1] for candidate in candidates]
        if (min(slopes) <= -0.018 and max(slopes) >= 0.018
                and max(slopes) - min(slopes) >= 0.075):
            return None, "insufficient_support"
    return len(groups), "checked"



def _supplementary_hough_bands(mask: np.ndarray) -> tuple[int | None, str]:
    """Bounded thin-line evidence when probabilistic Hough has ≤1 band.

    Standard-Hough peaks are *only proposals*. Verify sustained observed ink
    along each near-horizontal candidate and pass supported lines through the
    SAME physical-band deduplication; accumulator peaks are never counts.
    """
    height, width = mask.shape
    peaks = cv2.HoughLines(
        mask, rho=1, theta=np.pi / 720,
        threshold=max(32, int(0.27 * width)),
        min_theta=np.pi / 2 - 0.15, max_theta=np.pi / 2 + 0.15,
    )
    if peaks is None:
        return 0, "checked"
    raw = np.asarray(peaks)
    if raw.ndim == 3 and raw.shape[1:] == (1, 2):
        raw = raw[:, 0, :]
    elif raw.ndim != 2 or raw.shape[1] != 2:
        return None, "malformed_response"
    if raw.dtype.kind != "f" or not np.isfinite(raw).all():
        return None, "malformed_response"
    if len(raw) > MAX_HOUGH_SEGMENTS:
        return None, "budget_exceeded"

    samples_x = np.arange(0, width, max(1, width // 96))
    supported = []
    for rho, theta in raw:
        sine = float(np.sin(theta))
        cosine = float(np.cos(theta))
        if abs(sine) < 0.75:
            continue
        start_y = float(rho) / sine
        end_y = (float(rho) - (width - 1) * cosine) / sine
        if not (0 <= start_y < height and 0 <= end_y < height):
            continue
        predicted_y = np.rint((float(rho) - samples_x * cosine) / sine).astype(int)
        has_ink = np.zeros(len(samples_x), dtype=bool)
        for offset in (-1, 0, 1):
            rows = np.clip(predicted_y + offset, 0, height - 1)
            has_ink |= mask[rows, samples_x] > 0
        if np.count_nonzero(has_ink) < 0.78 * len(samples_x):
            continue
        # In-canvas floating intercepts may round to height at the border.
        # Their source evidence is valid; clamp before integer endpoint audit.
        supported.append((0, max(0, min(height - 1, round(start_y))),
                          width - 1, max(0, min(height - 1, round(end_y)))))
        if len(supported) > MAX_RULING_CANDIDATES:
            return None, "budget_exceeded"
    if not supported:
        return 0, "checked"
    return _distinct_hough_bands(np.asarray(supported, dtype=np.int32), mask)

def foreground_ruling_counts(mask: np.ndarray) -> dict:
    """Bounded visual evidence with explicit unperformed/unavailable states."""
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
    segments = cv2.HoughLinesP(
        binary, rho=1, theta=np.pi / 720,
        threshold=max(20, int(0.16 * reduced_width)),
        minLineLength=max(25, int(0.67 * reduced_width)),
        maxLineGap=max(3, int(0.03 * reduced_width)),
    )
    angled, status = _distinct_hough_bands(segments, binary)
    if status == "checked" and angled <= 1:
        # A full-width thick stroke already confirmed by the primary pass
        # produces many duplicate standard-Hough peaks. Inspect a secondary
        # source only for absent/very sparse primary linear evidence.
        stroke_equivalent = np.count_nonzero(binary) / reduced_width
        if angled == 0 or stroke_equivalent <= 12.0:
            second, second_status = _supplementary_hough_bands(binary)
            if second_status != "checked":
                angled, status = None, second_status
            elif second > angled:
                angled = second
    return {"dense_horizontal_bands": bands, "near_horizontal_long_bands": angled,
            "hough_status": status, "audit_limit_reached": status == "budget_exceeded"}


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

def assess_support(ctx, word_trace=None, reattachment_trace=None, *,
                   require_ruling_audit=True) -> dict:
    """Return a bounded audit and an abstention reason, never accuracy claims.

    Every full abstention withholds the 60 handwriting-dependent aggregates.
    Decisions operate on already-observed pixels and existing segmentation.
    False negatives and conservative refusals require empirical evaluation.
    """
    if type(require_ruling_audit) is not bool:
        raise ValueError("ruling audit requirement must be boolean")
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
    if (reason is None and ((ruling["dense_horizontal_bands"] or 0) >= 2
                           or (ruling["near_horizontal_long_bands"] or 0) >= 2)):
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

    # Compatibility-only callers may supply geometry without a pixel mask.
    # The real GraphologyEngine *always* requires a qualified pixel audit,
    # including explicit refusal of malformed, skipped and unsupported Hough.
    if reason is None and require_ruling_audit:
        status = ruling["hough_status"]
        if status == "budget_exceeded":
            reason = "residual_ruling_audit_budget"
        elif status == "malformed_response":
            reason = "residual_ruling_audit_malformed"
        elif status == "insufficient_support":
            reason = "residual_ruling_audit_insufficient_support"
        elif status != "checked":
            reason = "residual_ruling_audit_unavailable"

    return {
        "policy": GUARD_POLICY_VERSION,
        "status": "unqualified" if reason else "no_abstention_not_calibrated",
        "reason": reason,
        "ruling": ruling,
        "word_stages": _word_audit(ctx, word_trace, reattachment_trace),
    }


def support_warning(ctx) -> str | None:
    """Compatibility helper for callers that only need the abstention code."""
    # This historical geometry helper is not the authoritative engine gate.
    # Missing optional masks never become invented negative Hough findings.
    return assess_support(
        ctx, require_ruling_audit=getattr(ctx, "mask", None) is not None,
    )["reason"]


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
