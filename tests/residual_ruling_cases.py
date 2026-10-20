"""Rights-safe synthetic page, ruling, and pen-mask annotations (Issue #92).

All pixels are programmatically created OpenCV shapes, never handwriting photos.
"""
from __future__ import annotations

import cv2
import numpy as np

from princess_graphology.models import Box


def _bounds(mask: np.ndarray) -> Box | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return Box(int(xs.min()), int(ys.min()),
               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def residual_page(*, tabletop=False, tilted=False, writing=True,
                  near_edge=False, ink="black", ruling="gray"):
    """Return synthetic image plus independent ink/ruling masks and ROI labels."""
    h, w = 520, 760
    x0, y0, x1, y1 = (52, 42, 707, 478) if tabletop else (8, 6, 751, 513)
    canvas = np.full((h, w, 3), (168, 153, 133) if tabletop else (249, 249, 249), np.uint8)
    if tabletop:
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (249, 249, 249), -1)
    ruling_mask = np.zeros((h, w), np.uint8)
    ruling_colors = {"gray": (198, 198, 198), "blue": (237, 210, 184),
                     "dark": (70, 70, 70), "none": None}
    color = ruling_colors[ruling]
    if color is not None:
        for y in (y0 + 75, y0 + 235, y0 + 370):
            cv2.line(canvas, (x0, y), (x1, y), color, 2)
            cv2.line(ruling_mask, (x0, y), (x1, y), 255, 2)
    pen_mask = np.zeros((h, w), np.uint8)
    word_boxes = []
    if writing:
        pen_y = y0 + (35 if near_edge else 185)
        for value, x in zip(("ONE", "TWO", "THREE"), (x0 + 24, x0 + 205, x0 + 389)):
            cv2.putText(pen_mask, value, (x, pen_y),
                        cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.15, 255, 3, cv2.LINE_AA)
            word_mask = np.zeros((h, w), np.uint8)
            cv2.putText(word_mask, value, (x, pen_y),
                        cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.15, 255, 3, cv2.LINE_AA)
            word_boxes.append(_bounds(word_mask))
        palette = {"black": (20, 20, 20), "blue": (135, 48, 24),
                   "same": color if color is not None else (70, 70, 70)}
        canvas[pen_mask > 0] = palette[ink]
    paper_corners = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    if tilted:
        source = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        target = np.float32([[6, 8], [w - 17, 22], [w - 4, h - 19], [18, h - 1]])
        matrix = cv2.getPerspectiveTransform(source, target)
        canvas = cv2.warpPerspective(canvas, matrix, (w, h), borderValue=(248, 248, 248))
        pen_mask = cv2.warpPerspective(pen_mask, matrix, (w, h), flags=cv2.INTER_NEAREST)
        ruling_mask = cv2.warpPerspective(ruling_mask, matrix, (w, h), flags=cv2.INTER_NEAREST)
        paper_corners = cv2.perspectiveTransform(paper_corners[None], matrix)[0]
        if writing:
            mapped = []
            for box in word_boxes:
                quad = np.float32([[box.x, box.y], [box.x2, box.y],
                                   [box.x2, box.y2], [box.x, box.y2]])
                points = cv2.perspectiveTransform(quad[None], matrix)[0]
                left, top = np.floor(points.min(axis=0)).astype(int)
                right, bottom = np.ceil(points.max(axis=0)).astype(int)
                lx, ty = max(0, int(left)), max(0, int(top))
                mapped.append(Box(lx, ty, min(w, int(right)) - lx,
                                  min(h, int(bottom)) - ty))
            word_boxes = mapped
    return canvas, {
        "page_polygon": paper_corners,
        "ink_mask": pen_mask,
        "ruling_mask": ruling_mask,
        "observed_foreground": cv2.bitwise_or(ruling_mask, pen_mask),
        "true_line": _bounds(pen_mask),
        "true_words": tuple(word_boxes),
        "synthetic_only": True,
    }
