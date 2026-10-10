"""Bounded TLC-inspired line *candidates*, independent implementation.
No copied upstream source. Never used by the authoritative Free engine.
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np
from .models import Box

METHOD_ID = "projection_peaks_shadow_v1"
MAX_DIMENSION = 3000
MAX_PEAKS = 128


@dataclass(frozen=True)
class LineCandidates:
    boxes: tuple[Box, ...]
    peak_rows: tuple[int, ...]
    diagnostics: dict[str, int | float | str]


def local_maxima(signal):
    """One index per plateau, never a series of duplicate maxima."""
    if len(signal) == 0 or np.max(signal) <= 0:
        return []
    candidates = [i for i in range(len(signal))
                  if (i == 0 or signal[i] >= signal[i - 1])
                  and (i == len(signal) - 1 or signal[i] >= signal[i + 1])]
    groups = []
    for i in candidates:
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [group[len(group) // 2] for group in groups]


def propose_lines(mask: np.ndarray, *, sigma_px: float | None = None,
                  peak_floor_ratio: float = 0.18,
                  separation_ratio: float = 0.025) -> LineCandidates:
    """Project cleaned 0/255 ink mask and return candidate half-open line boxes.

    Coordinates are analysis canvas; candidate peaks are NOT physical baselines.
    """
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or not mask.size or mask.dtype != np.uint8:
        raise ValueError("nonempty uint8 2-D mask required")
    if max(mask.shape) > MAX_DIMENSION or not np.isin(mask, (0, 255)).all():
        raise ValueError("unqualified binary foreground")
    if not 0 < peak_floor_ratio <= 1 or not 0 < separation_ratio < 0.5:
        raise ValueError("invalid peak parameters")
    h, w = mask.shape
    sigma = float(sigma_px) if sigma_px is not None else min(9.0, max(1.0, h * 0.006))
    if not np.isfinite(sigma) or not 0.5 <= sigma <= 32:
        raise ValueError("invalid sigma")
    density = (mask > 0).sum(axis=1).astype(np.float32) / float(w)
    if not np.any(density):
        return LineCandidates((), (), {"method": METHOD_ID, "peaks": 0,
                                       "candidates": 0, "truncated": 0})
    smooth = cv2.GaussianBlur(density.reshape(-1, 1), (1, 0), sigmaY=sigma,
                              sigmaX=0)[:, 0]
    floor = max(float(smooth.max()) * peak_floor_ratio, float(density.max()) * 0.02)
    choices = [i for i in local_maxima(smooth) if smooth[i] >= floor]
    min_gap = max(6, round(h * separation_ratio))
    chosen = []
    for y in sorted(choices, key=lambda y: (-float(smooth[y]), y)):
        if all(abs(y - existing) >= min_gap for existing in chosen):
            chosen.append(y)
    truncated = max(0, len(chosen) - MAX_PEAKS)
    chosen = sorted(chosen[:MAX_PEAKS])
    boxes = []
    for i, peak in enumerate(chosen):
        lo = 0 if i == 0 else chosen[i - 1]
        hi = h - 1 if i == len(chosen) - 1 else chosen[i + 1]
        if i:
            lo += int(np.argmin(smooth[lo:peak + 1]))
        if i != len(chosen) - 1:
            hi = peak + int(np.argmin(smooth[peak:hi + 1]))
        ys = np.flatnonzero((mask[lo:hi + 1] != 0).any(axis=1))
        if not ys.size:
            continue
        y1, y2 = lo + int(ys[0]), lo + int(ys[-1]) + 1
        xs = np.flatnonzero((mask[y1:y2] != 0).any(axis=0))
        if xs.size:
            boxes.append(Box(int(xs[0]), y1, int(xs[-1] - xs[0] + 1), y2 - y1))
    return LineCandidates(tuple(boxes), tuple(chosen), {
        "method": METHOD_ID, "peaks": len(chosen),
        "candidates": len(boxes), "truncated": truncated})


__all__ = ["METHOD_ID", "LineCandidates", "propose_lines"]
