"""Rights-safe synthetic ruling/page/background fixtures. Never real handwriting."""
from __future__ import annotations

import cv2
import numpy as np


def page(*, ruling="gray", pen="blue", text=True, background=False,
         near_edge=False, perspective=False, width=760, height=520):
    """Return BGR source, exact pen pixel mask and labelled line/word boxes.

    Synthetic OpenCV shapes are engineering fixtures, not real-writer evidence.
    """
    if background:
        canvas = np.full((height, width, 3), (176, 164, 148), np.uint8)
        x0, y0, x1, y1 = 55, 40, width - 45, height - 48
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (250, 250, 250), -1)
    else:
        canvas = np.full((height, width, 3), 250, np.uint8)
        x0, y0, x1, y1 = 0, 0, width - 1, height - 1
    colors = {"gray": (207, 207, 207), "blue": (235, 209, 186),
              "black": (48, 48, 48), "none": None}
    grid = colors[ruling]
    if grid is not None:
        for x in range(x0 + 24, x1 - 5, 40):
            cv2.line(canvas, (x, y0), (x, y1), grid, 1)
        for y in range(y0 + 24, y1 - 5, 40):
            cv2.line(canvas, (x0, y), (x1, y), grid, 1)
    pen_color = {"blue": (140, 57, 28), "black": (20, 20, 20),
                 "same": (48, 48, 48)}[pen]
    pen_mask = np.zeros((height, width), np.uint8)
    boxes = []
    if text:
        y = y0 + (46 if near_edge else (y1 - y0) // 2)
        anchors = (x0 + 58, x0 + 205, x0 + 350)
        for word, x in zip(("HEY", "YOU", "ARE"), anchors):
            cv2.putText(pen_mask, word, (x, y), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
                        1.2, 255, 3, cv2.LINE_AA)
            (tw, th), baseline = cv2.getTextSize(word, cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.2, 3)
            boxes.append((x - 3, y - th - 4, tw + 6, th + baseline + 7))
        canvas[pen_mask > 0] = pen_color
    if perspective:
        src = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        dst = np.float32([[13, 4], [width - 15, 20], [width - 1, height - 12], [6, height - 1]])
        h = cv2.getPerspectiveTransform(src, dst)
        canvas = cv2.warpPerspective(canvas, h, (width, height), borderValue=(247, 247, 247))
        pen_mask = cv2.warpPerspective(pen_mask, h, (width, height), flags=cv2.INTER_NEAREST)
    return canvas, pen_mask, tuple(boxes)


def grid_only(*, ruling="gray", background=False):
    return page(ruling=ruling, text=False, background=background)
