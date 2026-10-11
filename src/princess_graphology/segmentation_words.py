"""Conservative connected-ink gap *candidate* grouping, shadow/evaluation only.

A gap is geometric whitespace, not evidence of a linguistic word.
Do not use this module in Free analysis without licensed real-data validation.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .models import Box

METHOD_ID = "ink_gap_groups_shadow_v1"
MAX_DIMENSION = 3000
MAX_WORDS = 4096


@dataclass(frozen=True)
class WordCandidates:
    boxes: tuple[Box, ...]
    line_indices: tuple[int, ...]
    diagnostics: dict[str, int | str]


def _runs(active):
    edges = np.diff(np.pad(active.astype(np.int8), (1, 1)))
    return list(zip(np.flatnonzero(edges == 1).tolist(),
                    np.flatnonzero(edges == -1).tolist()))


def propose_words(mask: np.ndarray, lines: tuple[Box, ...]) -> WordCandidates:
    """Detect candidate ink clusters from conspicuous horizontal whitespace.

    Input mask must already have passed grid-aware preprocessing. All boxes are
    analysis-canvas half-open and assigned to one supplied line by construction.
    """
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.uint8 or not mask.size:
        raise ValueError("nonempty uint8 mask required")
    if max(mask.shape) > MAX_DIMENSION or not np.isin(mask, (0, 255)).all():
        raise ValueError("invalid/oversized foreground mask")
    h, w = mask.shape
    boxes, parents = [], []
    for i, line in enumerate(lines):
        if not isinstance(line, Box) or line.x2 > w or line.y2 > h:
            raise ValueError("line outside mask")
        crop = mask[line.y:line.y2, line.x:line.x2] > 0
        columns = crop.any(axis=0)
        runs = _runs(columns)
        if not runs:
            continue
        widths = [b - a for a, b in runs]
        typical = float(np.median(widths))
        break_threshold = max(6, int(round(1.8 * typical)))
        groups = []
        start, end = runs[0]
        for left, right in runs[1:]:
            if left - end >= break_threshold:
                groups.append((start, end))
                start = left
            end = right
        groups.append((start, end))
        for left, right in groups:
            ys, xs = np.where(crop[:, left:right])
            if xs.size:
                boxes.append(Box(line.x + left + int(xs.min()), line.y + int(ys.min()),
                                 int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
                parents.append(i)
            if len(boxes) >= MAX_WORDS:
                return WordCandidates(tuple(boxes), tuple(parents), {
                    "method": METHOD_ID, "candidates": len(boxes), "truncated": 1})
    return WordCandidates(tuple(boxes), tuple(parents), {
        "method": METHOD_ID, "candidates": len(boxes), "truncated": 0})


__all__ = ["METHOD_ID", "WordCandidates", "propose_words"]
