from __future__ import annotations
import cv2
import numpy as np
from .models import Measurement, Box

def _stats(values):
    a = np.asarray(list(values), dtype=float)
    if a.size == 0:
        return None, None, None, 0
    return float(np.mean(a)), float(np.median(a)), float(np.std(a)), int(a.size)

def _confidence(n, cv=None, target=20):
    nf = min(1.0, n / max(1, target))
    cf = 1.0 if cv is None else float(np.clip(1.0 - cv, 0.0, 1.0))
    return float(np.clip(0.35 + 0.35 * nf + 0.30 * cf, 0.0, 0.98))

def measure_layout(mask, lines, words):
    h, w = mask.shape[:2]
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return []
    return [
        Measurement("PAGE_MARGIN_LEFT", float(xs.min() / w), "page_ratio", method_version="ink_bounds_v1"),
        Measurement("PAGE_MARGIN_RIGHT", float((w - 1 - xs.max()) / w), "page_ratio", method_version="ink_bounds_v1"),
        Measurement("PAGE_MARGIN_TOP", float(ys.min() / h), "page_ratio", method_version="ink_bounds_v1"),
        Measurement("PAGE_MARGIN_BOTTOM", float((h - 1 - ys.max()) / h), "page_ratio", method_version="ink_bounds_v1"),
        Measurement("INK_COVERAGE_RATIO", float(np.count_nonzero(mask) / mask.size), "ratio", method_version="binary_ink_ratio_v1"),
        Measurement("LINE_COUNT", len(lines), "count", n_observations=len(lines), method_version="hybrid_line_segment_v1"),
        Measurement("WORD_COUNT", len(words), "count", n_observations=len(words), method_version="scale_space_words_v1"),
    ]

def measure_baseline(mask, lines):
    angles, residuals, regions = [], [], []
    for idx, line in enumerate(lines):
        crop = line.crop(mask)
        xs, ys = [], []
        step = max(1, line.width // 50)
        for cx in range(0, line.width, step):
            ink = np.where(crop[:, cx] > 0)[0]
            if ink.size:
                xs.append(line.x + cx)
                ys.append(line.y + float(np.percentile(ink, 82)))
        if len(xs) < 6:
            continue
        x, y = np.asarray(xs, float), np.asarray(ys, float)
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept
        angles.append(float(-np.degrees(np.arctan(slope))))
        residuals.append(float(np.std(y - predicted)))
        regions.append(f"line_{idx}")
    mean, median, std, n = _stats(angles)
    if n == 0:
        return []
    conf = _confidence(n, std / (abs(mean) + 1.0), 5)
    waviness = float(np.mean(residuals)) if residuals else None
    return [
        Measurement("BASELINE_ANGLE_MEAN", mean, "degrees", confidence=conf, n_observations=n, std_dev=std, method_version="baseline_bottom_quantile_regression_v1", source_regions=regions),
        Measurement("BASELINE_ANGLE_MEDIAN", median, "degrees", confidence=conf, n_observations=n, method_version="baseline_bottom_quantile_regression_v1", source_regions=regions),
        Measurement("BASELINE_ANGLE_STD", std, "degrees", confidence=conf, n_observations=n, method_version="baseline_bottom_quantile_regression_v1", source_regions=regions),
        Measurement("BASELINE_WAVINESS", waviness, "pixels", confidence=conf, n_observations=n, method_version="baseline_residual_std_v1", source_regions=regions),
    ]

def measure_spacing(lines, words):
    out = []
    ordered = sorted(lines, key=lambda b: b.y)
    line_gaps = [max(0, ordered[i + 1].y - ordered[i].y2) for i in range(len(ordered) - 1)]
    mean, _, std, n = _stats(line_gaps)
    if n:
        out += [
            Measurement("LINE_SPACING_MEAN", mean, "pixels", confidence=_confidence(n, std / (mean + 1e-6), 5), n_observations=n, std_dev=std, method_version="line_box_gap_v1"),
            Measurement("LINE_SPACING_STD", std, "pixels", n_observations=n, method_version="line_box_gap_v1"),
        ]

    if lines and words:
        buckets = [[] for _ in lines]
        for word in words:
            cy = word.y + word.height / 2
            idx = min(range(len(lines)), key=lambda i: abs(cy - (lines[i].y + lines[i].height / 2)))
            buckets[idx].append(word)
        gaps = []
        for bucket in buckets:
            bucket = sorted(bucket, key=lambda b: b.x)
            gaps.extend(max(0, bucket[i + 1].x - bucket[i].x2) for i in range(len(bucket) - 1))
        mean, _, std, n = _stats(gaps)
        if n:
            out += [
                Measurement("WORD_SPACING_MEAN", mean, "pixels", confidence=_confidence(n, std / (mean + 1e-6), 15), n_observations=n, std_dev=std, method_version="word_box_gap_v1"),
                Measurement("WORD_SPACING_STD", std, "pixels", n_observations=n, method_version="word_box_gap_v1"),
            ]
    return out

def measure_slant(mask):
    contours = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)[0]
    angles = []
    for contour in contours:
        if len(contour) < 12:
            continue
        _, _, w, h = cv2.boundingRect(contour)
        if h < 8 or h < 0.65 * w:
            continue
        vx, vy, _, _ = cv2.fitLine(contour, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
        angle = float(np.degrees(np.arctan2(abs(vy), vx)) % 180)
        if 45 <= angle <= 135:
            angles.append(angle - 90.0)
    mean, median, std, n = _stats(angles)
    if n == 0:
        return []
    conf = _confidence(n, std / 45.0 if std is not None else None, 40)
    return [
        Measurement("SLANT_ANGLE_MEAN", mean, "degrees_from_vertical", confidence=conf, n_observations=n, std_dev=std, method_version="contour_axis_fit_v1"),
        Measurement("SLANT_ANGLE_MEDIAN", median, "degrees_from_vertical", confidence=conf, n_observations=n, method_version="contour_axis_fit_v1"),
        Measurement("SLANT_ANGLE_STD", std, "degrees", confidence=conf, n_observations=n, method_version="contour_axis_fit_v1"),
    ]

def measure_ink(gray, mask):
    ink = mask > 0
    if not np.any(ink):
        return []
    values = gray[ink].astype(float)
    darkness = 1.0 - float(np.mean(values) / 255.0)
    darkness_std = float(np.std(1.0 - values / 255.0))
    distance = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 5)
    widths = 2.0 * distance[distance > 0]
    sw = float(np.mean(widths)) if widths.size else 0.0
    swstd = float(np.std(widths)) if widths.size else 0.0
    return [
        Measurement("INK_DARKNESS_MEAN", darkness, "score_0_1", n_observations=int(values.size), std_dev=darkness_std, method_version="grayscale_ink_darkness_v1"),
        Measurement("INK_DARKNESS_STD", darkness_std, "score_0_1", n_observations=int(values.size), method_version="grayscale_ink_darkness_v1"),
        Measurement("STROKE_WIDTH_MEAN", sw, "pixels_proxy", n_observations=int(widths.size), std_dev=swstd, method_version="distance_transform_proxy_v1", evidence_status="COMPUTATIONAL_PROXY"),
        Measurement("STROKE_WIDTH_STD", swstd, "pixels_proxy", n_observations=int(widths.size), method_version="distance_transform_proxy_v1", evidence_status="COMPUTATIONAL_PROXY"),
    ]
