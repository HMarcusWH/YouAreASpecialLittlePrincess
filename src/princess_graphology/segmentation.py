"""Hybrid line segmentation and WordDetector-derived word proposals (MIT).

Proposal scores are contour areas, NOT calibrated probabilities. See provenance.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .models import Box


def _bump(diagnostics, name):
    diagnostics[name] = diagnostics.get(name, 0) + 1


@dataclass
class WordDetection:
    box: Box
    score: float = 1.0


def _runs(active):
    out, start = [], None
    for i, value in enumerate(active):
        if value and start is None:
            start = i
        elif not value and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(active) - 1))
    return out


def segment_lines(mask: np.ndarray, min_height: int = 8, merge_gap_ratio: float = 0.45):
    if mask.ndim != 2 or not mask.size:
        raise ValueError('segment_lines expects a nonempty 2-D mask')
    ink = mask > 0
    profile = ink.sum(axis=1)
    threshold = max(1, int(profile.max() * 0.015)) if profile.max() else 1
    bands = []
    for y1, y2 in _runs(profile > threshold):
        xs = np.where(ink[y1:y2 + 1].any(axis=0))[0]
        if xs.size:
            bands.append(Box(int(xs[0]), y1, int(xs[-1] - xs[0] + 1), y2 - y1 + 1))
    substantial = [b for b in bands if b.height >= min_height]
    fragments = [b for b in bands if b.height < min_height]
    if not substantial:
        substantial, fragments = bands, []
    med_h = float(np.median([b.height for b in substantial])) if substantial else float(min_height)
    for f in fragments:
        best, best_gap = None, float('inf')
        for i, b in enumerate(substantial):
            gap = max(0, b.y - f.y2, f.y - b.y2)
            overlap = max(0, min(b.x2, f.x2) - max(b.x, f.x)) / min(b.width, f.width)
            if gap <= med_h * merge_gap_ratio and overlap > 0.05 and gap < best_gap:
                best, best_gap = i, gap
        if best is not None:
            b = substantial[best]
            x1, y1 = min(b.x, f.x), min(b.y, f.y)
            x2, y2 = max(b.x2, f.x2), max(b.y2, f.y2)
            substantial[best] = Box(x1, y1, x2 - x1, y2 - y1)
    return sorted(substantial, key=lambda b: (b.y, b.x))


def _kernel(kernel_size: int, sigma: float, theta: float):
    if kernel_size % 2 != 1 or kernel_size < 3 or sigma <= 0 or theta <= 0:
        raise ValueError('kernel_size must be odd >=3; sigma and theta must be positive')
    half = kernel_size // 2
    x, y = np.meshgrid(np.linspace(-half, half, kernel_size), np.linspace(-half, half, kernel_size))
    sigma_y, sigma_x = float(sigma), float(sigma * theta)
    # Retain the selected upstream detector response in this schema-focused PR.
    exp_term = np.exp(-x ** 2 / (2 * sigma_x) - y ** 2 / (2 * sigma_y))
    x_term = (x ** 2 - sigma_x ** 2) / (2 * np.pi * sigma_x ** 5 * sigma_y)
    y_term = (y ** 2 - sigma_y ** 2) / (2 * np.pi * sigma_y ** 5 * sigma_x)
    kernel = (x_term + y_term) * exp_term
    total = kernel.sum()
    return kernel / total if abs(total) > 1e-12 else kernel


def detect_words(gray: np.ndarray, kernel_size: int = 25, sigma: float = 11.0,
                 theta: float = 7.0, min_area: int = 80, *, diagnostics=None):
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    filtered = cv2.filter2D(gray, -1, _kernel(kernel_size, sigma, theta), borderType=cv2.BORDER_REPLICATE)
    thresholded = 255 - cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    contours = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    result = []
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        if area >= min_area and w >= 3 and h >= 3:
            result.append(WordDetection(Box(int(x), int(y), int(w), int(h)), float(area)))
        elif diagnostics is not None:
            _bump(diagnostics, "reject_low_area_or_extent")
    if diagnostics is not None:
        diagnostics["raw_contours"] = len(contours)
        diagnostics["raw_proposals"] = len(result)
    return result


def filter_word_proposals(words, image_shape, *, diagnostics=None):
    if not words:
        if diagnostics is not None:
            diagnostics["after_geometry_filter"] = 0
        return []
    h, w = image_shape[:2]
    mh = max(3.0, float(np.median([x.box.height for x in words])))
    mw = max(3.0, float(np.median([x.box.width for x in words])))
    accepted = []
    for item in words:
        if item.box.height < 0.22 * mh and item.box.width < 0.22 * mw:
            if diagnostics is not None:
                _bump(diagnostics, "reject_small_relative_proposal")
        elif item.box.width > 0.98 * w or item.box.height > 0.5 * h:
            if diagnostics is not None:
                _bump(diagnostics, "reject_oversized_proposal")
        else:
            accepted.append(item)
    if diagnostics is not None:
        diagnostics["after_geometry_filter"] = len(accepted)
    return accepted


def attach_words(words, lines, mask, *, diagnostics=None):
    """Require vertical overlap; trim detector halos and suppress nested duplicates."""
    candidates = []
    for word in words:
        overlaps = [max(0, min(word.y2, b.y2) - max(word.y, b.y)) / min(word.height, b.height)
                    for b in lines]
        matching = [i for i, overlap in enumerate(overlaps) if overlap >= 0.5]
        if len(matching) != 1:
            if diagnostics is not None:
                _bump(diagnostics, "reject_no_unique_line" if not matching else "reject_ambiguous_lines")
            continue  # no nearest-line guessing, or ambiguous cross-line proposal
        i = matching[0]
        b = lines[i]
        x1, y1, x2, y2 = max(word.x, b.x), max(word.y, b.y), min(word.x2, b.x2), min(word.y2, b.y2)
        if x2 <= x1 or y2 <= y1:
            if diagnostics is not None:
                _bump(diagnostics, "reject_empty_line_intersection")
            continue
        ys, xs = np.where(mask[y1:y2, x1:x2] > 0)
        if xs.size:
            candidates.append((i, Box(x1 + int(xs.min()), y1 + int(ys.min()),
                                      int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))))
        elif diagnostics is not None:
            _bump(diagnostics, "reject_no_ink_in_crop")
    unique_candidates = set(candidates)
    if diagnostics is not None:
        diagnostics["reject_exact_duplicate"] = len(candidates) - len(unique_candidates)
    kept = []
    for i, b in sorted(unique_candidates, key=lambda p: (-p[1].area, p[0], p[1].x, p[1].y)):
        if not any(i == j and c.x <= b.x and c.y <= b.y and c.x2 >= b.x2 and c.y2 >= b.y2 for j, c in kept):
            kept.append((i, b))
        elif diagnostics is not None:
            _bump(diagnostics, "reject_nested_duplicate")
    kept.sort(key=lambda p: (p[0], p[1].x, p[1].y))
    if diagnostics is not None:
        diagnostics["accepted_words"] = len(kept)
    return tuple(b for _, b in kept), tuple(i for i, _ in kept)
