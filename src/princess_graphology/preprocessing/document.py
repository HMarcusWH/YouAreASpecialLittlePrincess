"""Optional conservative paper quadrilateral; no fixed crop or OCR.

A source photo remains authoritative. The detected page is optional and may
not justify physical-page metrics unless its contour passes every qualifier.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MAX_SIDE = 3000


@dataclass(frozen=True)
class DocumentFrame:
    gray: np.ndarray
    color: np.ndarray | None
    to_input: np.ndarray
    status: str
    area_fraction: float | None = None

    def diagnostics(self) -> dict:
        return {"version": "document-roi-v1", "status": self.status,
                "area_fraction": self.area_fraction}


def _corners(points: np.ndarray) -> np.ndarray:
    """Clockwise TL, TR, BR, BL independent of contour traversal order."""
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = pts.sum(axis=1)
    diffs = pts[:, 0] - pts[:, 1]
    ordered = np.asarray([pts[np.argmin(sums)], pts[np.argmax(diffs)],
                          pts[np.argmax(sums)], pts[np.argmin(diffs)]], np.float32)
    if np.unique(ordered, axis=0).shape[0] != 4:
        raise ValueError("degenerate paper quadrilateral")
    return ordered


def detect_document(gray: np.ndarray, color: np.ndarray | None = None) -> DocumentFrame:
    """Return rectified page only for a bright, clearly inset quadrilateral.

    This is deliberately conservative: fully framed pages, shadows, uncertain
    edges and near-border handwriting stay unmodified, not forcibly cropped.
    """
    if gray.ndim != 2 or gray.dtype != np.uint8 or not gray.size or max(gray.shape) > MAX_SIDE:
        raise ValueError("document detector requires bounded uint8 grayscale")
    if color is not None and (color.shape != (*gray.shape, 3) or color.dtype != np.uint8):
        raise ValueError("document color/gray misregistration")
    unchanged = DocumentFrame(gray, color, np.eye(3), "not_qualified")
    h, w = gray.shape
    if min(h, w) < 96:
        return unchanged
    smoothed = cv2.GaussianBlur(gray, (7, 7), 0)
    level, binary = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if level <= 0:
        return unchanged
    contours = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area_fraction = float(cv2.contourArea(contour) / (w * h))
        if not 0.35 <= area_fraction <= 0.94:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        try:
            source = _corners(approx)
        except ValueError:
            continue
        xs, ys = source[:, 0], source[:, 1]
        if (np.min(xs) < 0.015 * w or np.max(xs) > 0.985 * w
                or np.min(ys) < 0.015 * h or np.max(ys) > 0.985 * h):
            continue
        edge = np.roll(source, -1, axis=0) - source
        lengths = np.linalg.norm(edge, axis=1)
        if np.min(lengths) < min(w, h) * 0.25:
            continue
        out_w = int(round(max(lengths[0], lengths[2])))
        out_h = int(round(max(lengths[1], lengths[3])))
        if not 96 <= min(out_w, out_h) or max(out_w, out_h) > MAX_SIDE:
            continue
        region = np.zeros_like(gray)
        cv2.fillConvexPoly(region, source.astype(np.int32), 255)
        inside = float(np.median(gray[region > 0]))
        outside = gray[region == 0]
        if not outside.size or inside - float(np.median(outside)) < 18:
            continue
        destination = np.float32([[0, 0], [out_w - 1, 0],
                                  [out_w - 1, out_h - 1], [0, out_h - 1]])
        forward = cv2.getPerspectiveTransform(source, destination)
        if abs(np.linalg.det(forward)) < 1e-12:
            continue
        warped_gray = cv2.warpPerspective(gray, forward, (out_w, out_h),
                                           borderValue=255)
        warped_color = cv2.warpPerspective(color, forward, (out_w, out_h),
                                            borderValue=(255, 255, 255)) if color is not None else None
        return DocumentFrame(warped_gray, warped_color, np.linalg.inv(forward),
                             "qualified", area_fraction)
    return unchanged
