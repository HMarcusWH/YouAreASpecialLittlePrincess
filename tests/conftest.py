from dataclasses import replace

import cv2
import numpy as np
import pytest

from princess_graphology.context import build_measurement_context
from princess_graphology.models import Box


@pytest.fixture
def page():
    image = np.full((300, 700), 245, np.uint8)
    for i, text in enumerate(['special little princess', 'handwriting analysis', 'deterministic measurements']):
        cv2.putText(image, text, (25, 70 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 20, 2, cv2.LINE_AA)
    return image


def context(mask=None, *, shape=(120, 240), lines=(), words=(), xheight=10.0, gray=None):
    if mask is None:
        mask = np.zeros(shape, np.uint8)
    if gray is None:
        gray = np.where(mask, 20, 245).astype(np.uint8)
    ctx = build_measurement_context(gray, mask, lines=lines, words=words)
    return replace(ctx, x_height_px=xheight, x_height_missing_reason=None if xheight else 'test_missing')


def values(measurements):
    return {m.feature_id: m.raw_value for m in measurements}


def records(measurements):
    return {m.feature_id: m for m in measurements}


def rectangle_mask(boxes, shape=(120, 240)):
    mask = np.zeros(shape, np.uint8)
    for b in boxes:
        mask[b.y:b.y2, b.x:b.x2] = 255
    return mask


__all__ = ['Box', 'context', 'values', 'records', 'rectangle_mask']
