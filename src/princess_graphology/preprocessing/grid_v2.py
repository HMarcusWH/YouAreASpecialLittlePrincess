"""Grid-v2: deterministic neutral and chromatic ruling separation.

Only high-support periodic horizontal/vertical print lines qualify. Preserve
observed darker ink at intersections; never inpaint or invent pen pixels.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .grid import GridQualityError

MAX_SIDE = 3000
MAX_CANDIDATE_FRACTION = 0.35


@dataclass(frozen=True)
class GridV2Result:
    retained_mask: np.ndarray
    proposal_gray: np.ndarray
    status: str
    candidate_pixels: int
    removed_pixels: int
    uncertain_pixels: int
    horizontal_pitch_px: float | None
    vertical_pitch_px: float | None
    reference_intensity: float | None

    def diagnostics(self) -> dict:
        return {"version": "grid-v2", "status": self.status,
                "grid_candidate_pixels": self.candidate_pixels,
                "grid_removed_pixels": self.removed_pixels,
                "grid_uncertain_pixels": self.uncertain_pixels,
                "horizontal_pitch_px": self.horizontal_pitch_px,
                "vertical_pitch_px": self.vertical_pitch_px,
                "ruling_reference_gray": self.reference_intensity,
                "grid_separation_policy": "periodic_chromatic_or_gray; observed_ink_only"}


def _centres(profile: np.ndarray, dimension: int, min_support: float):
    active = np.flatnonzero(profile >= min_support)
    if active.size < 4:
        return [], None
    groups = np.split(active, np.where(np.diff(active) > 1)[0] + 1)
    pos = [int(round((g[0] + g[-1]) / 2)) for g in groups if len(g) <= 12]
    if len(pos) < 4:
        return [], None
    gaps = np.diff(pos).astype(float)
    good = gaps >= 8
    if np.count_nonzero(good) < 3:
        return [], None
    pitch = float(np.median(gaps[good]))
    if pitch < 8 or pitch > dimension / 3:
        return [], None
    close = np.abs(gaps - pitch) <= max(2.5, pitch * 0.17)
    if np.count_nonzero(close) < max(3, int(0.7 * len(gaps))):
        return [], None
    return pos, pitch


def _lines(gray: np.ndarray, background: float, *, dark_only=False):
    h, w = gray.shape
    # Detect light neutral prints absent from Otsu's ink mask as well as color.
    signal = np.where(gray < background - 8, 255, 0).astype(np.uint8)
    horizontal = cv2.morphologyEx(signal, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (max(35, w // 5), 1)))
    vertical = cv2.morphologyEx(signal, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(35, h // 5))))
    horiz_counts = np.count_nonzero(horizontal, axis=1)
    vert_counts = np.count_nonzero(vertical, axis=0)
    hp, pitch_h = _centres(horiz_counts, h, max(15, 0.67 * w))
    vp, pitch_v = _centres(vert_counts, w, max(15, 0.67 * h))
    mask = np.zeros((h, w), np.uint8)
    for y in hp:
        mask[max(0, y - 2):min(h, y + 3), :] = 255
    for x in vp:
        mask[:, max(0, x - 2):min(w, x + 3)] = 255
    observed = cv2.bitwise_or(horizontal if hp else np.zeros_like(mask),
                             vertical if vp else np.zeros_like(mask))
    return mask, observed, pitch_h, pitch_v


def separate_grid_v2(color: np.ndarray | None, gray: np.ndarray,
                     raw_mask: np.ndarray) -> GridV2Result:
    if not isinstance(gray, np.ndarray) or gray.dtype != np.uint8 or gray.ndim != 2 or not gray.size:
        raise ValueError("grid-v2 requires grayscale uint8")
    if max(gray.shape) > MAX_SIDE or raw_mask.shape != gray.shape or raw_mask.dtype != np.uint8:
        raise ValueError("grid-v2 requires bounded registered binary mask")
    if not np.isin(raw_mask, (0, 255)).all():
        raise ValueError("grid-v2 requires binary ink polarity")
    if color is not None and (color.shape != (*gray.shape, 3) or color.dtype != np.uint8):
        raise ValueError("grid-v2 color/gray mismatch")
    background = float(np.percentile(gray, 90))
    regions, supports, hp, vp = _lines(gray, background)
    if hp is None and vp is None:
        return GridV2Result(raw_mask.copy(), gray.copy(), "absent", 0, 0, 0,
                            None, None, None)
    pixels = int(np.count_nonzero(regions))
    if pixels > MAX_CANDIDATE_FRACTION * gray.size:
        raise GridQualityError("grid_ink_separation_ambiguous")
    samples = (supports > 0) & (gray < background - 8)
    if not np.any(samples):
        raise GridQualityError("grid_ink_separation_ambiguous")
    ref_gray = float(np.median(gray[samples]))
    # When ruling is as dark as pen, identity at intersections is unresolvable.
    # Never guess which same-tone pixels belong to handwriting.
    if ref_gray < 120:
        raise GridQualityError("grid_ink_separation_ambiguous")
    has_ruling = regions > 0
    # Contrast is local relative to the observed print, not a blue-pen rule.
    print_like = has_ruling & (gray >= ref_gray - 26) & (gray <= min(255., background - 3))
    ambiguous = has_ruling & (gray > ref_gray - 45) & ~print_like & (gray < ref_gray)
    if np.count_nonzero(ambiguous & (raw_mask > 0)) > max(64, gray.size // 7500):
        raise GridQualityError("grid_ink_separation_ambiguous")
    removed_mask = print_like & (raw_mask > 0)
    retained = raw_mask.copy()
    retained[removed_mask] = 0
    proposal_gray = gray.copy()
    proposal_gray[print_like] = 255
    removed = int(np.count_nonzero(removed_mask))
    # A more sensitive independent check detects residual *periodic* ruling.
    residual_regions, _, rh, rv = _lines(np.where(retained > 0, gray, 255).astype(np.uint8), background)
    residual = int(np.count_nonzero((residual_regions > 0) & (retained > 0)))
    if (rh is not None or rv is not None) and residual > max(80, np.count_nonzero(retained) // 8):
        raise GridQualityError("grid_ink_separation_ambiguous")
    if np.count_nonzero(retained) < max(8, gray.size // 30000):
        raise GridQualityError("no_handwriting_after_grid_removal")
    return GridV2Result(retained, proposal_gray, "cleaned" if removed else "detected_no_contamination",
                        pixels, removed, int(np.count_nonzero(ambiguous)), hp, vp, ref_gray)
