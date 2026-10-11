"""Qualified deterministic connected-ink line and geometric word-group candidates.

Never asserts that whitespace groups correspond to linguistic words. All
diagnostics are bounded integer counts and method IDs, not raw user pixels.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .models import Box
from .segmentation import attach_words, detect_words, filter_word_proposals
from .segmentation_words import propose_words

MAX_SIDE = 3000
MAX_LINES = 128
MAX_GROUPS = 4096


@dataclass(frozen=True)
class LineSelection:
    mask: np.ndarray
    lines: tuple[Box, ...]
    status: str
    diagnostics: dict


@dataclass(frozen=True)
class WordSelection:
    boxes: tuple[Box, ...]
    status: str
    diagnostics: dict


def qualified_lines(mask: np.ndarray) -> LineSelection:
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.uint8 or not mask.size:
        raise ValueError("qualified lines require a nonempty binary uint8 mask")
    if max(mask.shape) > MAX_SIDE or not np.isin(mask, (0, 255)).all():
        raise ValueError("unqualified/oversized line candidate image")
    h, w = mask.shape
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    accepted, excluded = [], 0
    for index in range(1, num):
        x, y, cw, ch, area = (int(v) for v in stats[index, :5])
        if area < 5 or (cw <= 2 and ch <= 2):
            excluded += 1
            continue
        # An entire horizontal/vertical page rule is not a character.
        if ((cw > 0.55 * w and ch < max(8, 0.025 * h))
                or (ch > 0.55 * h and cw < max(8, 0.025 * w))
                or (cw > 0.93 * w and ch > 0.25 * h)
                or area > 0.1 * mask.size):
            excluded += 1
            continue
        accepted.append((index, Box(x, y, cw, ch), area, float(centroids[index, 1])))
    if not accepted:
        return LineSelection(np.zeros_like(mask), (), "unavailable",
                             {"components": num - 1, "rejected_components": excluded,
                              "accepted_components": 0, "accepted_lines": 0})
    heights = [b.height for _, b, _, _ in accepted if b.height >= 5]
    median_h = float(np.median(heights)) if heights else 12.
    max_center_gap = max(9., min(55., median_h * 0.95))
    groups: list[list[tuple[int, Box, int, float]]] = []
    for item in sorted(accepted, key=lambda row: (row[3], row[1].x)):
        if not groups or item[3] - np.median([v[3] for v in groups[-1]]) > max_center_gap:
            groups.append([item])
        else:
            groups[-1].append(item)
    if len(groups) > MAX_LINES * 3:
        return LineSelection(np.zeros_like(mask), (), "ambiguous",
                             {"components": num - 1, "rejected_components": excluded,
                              "accepted_components": len(accepted), "accepted_lines": 0})
    retained = np.zeros_like(mask)
    boxes = []
    unqualified = 0
    for group in groups:
        x1 = min(item[1].x for item in group)
        y1 = min(item[1].y for item in group)
        x2 = max(item[1].x2 for item in group)
        y2 = max(item[1].y2 for item in group)
        # Text must have observed compact-ink support, not just long lines.
        area = sum(item[2] for item in group)
        substantial = sum(item[1].height >= 5 and item[2] >= 15 for item in group)
        if (x2 - x1 < 12 or y2 - y1 < 5 or area < 25
                or not (substantial >= 2 or (substantial == 1 and area >= 75))):
            unqualified += 1
            continue
        row_ink = np.count_nonzero(mask[y1:y2, x1:x2], axis=1)
        if (max(row_ink, default=0) > 0.93 * (x2 - x1)
                and y2 - y1 < max(9, h * 0.025)):
            unqualified += 1
            continue
        for index, _, _, _ in group:
            retained[labels == index] = 255
        boxes.append(Box(x1, y1, x2 - x1, y2 - y1))
    boxes.sort(key=lambda b: (b.y, b.x))
    if len(boxes) > MAX_LINES:
        return LineSelection(np.zeros_like(mask), (), "ambiguous",
                             {"components": num - 1, "rejected_components": excluded,
                              "accepted_components": len(accepted), "accepted_lines": 0})
    return LineSelection(retained, tuple(boxes), "qualified" if boxes else "unavailable",
                         {"components": num - 1, "rejected_components": excluded,
                          "accepted_components": len(accepted), "rejected_line_groups": unqualified,
                          "accepted_lines": len(boxes)})


def qualified_words(gray: np.ndarray, mask: np.ndarray,
                    lines: tuple[Box, ...]) -> WordSelection:
    """Combine scale-aware WordDetector diagnostics with conservative ink gaps.

    Where detector groups are unverifiable, return unavailable rather than a
    factual zero. Geometric groups are an explicit proxy, not OCR words.
    """
    if not lines:
        return WordSelection((), "unavailable", {"accepted_words": 0, "reason": "no_qualified_lines"})
    height = float(np.median([line.height for line in lines]))
    factor = min(2.0, max(0.5, 32.0 / max(8., height)))
    traces: dict[str, int | float | str] = {"normalized_scale": round(factor, 4)}
    if factor != 1.:
        target = (max(1, int(round(gray.shape[1] * factor))),
                  max(1, int(round(gray.shape[0] * factor))))
        proposal = cv2.resize(gray, target, interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
    else:
        proposal = gray
    raw = detect_words(proposal, diagnostics=traces, retrieval='list')
    if factor != 1.:
        resized = []
        from .segmentation import WordDetection
        for item in raw:
            b = item.box
            x1, y1 = max(0, int(b.x / factor)), max(0, int(b.y / factor))
            x2, y2 = min(mask.shape[1], int(np.ceil(b.x2 / factor))), min(mask.shape[0], int(np.ceil(b.y2 / factor)))
            if x2 > x1 and y2 > y1:
                resized.append(WordDetection(Box(x1, y1, x2 - x1, y2 - y1), item.score))
        raw = resized
    filtered = filter_word_proposals(raw, gray.shape, diagnostics=traces)
    detector_boxes, _ = attach_words([item.box for item in filtered], lines, mask, diagnostics=traces)
    shadow = propose_words(mask, lines)
    if shadow.diagnostics["truncated"]:
        return WordSelection((), "ambiguous", {**traces, "gap_candidates": len(shadow.boxes),
                                               "reason": "word_candidate_cap"})
    # Gaps are candidate *groups*, not linguistic word labels. Reject tiny
    # remnants and clearly massive boxes before admitting geometric counts.
    groups = [box for box in shadow.boxes if box.width >= 6 and box.height >= 4
              and box.area >= 20 and box.width <= 0.97 * mask.shape[1]]
    if len(groups) > MAX_GROUPS or any(sum(1 for b in groups if b.y < ln.y2 and b.y2 > ln.y)
                                      > 96 for ln in lines):
        return WordSelection((), "ambiguous", {**traces, "gap_candidates": len(groups),
                                               "reason": "implausible_word_groups"})
    accepted, _ = attach_words(groups, lines, mask)
    diagnostics = {**traces, "gap_candidates": len(shadow.boxes),
                   "accepted_geometry_groups": len(accepted),
                   "detector_accepted_groups": len(detector_boxes)}
    if not accepted:
        return WordSelection((), "unavailable", {**diagnostics, "reason": "no_qualified_word_groups"})
    return WordSelection(accepted, "qualified", diagnostics)
