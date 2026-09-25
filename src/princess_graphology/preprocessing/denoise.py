# Adapted from NitinRamchandani/ocr-preprocessing-tool (MIT). See THIRD_PARTY_NOTICES.md.
"""Noise removal and stroke repair.

Runs after binarization on the binary mask. Two failure modes bracket every
choice here: remove too little and the segmenter finds hundreds of one-pixel
"characters"; remove too much and punctuation, dots on an 'i', and diacritics
disappear. Every default below is chosen to sit on the conservative side of
that line, because a false character is recoverable downstream and a deleted
one is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class DenoiseReport:
    """What a denoising pass changed."""

    removed_components: int = 0
    removed_pixels: int = 0
    filled_holes: int = 0
    operations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"removed {self.removed_components} component(s) "
                f"/ {self.removed_pixels} px, filled {self.filled_holes} hole(s) "
                f"[{', '.join(self.operations) or 'none'}]")


def remove_speckle(mask: np.ndarray,
                   min_area: int | None = None,
                   min_dimension: int = 2) -> tuple[np.ndarray, DenoiseReport]:
    """Drop connected components too small to be glyphs or punctuation.

    ``min_area`` defaults to a fraction of the estimated stroke width squared
    rather than a fixed pixel count, because a threshold tuned at 300 DPI
    deletes commas at 150 DPI. Deriving it from the image's own stroke width
    makes the stage resolution independent, which matters when a dataset mixes
    sources.

    Args:
        mask: binary, ink as 255.
        min_area: override the derived area threshold.
        min_dimension: components thinner than this in both axes are dropped
            regardless of area, catching single-pixel scan lines.
    """
    report = DenoiseReport()

    if min_area is None:
        stroke = estimate_stroke_width(mask)
        min_area = max(3, int(round((stroke * 0.75) ** 2)))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8)

    keep = np.zeros(count, dtype=bool)
    keep[0] = True  # background

    for index in range(1, count):
        area = stats[index, cv2.CC_STAT_AREA]
        width = stats[index, cv2.CC_STAT_WIDTH]
        height = stats[index, cv2.CC_STAT_HEIGHT]

        too_small = area < min_area
        too_thin = width < min_dimension and height < min_dimension

        if too_small or too_thin:
            report.removed_components += 1
            report.removed_pixels += int(area)
        else:
            keep[index] = True

    cleaned = np.where(keep[labels], mask, 0).astype(np.uint8)
    report.operations.append(f"speckle(min_area={min_area})")
    return cleaned, report


def remove_large_blobs(mask: np.ndarray,
                       max_area_fraction: float = 0.25) -> tuple[np.ndarray, DenoiseReport]:
    """Drop components covering an implausible fraction of the page.

    Catches the failure where a shadow, a page border, or a photographed
    fingertip binarizes as one enormous connected region. Such a blob usually
    also merges with real text, so this runs before segmentation rather than
    after.
    """
    report = DenoiseReport()
    max_area = int(mask.size * max_area_fraction)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8)

    keep = np.ones(count, dtype=bool)
    for index in range(1, count):
        area = stats[index, cv2.CC_STAT_AREA]
        if area > max_area:
            keep[index] = False
            report.removed_components += 1
            report.removed_pixels += int(area)

    cleaned = np.where(keep[labels], mask, 0).astype(np.uint8)
    report.operations.append(f"large_blob(max={max_area_fraction:.0%})")
    return cleaned, report


def close_gaps(mask: np.ndarray,
               kernel_size: int | None = None,
               iterations: int = 1) -> tuple[np.ndarray, DenoiseReport]:
    """Morphological closing to reconnect strokes broken by thresholding.

    A faded stroke often binarizes into two fragments separated by a one or
    two pixel gap, which segmentation then reports as two characters. Closing
    with a kernel around the stroke width bridges those gaps without merging
    adjacent glyphs, provided the kernel stays comfortably below inter-
    character spacing.
    """
    report = DenoiseReport()

    if kernel_size is None:
        stroke = estimate_stroke_width(mask)
        kernel_size = max(2, int(round(stroke * 0.6)))

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=iterations)

    report.filled_holes = int(((closed > 0) & (mask == 0)).sum())
    report.operations.append(f"close(k={kernel_size}, i={iterations})")
    return closed, report


def thin_strokes(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    """Erode to normalise stroke weight.

    Useful when a dataset mixes pen weights, since a classifier trained mostly
    on thin strokes degrades on bold ones. Applied sparingly: over-eroding
    breaks thin strokes entirely, which is the worse error.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    return cv2.erode(mask, kernel, iterations=iterations)


def estimate_stroke_width(mask: np.ndarray) -> float:
    """Estimate stroke width from the distance transform.

    The distance transform gives each ink pixel its distance to the nearest
    background pixel. Along a stroke's centreline that distance equals half the
    stroke width, so twice the median over the upper quantile of the transform
    is a robust estimate. Robust specifically because it ignores the stroke
    edges, where the distance is near zero regardless of width.

    Returns:
        Estimated width in pixels, minimum 1.0. Returns 1.0 for an empty mask.
    """
    binary = (mask > 0).astype(np.uint8)
    if binary.sum() == 0:
        return 1.0

    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    values = distance[distance > 0]
    if values.size == 0:
        return 1.0

    # Upper quartile approximates centreline pixels.
    centreline = values[values >= np.percentile(values, 75)]
    if centreline.size == 0:
        return 1.0

    return float(max(1.0, 2.0 * np.median(centreline)))


def denoise(mask: np.ndarray,
            speckle: bool = True,
            large_blobs: bool = True,
            closing: bool = True) -> tuple[np.ndarray, DenoiseReport]:
    """Run the standard denoising sequence.

    Order is deliberate:

    1. Large blobs first. A shadow blob distorts the stroke width estimate
       that the later stages derive their parameters from.
    2. Speckle second, on a mask whose stroke width is now measurable.
    3. Closing last, so it is not asked to bridge gaps in noise that was
       about to be deleted anyway.
    """
    combined = DenoiseReport()
    result = mask

    if large_blobs:
        result, report = remove_large_blobs(result)
        combined.removed_components += report.removed_components
        combined.removed_pixels += report.removed_pixels
        combined.operations += report.operations

    if speckle:
        result, report = remove_speckle(result)
        combined.removed_components += report.removed_components
        combined.removed_pixels += report.removed_pixels
        combined.operations += report.operations

    if closing:
        result, report = close_gaps(result)
        combined.filled_holes += report.filled_holes
        combined.operations += report.operations

    return result, combined
