"""Hybrid page segmentation.

Line detection starts from horizontal projection runs but merges detached descenders,
punctuation and diacritics. Word proposals use the scale-space detector from
Harald Scheidl's WordDetector (MIT), modernized for NumPy 2.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
import cv2
import numpy as np
from sklearn.cluster import DBSCAN
from .models import Box

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
    if mask.ndim != 2:
        raise ValueError("segment_lines expects a 2-D mask")
    ink = mask > 0
    profile = ink.sum(axis=1)
    threshold = max(1, int(profile.max() * 0.015)) if profile.max() else 1
    raw = _runs(profile > threshold)
    if not raw:
        return []

    bands = []
    for y1, y2 in raw:
        xs = np.where(ink[y1:y2 + 1].any(axis=0))[0]
        if xs.size:
            bands.append(Box(int(xs[0]), y1, int(xs[-1] - xs[0] + 1), int(y2 - y1 + 1)))

    substantial = [b for b in bands if b.height >= min_height]
    fragments = [b for b in bands if b.height < min_height]
    if not substantial:
        substantial, fragments = bands, []

    med_h = float(np.median([b.height for b in substantial])) if substantial else float(min_height)
    for f in fragments:
        best, best_gap = None, 1e9
        for i, b in enumerate(substantial):
            gap = max(0, max(b.y - f.y2, f.y - b.y2))
            x_overlap = max(0, min(b.x2, f.x2) - max(b.x, f.x))
            overlap_ratio = x_overlap / max(1, min(b.width, f.width))
            if gap <= med_h * merge_gap_ratio and overlap_ratio > 0.05 and gap < best_gap:
                best, best_gap = i, gap
        if best is not None:
            b = substantial[best]
            x1, y1 = min(b.x, f.x), min(b.y, f.y)
            x2, y2 = max(b.x2, f.x2), max(b.y2, f.y2)
            substantial[best] = Box(x1, y1, x2 - x1, y2 - y1)

    return sorted(substantial, key=lambda b: b.y)

def _kernel(kernel_size: int, sigma: float, theta: float):
    if kernel_size % 2 != 1:
        raise ValueError("kernel_size must be odd")
    half = kernel_size // 2
    xs = ys = np.linspace(-half, half, kernel_size)
    x, y = np.meshgrid(xs, ys)
    sigma_y = float(sigma)
    sigma_x = sigma_y * float(theta)
    exp_term = np.exp(-x ** 2 / (2 * sigma_x) - y ** 2 / (2 * sigma_y))
    x_term = (x ** 2 - sigma_x ** 2) / (2 * np.pi * sigma_x ** 5 * sigma_y)
    y_term = (y ** 2 - sigma_y ** 2) / (2 * np.pi * sigma_y ** 5 * sigma_x)
    kernel = (x_term + y_term) * exp_term
    total = kernel.sum()
    return kernel / total if abs(total) > 1e-12 else kernel

def detect_words(gray: np.ndarray, kernel_size: int = 25, sigma: float = 11.0,
                 theta: float = 7.0, min_area: int = 80):
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    kernel = _kernel(kernel_size, sigma, theta)
    filtered = cv2.filter2D(gray, -1, kernel, borderType=cv2.BORDER_REPLICATE).astype(np.uint8)
    thresholded = 255 - cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    contours = cv2.findContours(thresholded, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]
    result = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w >= 3 and h >= 3:
            result.append(WordDetection(Box(int(x), int(y), int(w), int(h)), float(area)))
    return result

def filter_word_proposals(words, image_shape):
    if not words:
        return []
    h, w = image_shape[:2]
    heights = np.array([x.box.height for x in words], dtype=float)
    widths = np.array([x.box.width for x in words], dtype=float)
    mh, mw = max(3.0, float(np.median(heights))), max(3.0, float(np.median(widths)))
    result = []
    for item in words:
        b = item.box
        tiny = b.height < 0.22 * mh and b.width < 0.22 * mw
        impossible = b.width > 0.98 * w or b.height > 0.5 * h
        if not tiny and not impossible:
            result.append(item)
    return result
