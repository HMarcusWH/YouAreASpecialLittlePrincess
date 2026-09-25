# Adapted from NitinRamchandani/ocr-preprocessing-tool (MIT). See THIRD_PARTY_NOTICES.md.
"""Geometric correction: deskew, deslant, and rescale.

Skew is the single largest source of avoidable OCR error in scanned text. A
two-degree rotation is invisible to a reader and destroys horizontal projection
profiles, which is what line segmentation depends on. Correcting it first means
every later stage operates on a cleaner input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SkewEstimate:
    """Result of a skew measurement."""

    angle_degrees: float
    method: str
    confidence: float

    def __str__(self) -> str:
        return f"{self.angle_degrees:+.2f}deg via {self.method} (conf {self.confidence:.2f})"


def estimate_skew_projection(binary: np.ndarray,
                             limit: float = 15.0,
                             step: float = 0.2) -> SkewEstimate:
    """Estimate skew by maximising the variance of the horizontal projection.

    Rotating text to true horizontal makes the row-sum profile alternate
    sharply between dense text rows and empty inter-line gaps. That alternation
    is exactly what high variance measures, so the angle producing peak
    variance is the correct one.

    Robust on dense body text. Weak on sparse pages where too few rows exist
    for the profile to be meaningful, which is why ``estimate_skew`` falls back
    to the Hough method when confidence is low.

    Args:
        binary: single-channel image, text as white (255) on black (0).
        limit: search range in degrees, plus and minus.
        step: search granularity in degrees.

    Returns:
        The best angle found, with a confidence in ``[0, 1]`` derived from how
        much the peak variance exceeds the median across the search.
    """
    if binary.ndim != 2:
        raise ValueError("estimate_skew_projection expects a single-channel image")

    # Downscale: skew is a global property and full resolution wastes time.
    height, width = binary.shape
    scale = min(1.0, 800.0 / max(height, width))
    if scale < 1.0:
        binary = cv2.resize(binary, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_NEAREST)

    angles = np.arange(-limit, limit + step, step)
    scores = np.empty(len(angles), dtype=np.float64)

    for i, angle in enumerate(angles):
        rotated = _rotate_keep_size(binary, angle)
        profile = rotated.sum(axis=1, dtype=np.float64)
        scores[i] = profile.var()

    best_index = int(np.argmax(scores))
    best_angle = float(angles[best_index])

    median = float(np.median(scores))
    peak = float(scores[best_index])
    confidence = 0.0 if peak <= 0 else min(1.0, (peak - median) / peak)

    return SkewEstimate(best_angle, "projection-variance", confidence)


def estimate_skew_hough(binary: np.ndarray, limit: float = 15.0) -> SkewEstimate:
    """Estimate skew from the dominant angle of detected line segments.

    Works where the projection method does not: sparse pages, forms, and
    anything with ruled lines or table borders. Fails on images with no
    extended straight structure at all.
    """
    edges = cv2.Canny(binary, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=100,
                            minLineLength=max(40, binary.shape[1] // 8),
                            maxLineGap=12)

    if lines is None or len(lines) == 0:
        return SkewEstimate(0.0, "hough", 0.0)

    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        if x2 == x1:
            continue
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        # Fold near-vertical segments (table borders) onto the horizontal axis.
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        if abs(angle) <= limit:
            angles.append(angle)

    if not angles:
        return SkewEstimate(0.0, "hough", 0.0)

    angles_arr = np.array(angles)
    # Median, not mean: one badly detected segment should not move the answer.
    best = float(np.median(angles_arr))
    spread = float(np.std(angles_arr))
    confidence = float(np.clip(1.0 - spread / 5.0, 0.0, 1.0))

    return SkewEstimate(best, "hough", confidence)


def estimate_skew(binary: np.ndarray, limit: float = 15.0) -> SkewEstimate:
    """Estimate skew, preferring projection variance and falling back to Hough.

    The two methods fail on disjoint inputs, so trying the cheap reliable one
    first and only reaching for the other when confidence is poor gets better
    coverage than either alone.
    """
    projection = estimate_skew_projection(binary, limit=limit)
    if projection.confidence >= 0.35:
        return projection

    hough = estimate_skew_hough(binary, limit=limit)
    return hough if hough.confidence > projection.confidence else projection


def deskew(image: np.ndarray,
           angle_degrees: float | None = None,
           border_value: int = 255) -> tuple[np.ndarray, float]:
    """Rotate an image to correct skew, expanding the canvas to avoid clipping.

    Args:
        image: grayscale or colour.
        angle_degrees: measured angle, or None to measure it here.
        border_value: fill for the corners the rotation exposes. 255 for a
            white-background page, so introduced pixels read as paper rather
            than as ink.

    Returns:
        ``(rotated_image, applied_angle)``.
    """
    if angle_degrees is None:
        working = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(working, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        angle_degrees = estimate_skew(binary).angle_degrees

    if abs(angle_degrees) < 0.05:
        return image, 0.0

    height, width = image.shape[:2]
    centre = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(centre, angle_degrees, 1.0)

    # Grow the canvas so rotation cannot push glyphs off the edge.
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_width = int(height * sin + width * cos)
    new_height = int(height * cos + width * sin)
    matrix[0, 2] += (new_width / 2.0) - centre[0]
    matrix[1, 2] += (new_height / 2.0) - centre[1]

    rotated = cv2.warpAffine(image, matrix, (new_width, new_height),
                             flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_CONSTANT,
                             borderValue=border_value)
    return rotated, float(angle_degrees)


def deslant(binary: np.ndarray, max_shear: float = 0.6) -> tuple[np.ndarray, float]:
    """Remove italic or cursive slant with a horizontal shear.

    Searches shear factors and keeps the one maximising the sum of squared
    column sums. Upright strokes stack into tall narrow columns, so that sum
    peaks when the glyphs are vertical. This is a standard normalisation for
    handwriting recognition and reduces intra-class variance noticeably.
    """
    if binary.ndim != 2:
        raise ValueError("deslant expects a single-channel image")

    height, width = binary.shape
    best_shear = 0.0
    best_score = -1.0

    for shear in np.arange(-max_shear, max_shear + 0.05, 0.05):
        matrix = np.array([[1, shear, -0.5 * shear * height],
                           [0, 1, 0]], dtype=np.float32)
        sheared = cv2.warpAffine(binary, matrix, (width, height),
                                 flags=cv2.INTER_NEAREST,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        column_sums = sheared.sum(axis=0, dtype=np.float64)
        score = float((column_sums ** 2).sum())
        if score > best_score:
            best_score = score
            best_shear = float(shear)

    if abs(best_shear) < 0.02:
        return binary, 0.0

    matrix = np.array([[1, best_shear, -0.5 * best_shear * height],
                       [0, 1, 0]], dtype=np.float32)
    corrected = cv2.warpAffine(binary, matrix, (width, height),
                               flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return corrected, best_shear


def rescale_to_height(image: np.ndarray, target_height: int = 64) -> np.ndarray:
    """Scale to a fixed height, preserving aspect ratio.

    Uses ``INTER_AREA`` when shrinking and ``INTER_CUBIC`` when growing.
    Shrinking with a non-area interpolation aliases thin strokes into
    dotted lines, which is a subtle and expensive mistake in an OCR pipeline
    because the damage happens before any classifier sees the glyph.
    """
    height, width = image.shape[:2]
    if height == target_height:
        return image

    scale = target_height / float(height)
    new_width = max(1, int(round(width * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(image, (new_width, target_height), interpolation=interpolation)


def pad_to_size(image: np.ndarray,
                size: tuple[int, int],
                fill: int = 0,
                centre: bool = True) -> np.ndarray:
    """Pad or centre-crop to an exact ``(height, width)``.

    Padding rather than stretching preserves the aspect ratio, which carries
    real information: a distorted '1' starts to resemble a '7', and stretching
    every glyph to a square throws that discriminator away.
    """
    target_h, target_w = size
    height, width = image.shape[:2]

    if height > target_h or width > target_w:
        scale = min(target_h / height, target_w / width)
        image = cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))),
                           interpolation=cv2.INTER_AREA)
        height, width = image.shape[:2]

    pad_y = target_h - height
    pad_x = target_w - width
    if centre:
        top, left = pad_y // 2, pad_x // 2
    else:
        top, left = 0, 0

    return cv2.copyMakeBorder(image, top, pad_y - top, left, pad_x - left,
                              cv2.BORDER_CONSTANT, value=fill)


def _rotate_keep_size(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotate about the centre without resizing. Internal to skew search."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(image, matrix, (width, height),
                          flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)
