# Adapted from NitinRamchandani/ocr-preprocessing-tool (MIT). See THIRD_PARTY_NOTICES.md.
"""Binarization: separating ink from paper.

The single most consequential stage in the pipeline. Every downstream step
operates on the binary mask, so a threshold that eats thin strokes or floods
the page with noise cannot be recovered from later. No classifier, however
good, recovers a stroke that binarization deleted.

Four methods are provided because no single one wins across document types:

===================  ==============================================
Method               Best on
===================  ==============================================
``otsu``             Clean scans with uniform lighting
``adaptive``         Uneven illumination, phone photographs
``sauvola``          Faded ink, degraded historical documents
``niblack``          High-contrast text with a noisy background
===================  ==============================================

``auto`` measures illumination uniformity and picks between them.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class BinarizationResult:
    """A binary mask plus how it was produced."""

    mask: np.ndarray
    method: str
    threshold: float | None
    ink_ratio: float

    def __str__(self) -> str:
        thresh = "adaptive" if self.threshold is None else f"{self.threshold:.1f}"
        return f"{self.method} (T={thresh}, ink {self.ink_ratio:.1%})"


def otsu(gray: np.ndarray, invert: bool = True) -> BinarizationResult:
    """Global threshold chosen to minimise intra-class variance.

    Assumes the intensity histogram is bimodal: one lobe of paper, one of ink.
    On a clean scan that assumption holds and Otsu is both fast and close to
    optimal. On a page with a shadow across one corner it does not, because the
    shadowed paper overlaps the ink lobe and the whole corner binarizes as
    text.
    """
    flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    threshold, mask = cv2.threshold(gray, 0, 255, flag + cv2.THRESH_OTSU)
    return BinarizationResult(mask, "otsu", float(threshold), _ink_ratio(mask))


def adaptive_gaussian(gray: np.ndarray,
                      block_size: int = 31,
                      constant: float = 10.0,
                      invert: bool = True) -> BinarizationResult:
    """Per-pixel threshold from a Gaussian-weighted local mean.

    Handles uneven lighting because the threshold tracks the illumination
    rather than assuming it is flat.

    Args:
        block_size: neighbourhood size, must be odd. Should comfortably exceed
            stroke width. Too small and the interior of a thick stroke becomes
            its own background and hollows out.
        constant: subtracted from the local mean. Raise it to suppress noise
            in blank regions, lower it to retain faint strokes.
    """
    if block_size % 2 == 0:
        block_size += 1
    block_size = max(3, block_size)

    flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 flag, block_size, constant)
    return BinarizationResult(mask, "adaptive", None, _ink_ratio(mask))


def sauvola(gray: np.ndarray,
            window: int = 25,
            k: float = 0.2,
            r: float = 128.0,
            invert: bool = True) -> BinarizationResult:
    """Sauvola local thresholding.

    ``T(x,y) = m(x,y) * (1 + k * (s(x,y) / R - 1))``

    where ``m`` and ``s`` are the local mean and standard deviation. In a
    uniform region ``s`` is near zero, the bracket goes negative, and the
    threshold drops below the mean, so blank paper does not binarize into
    speckle. That behaviour is what makes Sauvola the standard choice for
    degraded documents where a global threshold either loses faint ink or
    fills the background with noise.

    Implemented with integral images, so cost is independent of window size.
    """
    if window % 2 == 0:
        window += 1
    window = max(3, window)

    image = gray.astype(np.float64)
    pad = window // 2
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_REFLECT)

    integral, integral_sq = cv2.integral2(padded)
    area = float(window * window)

    height, width = gray.shape
    top_left = integral[0:height, 0:width]
    top_right = integral[0:height, window:window + width]
    bottom_left = integral[window:window + height, 0:width]
    bottom_right = integral[window:window + height, window:window + width]
    local_sum = bottom_right - bottom_left - top_right + top_left

    tl2 = integral_sq[0:height, 0:width]
    tr2 = integral_sq[0:height, window:window + width]
    bl2 = integral_sq[window:window + height, 0:width]
    br2 = integral_sq[window:window + height, window:window + width]
    local_sum_sq = br2 - bl2 - tr2 + tl2

    mean = local_sum / area
    variance = np.maximum(local_sum_sq / area - mean ** 2, 0.0)
    std = np.sqrt(variance)

    threshold = mean * (1.0 + k * (std / r - 1.0))
    mask = (image < threshold) if invert else (image >= threshold)

    return BinarizationResult((mask * 255).astype(np.uint8), "sauvola",
                              float(np.median(threshold)), _ink_ratio(mask * 255))


def niblack(gray: np.ndarray,
            window: int = 25,
            k: float = -0.2,
            invert: bool = True) -> BinarizationResult:
    """Niblack local thresholding: ``T = m + k * s``.

    Retains more faint detail than Sauvola but produces speckle in blank
    regions, because with ``s`` near zero the threshold collapses to the local
    mean and half the noise falls on each side. Useful when recall of faint
    strokes matters more than a clean background, and normally paired with a
    denoising pass.
    """
    if window % 2 == 0:
        window += 1
    window = max(3, window)

    image = gray.astype(np.float64)
    mean = cv2.boxFilter(image, cv2.CV_64F, (window, window), normalize=True,
                         borderType=cv2.BORDER_REFLECT)
    mean_sq = cv2.boxFilter(image ** 2, cv2.CV_64F, (window, window), normalize=True,
                            borderType=cv2.BORDER_REFLECT)
    std = np.sqrt(np.maximum(mean_sq - mean ** 2, 0.0))

    threshold = mean + k * std
    mask = (image < threshold) if invert else (image >= threshold)

    return BinarizationResult((mask * 255).astype(np.uint8), "niblack",
                              float(np.median(threshold)), _ink_ratio(mask * 255))


def illumination_uniformity(gray: np.ndarray, tiles: int = 8) -> float:
    """Measure how flat the lighting is, in ``[0, 1]``.

    Splits the image into a grid, takes the median of each tile, and compares
    the spread of those medians to their overall level. A flatbed scan lands
    near 1.0; a phone photograph with a shadow lands well below.

    This is the signal ``auto`` uses to decide whether a global threshold is
    safe.
    """
    height, width = gray.shape
    tile_h = max(1, height // tiles)
    tile_w = max(1, width // tiles)

    medians = []
    for y in range(0, height - tile_h + 1, tile_h):
        for x in range(0, width - tile_w + 1, tile_w):
            medians.append(np.median(gray[y:y + tile_h, x:x + tile_w]))

    if not medians:
        return 1.0

    medians_arr = np.array(medians, dtype=np.float64)
    level = float(medians_arr.mean())
    if level <= 1e-6:
        return 1.0

    spread = float(medians_arr.std())
    return float(np.clip(1.0 - (spread / level) * 3.0, 0.0, 1.0))


def auto(gray: np.ndarray, invert: bool = True) -> BinarizationResult:
    """Choose a binarization method from measured image properties.

    Decision rule, in order:

    1. Uniform illumination (>= 0.80) and a bimodal histogram -> ``otsu``.
       Cheapest and best when its assumptions hold.
    2. Poor uniformity (< 0.55) -> ``adaptive``. Strong illumination gradient,
       a global threshold cannot work.
    3. Otherwise -> ``sauvola``. Middle ground, tolerant of mild gradients and
       of faded ink.

    A result whose ink ratio is implausible (under 0.5% or over 40% of the
    page) is treated as a failure and retried with ``adaptive``, since a page
    of text almost always falls between those bounds. Catching the failure
    here matters because everything downstream would otherwise inherit it.
    """
    uniformity = illumination_uniformity(gray)
    bimodal = _histogram_bimodality(gray)

    if uniformity >= 0.80 and bimodal >= 0.35:
        result = otsu(gray, invert=invert)
    elif uniformity < 0.55:
        result = adaptive_gaussian(gray, invert=invert)
    else:
        result = sauvola(gray, invert=invert)

    if not 0.005 <= result.ink_ratio <= 0.40:
        fallback = adaptive_gaussian(gray, invert=invert)
        if abs(fallback.ink_ratio - 0.10) < abs(result.ink_ratio - 0.10):
            fallback.method = f"adaptive (auto rescued {result.method})"
            return fallback

    result.method = f"{result.method} (auto, uniformity {uniformity:.2f})"
    return result


def binarize(gray: np.ndarray, method: str = "auto", **kwargs) -> BinarizationResult:
    """Dispatch to a named binarization method."""
    if gray.ndim != 2:
        raise ValueError("binarize expects a single-channel image")

    methods = {
        "otsu": otsu,
        "adaptive": adaptive_gaussian,
        "sauvola": sauvola,
        "niblack": niblack,
        "auto": auto,
    }
    if method not in methods:
        raise ValueError(f"unknown method {method!r}, choose from {sorted(methods)}")

    return methods[method](gray, **kwargs)


def _ink_ratio(mask: np.ndarray) -> float:
    """Fraction of pixels marked as ink."""
    return float((mask > 0).sum()) / float(mask.size)


def _histogram_bimodality(gray: np.ndarray) -> float:
    """Crude bimodality score in ``[0, 1]``.

    Smooths the intensity histogram, finds the two tallest well-separated
    peaks, and scores the depth of the valley between them relative to the
    smaller peak. A deep valley means ink and paper are cleanly separable by a
    single global threshold.
    """
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    hist = cv2.GaussianBlur(hist.reshape(-1, 1), (1, 9), 0).ravel()

    if hist.sum() <= 0:
        return 0.0
    hist = hist / hist.sum()

    peaks = []
    for i in range(2, 254):
        if hist[i] > hist[i - 1] and hist[i] >= hist[i + 1] and hist[i] > 0.001:
            peaks.append((hist[i], i))

    if len(peaks) < 2:
        return 0.0

    peaks.sort(reverse=True)
    (h1, i1), (h2, i2) = peaks[0], peaks[1]
    for height, index in peaks[1:]:
        if abs(index - i1) > 30:
            h2, i2 = height, index
            break
    else:
        return 0.0

    low, high = sorted((i1, i2))
    valley = float(hist[low:high + 1].min())
    smaller = float(min(h1, h2))
    if smaller <= 0:
        return 0.0

    return float(np.clip(1.0 - valley / smaller, 0.0, 1.0))
