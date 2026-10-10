"""Shared, read-only image primitives; never identify a component as a letter."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import cv2
import numpy as np

from .models import Box
from .preprocessing.binarize import binarize
from .preprocessing.denoise import denoise
from .preprocessing.geometry import deskew, estimate_skew
from .preprocessing.grid import GRID_PROFILE, GridQualityError, require_qualified, separate_grid
from .segmentation import attach_words, detect_words, filter_word_proposals, segment_lines


def estimate_x_height(components, indices):
    """Dominant relative-height cluster. Return missing for sparse/ambiguous modes.

    Geometry cannot certify lowercase membership. This is an experimental
    normalizer, particularly unreliable for all-capital or joined cursive text.
    """
    if len(indices) < 6:
        return None, (), 'fewer_than_six_eligible_components'
    heights = np.asarray([components[i].height for i in indices], dtype=float)
    order = np.argsort(heights, kind='stable')
    ordered = heights[order]
    low = np.searchsorted(ordered, ordered / 1.15, side='left')
    high = np.searchsorted(ordered, ordered * 1.15, side='right')
    counts = high - low
    best = int(np.argmax(counts))
    left, right = int(low[best]), int(high[best])
    if counts[best] < 6 or counts[best] < 0.5 * len(indices):
        return None, (), 'no_dominant_component_height'
    disjoint = (high <= left) | (low >= right)
    if np.any(disjoint & (counts >= 0.8 * counts[best])):
        return None, (), 'ambiguous_component_height_modes'
    members = sorted(int(i) for i in order[left:right])
    return float(np.median(heights[members])), tuple(indices[i] for i in members), None



@dataclass(frozen=True)
class MeasurementContext:
    gray: np.ndarray
    mask: np.ndarray
    labels: np.ndarray
    lines: tuple[Box, ...]
    words: tuple[Box, ...]
    word_lines: tuple[int, ...]
    components: tuple[Box, ...]
    glyph_indices: tuple[int, ...]
    x_height_px: float | None
    x_height_indices: tuple[int, ...]
    x_height_missing_reason: str | None
    original_width: int
    original_height: int
    rotation_deg: float | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if type(self.original_width) is not int or type(self.original_height) is not int:
            raise ValueError('original dimensions must be integers')
        if min(self.original_width, self.original_height) <= 0:
            raise ValueError('original dimensions must be positive')
        if self.x_height_px is not None and (
            type(self.x_height_px) not in (int, float) or not math.isfinite(self.x_height_px)
            or self.x_height_px <= 0
        ):
            raise ValueError('x-height must be finite and positive or missing')
        if self.rotation_deg is not None and (
            type(self.rotation_deg) not in (int, float) or not math.isfinite(self.rotation_deg)
        ):
            raise ValueError('rotation must be finite or missing')

    @property
    def width(self):
        return int(self.mask.shape[1])

    @property
    def height(self):
        return int(self.mask.shape[0])

    @property
    def text_bounds(self):
        if not self.lines:
            return None
        x, y = min(b.x for b in self.lines), min(b.y for b in self.lines)
        return Box(x, y, max(b.x2 for b in self.lines) - x, max(b.y2 for b in self.lines) - y)

    @property
    def median_glyph_height(self):
        return float(np.median([self.components[i].height for i in self.glyph_indices])) if self.glyph_indices else None

    @property
    def median_glyph_width(self):
        return float(np.median([self.components[i].width for i in self.glyph_indices])) if self.glyph_indices else None


def build_measurement_context(gray, mask, *, lines=(), words=(), original_width=None,
                              original_height=None, rotation_deg=None, metadata=None, word_trace=None):
    if gray.ndim != 2 or not gray.size or gray.dtype != np.uint8 or mask.shape != gray.shape:
        raise ValueError('gray and mask must have the same nonempty 2-D shape; gray must be uint8')
    if not np.isin(mask, (0, 1, 255)).all():
        raise ValueError('mask must be binary')
    gray = gray.copy()
    mask = (mask > 0).astype(np.uint8) * 255
    lines = tuple(sorted(lines, key=lambda b: (b.y, b.x)))
    for box in (*lines, *words):
        if box.x2 > gray.shape[1] or box.y2 > gray.shape[0]:
            raise ValueError('segmentation box outside image')
    words, word_lines = attach_words(words, lines, mask, diagnostics=word_trace)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components = tuple(Box(*(int(v) for v in row[:4])) for row in stats[1:])
    min_height = max(3.0, 0.2 * float(np.median([b.height for b in lines]))) if lines else 3.0
    eligible = tuple(i for i, b in enumerate(components)
                     if b.height >= min_height and 0.12 <= b.width / b.height <= 2.5
                     and stats[i + 1, cv2.CC_STAT_AREA] >= 5
                     and b.x > 0 and b.y > 0 and b.x2 < gray.shape[1] and b.y2 < gray.shape[0])
    x_height, inliers, reason = estimate_x_height(components, eligible)
    for array in (gray, mask, labels):
        array.flags.writeable = False
    return MeasurementContext(gray, mask, labels, lines, words, word_lines, components, eligible,
                              x_height, inliers, reason,
                              original_width if original_width is not None else int(gray.shape[1]),
                              original_height if original_height is not None else int(gray.shape[0]),
                              rotation_deg, dict(metadata or {}))


def prepare_context(image, *, max_dimension=2200, deskew_enabled=True, grid_profile='grid-v1',
                    word_trace=None):
    """Aligned color/rule detection with one authoritative handwriting mask.

    Legacy reproduces the pre-grid measurements. grid-v1 conservatively
    suppresses separable printed ruling in both line and word detection.
    """
    if grid_profile not in ('legacy', GRID_PROFILE):
        raise ValueError('unknown grid preprocessing profile')
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or not image.size:
        raise ValueError('image must be a nonempty uint8 NumPy array')
    color = None
    if image.ndim == 2:
        gray = image.copy()
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        color = image[:, :, :3].copy()
        if image.shape[2] == 4:
            alpha = image[:, :, 3:4].astype(float) / 255
            color = np.rint(color * alpha + 255 * (1 - alpha)).astype(np.uint8)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError('expected grayscale, BGR, or BGRA image')
    original_h, original_w = gray.shape
    scale = min(1.0, max_dimension / max(gray.shape))
    target = max(1, round(original_w * scale)), max(1, round(original_h * scale))
    if target != (original_w, original_h):
        gray = cv2.resize(gray, target, interpolation=cv2.INTER_AREA)
        if color is not None:
            color = cv2.resize(color, target, interpolation=cv2.INTER_AREA)
    h, w = gray.shape
    correction, rotation = 0.0, None
    skew_method = 'not_estimated'
    if deskew_enabled and min(gray.shape) >= 8 and np.ptp(gray) > 0:
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        if 16 <= np.count_nonzero(binary) < 0.5 * binary.size:
            estimate = estimate_skew(binary)
            if estimate.confidence > 0 and abs(estimate.angle_degrees) < 14.9:
                correction = 0.0 if abs(estimate.angle_degrees) < 0.05 else estimate.angle_degrees
                rotation, skew_method = -float(correction), estimate.method
    corrected, applied = deskew(gray, angle_degrees=correction)
    corrected_color = None
    if color is not None and grid_profile != 'legacy':
        corrected_color, _ = deskew(color, angle_degrees=correction, border_value=(255, 255, 255))
        if corrected_color.shape[:2] != corrected.shape:
            raise RuntimeError('co-registered color/gray geometry drift')
    if np.ptp(corrected) == 0:
        raw_mask, bin_method = np.zeros_like(corrected), 'uniform_image'
    else:
        binary_result = binarize(corrected, method='auto')
        raw_mask, bin_method = binary_result.mask, binary_result.method
    word_gray = corrected
    grid_metadata = {'version': 'legacy', 'status': 'not_applied'}
    if grid_profile != 'legacy':
        if max(corrected.shape) > 3000:
            raise GridQualityError('grid_ink_separation_ambiguous')
        inspected = separate_grid(corrected_color, corrected, raw_mask)
        require_qualified(inspected)
        raw_mask = inspected.retained_mask
        word_gray = inspected.proposal_gray
        grid_metadata = inspected.diagnostics()
        if inspected.status != 'absent':
            # Printed paper alignment is not necessarily a text skew estimate.
            rotation = None
            skew_method = 'paper_rule_alignment_not_text_skew'
    if np.ptp(corrected) == 0:
        mask, removed = np.zeros_like(corrected), 0
    else:
        mask, report = denoise(raw_mask, speckle=True, large_blobs=True, closing=False)
        removed = report.removed_pixels
    if grid_profile != 'legacy' and grid_metadata['status'] != 'absent' and not np.any(mask):
        raise GridQualityError('no_handwriting_after_grid_removal')
    lines = segment_lines(mask)
    if word_trace is not None:
        word_trace.update({"raw_contours": 0, "raw_proposals": 0,
                           "after_geometry_filter": 0, "accepted_words": 0})
    proposals = (filter_word_proposals(detect_words(word_gray, diagnostics=word_trace),
                                     mask.shape, diagnostics=word_trace) if lines else [])
    sx, sy = w / original_w, h / original_h
    resize = np.array([[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]])
    rotate = np.eye(3)
    if applied:
        rotate[:2] = cv2.getRotationMatrix2D((w / 2, h / 2), applied, 1)
        rotate[0, 2] += (corrected.shape[1] - w) / 2
        rotate[1, 2] += (corrected.shape[0] - h) / 2
    transform = rotate @ resize
    metadata = {
        'coordinate_frame': 'analysis_canvas', 'original_width': original_w, 'original_height': original_h,
        'resize_scale_xy': [sx, sy], 'deskew_applied_deg': float(applied), 'skew_method': skew_method,
        'original_to_analysis': transform.tolist(), 'analysis_to_original': np.linalg.inv(transform).tolist(),
        'binarize_method': bin_method, 'denoise_removed_pixels': removed,
        'layout_assumption': 'single_column; margins relative to image canvas, not detected paper edges',
        'rotation_caveat': 'text tilt cannot distinguish page rotation from intentional baseline tilt',
        'grid_preprocessing': grid_metadata,
        'word_proposal_input': 'grid_suppressed_gray' if grid_profile != 'legacy' else 'original_gray',
    }
    return build_measurement_context(corrected, mask, lines=lines, words=[p.box for p in proposals],
                                     original_width=original_w, original_height=original_h,
                                     rotation_deg=rotation, metadata=metadata, word_trace=word_trace)
