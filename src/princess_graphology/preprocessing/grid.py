"""Deterministic, conservative graph-paper separation (grid-v1).

Foreground pixels are 255. No OCR, models, learned classifiers or network.
New implementation informed by MIT-licensed signature-remove-bg and heb-ocr,
using public OpenCV morphology primitives. Ambiguous grids fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import cv2
import numpy as np

GRID_PROFILE = "grid-v1"
MAX_GRID_CANVAS_DIMENSION = 3000


class GridQualityError(ValueError):
    def __init__(self, code: str):
        if code not in ("grid_ink_separation_ambiguous", "no_handwriting_after_grid_removal"):
            raise ValueError("unknown grid quality error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GridResult:
    retained_mask: np.ndarray
    proposal_gray: np.ndarray
    candidate_mask: np.ndarray
    removable_mask: np.ndarray
    uncertainty_mask: np.ndarray
    status: str
    horizontal_pitch_px: float | None
    vertical_pitch_px: float | None
    removed_pixels: int
    candidate_pixels: int
    uncertain_pixels: int
    version: str = GRID_PROFILE

    def diagnostics(self) -> dict:
        return {
            "version": self.version,
            "status": self.status,
            "horizontal_pitch_px": self.horizontal_pitch_px,
            "vertical_pitch_px": self.vertical_pitch_px,
            "grid_candidate_pixels": self.candidate_pixels,
            "grid_removed_pixels": self.removed_pixels,
            "grid_uncertain_pixels": self.uncertain_pixels,
            "grid_separation_policy": "colored_light_rule_only; ambiguous_fails_closed",
        }


def _runs(active: np.ndarray) -> list[tuple[int, int]]:
    padded = np.pad(active.astype(np.uint8), (1, 1))
    delta = np.diff(padded.astype(np.int16))
    return list(zip(np.flatnonzero(delta == 1).tolist(), (np.flatnonzero(delta == -1) - 1).tolist()))


def _regular_centres(profile: np.ndarray, min_count: int, *, min_pitch: int = 7):
    max_value = float(profile.max(initial=0))
    if max_value == 0:
        return (), None
    bands = _runs(profile >= max(3., max_value * 0.32))
    centres = np.asarray([(a + b) / 2 for a, b in bands if b - a <= 12], dtype=float)
    if len(centres) < min_count:
        return (), None
    gaps = np.diff(centres)
    if not len(gaps):
        return (), None
    gaps = gaps[gaps >= min_pitch]
    if len(gaps) < min_count - 1:
        return (), None
    pitch = float(np.median(gaps))
    if pitch < min_pitch or pitch > profile.size * 0.40:
        return (), None
    aligned = np.count_nonzero(np.abs(gaps - pitch) <= max(2., 0.16 * pitch))
    if aligned / len(gaps) < 0.75:
        return (), None
    return tuple(float(x) for x in centres), pitch


def _candidate_ruling(binary: np.ndarray):
    h, w = binary.shape
    lh = min(max(35, w // 16), max(35, w))
    lv = min(max(35, h // 16), max(35, h))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (lh, 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (1, lv)))
    hpos, hpitch = _regular_centres((horizontal > 0).sum(axis=1).astype(float), 4)
    vpos, vpitch = _regular_centres((vertical > 0).sum(axis=0).astype(float), 4)
    if not (hpos or vpos):
        return np.zeros_like(binary), None, None, np.zeros_like(binary)
    found = np.zeros_like(binary)
    if hpos:
        found = cv2.bitwise_or(found, horizontal)
    if vpos:
        found = cv2.bitwise_or(found, vertical)
    bands = np.zeros_like(binary)
    for centre in hpos:
        y = int(round(centre))
        bands[max(0, y - 2):min(h, y + 3), :] = 255
    for centre in vpos:
        x = int(round(centre))
        bands[:, max(0, x - 2):min(w, x + 3)] = 255
    return found, hpitch, vpitch, bands


def _chromatic_ruling(color: np.ndarray, gray: np.ndarray):
    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    background = float(np.percentile(gray, 90))
    return ((saturation >= 35) & (value >= 120) & (gray <= background - 8)).astype(np.uint8) * 255


def separate_grid(color: np.ndarray | None, gray: np.ndarray, ink_mask: np.ndarray) -> GridResult:
    """All arrays are co-registered; the original image is not mutated.

    Preserve darker/differently-colored pen marks at crossings. Gray or
    pen-colored grid cannot be removed reliably and must fail closed.
    """
    if gray.ndim != 2 or gray.dtype != np.uint8 or not gray.size:
        raise ValueError("grid-v1 requires nonempty uint8 grayscale")
    if max(gray.shape) > MAX_GRID_CANVAS_DIMENSION:
        raise ValueError("grid-v1 analysis canvas exceeds reviewed size")
    if ink_mask.shape != gray.shape or ink_mask.dtype != np.uint8 or not np.isin(ink_mask, (0, 255)).all():
        raise ValueError("grid-v1 mask must be co-registered uint8 binary 0/255")
    if color is not None and (color.shape != (*gray.shape, 3) or color.dtype != np.uint8):
        raise ValueError("grid-v1 color must be co-registered BGR uint8")

    chroma = _chromatic_ruling(color, gray) if color is not None else np.zeros_like(ink_mask)
    chroma_lines, hc, vc, chroma_bands = _candidate_ruling(chroma)
    binary_lines, hb, vb, _ = _candidate_ruling(ink_mask)
    background = float(np.percentile(gray, 90))
    faint_lines, hf, vf, _ = _candidate_ruling(np.where(gray < background - 8, 255, 0).astype(np.uint8))
    has_grid = any(p is not None for p in (hc, vc, hb, vb, hf, vf))
    chroma_identified = bool(hc is not None or vc is not None)
    candidates = cv2.bitwise_or(cv2.bitwise_or(chroma_lines, binary_lines), faint_lines)

    if not has_grid:
        return GridResult(ink_mask.copy(), gray.copy(), candidates, np.zeros_like(ink_mask),
                          np.zeros_like(ink_mask), "absent", None, None, 0, 0, 0)

    if not chroma_identified:
        uncertain = cv2.bitwise_and(ink_mask, cv2.bitwise_or(binary_lines, faint_lines))
        return GridResult(ink_mask.copy(), gray.copy(), candidates, np.zeros_like(ink_mask),
                          uncertain, "ambiguous", hb or hf, vb or vf, 0, int(np.count_nonzero(candidates)),
                          int(np.count_nonzero(uncertain)))

    neighbourhood = cv2.dilate(chroma_lines, np.ones((3, 3), np.uint8))
    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.int16)
    sample = chroma_lines > 0
    reference_hue = int(np.median(hue[sample]))
    reference_gray = float(np.median(gray[sample]))
    distance = np.abs(hue - reference_hue)
    hue_gap = np.minimum(distance, 180 - distance)
    near_print_ink = (hue_gap <= 12) & (gray >= reference_gray - 25)
    printed_pixels = (chroma > 0) & near_print_ink
    removable = np.where((neighbourhood > 0) & printed_pixels, 255, 0).astype(np.uint8)
    removable_from_ink = cv2.bitwise_and(removable, ink_mask)
    retained = cv2.bitwise_and(ink_mask, cv2.bitwise_not(removable_from_ink))
    proposal_gray = gray.copy()
    proposal_gray[removable > 0] = 255

    discrepancy = cv2.bitwise_and(binary_lines, cv2.bitwise_not(neighbourhood))
    unknown = cv2.bitwise_and(discrepancy, ink_mask)
    unresolved = int(np.count_nonzero(unknown))
    same_tone_ink_px = int(np.count_nonzero(printed_pixels & (chroma_bands == 0)))
    original = int(np.count_nonzero(ink_mask))
    removed = int(np.count_nonzero(removable_from_ink))
    leftover = int(np.count_nonzero(retained))
    if unresolved > max(100, original // 10) or same_tone_ink_px > max(75, gray.size // 20000):
        status = "ambiguous"
    elif leftover < max(12, gray.size // 30000):
        status = "empty_after_clean"
    else:
        status = "cleaned" if removed else "detected_no_contamination"

    return GridResult(retained, proposal_gray, candidates, removable, unknown, status,
                      hc or hb, vc or vb, removed, int(np.count_nonzero(candidates)), unresolved)


def require_qualified(result: GridResult) -> None:
    if result.status == "ambiguous":
        raise GridQualityError("grid_ink_separation_ambiguous")
    if result.status == "empty_after_clean":
        raise GridQualityError("no_handwriting_after_grid_removal")
