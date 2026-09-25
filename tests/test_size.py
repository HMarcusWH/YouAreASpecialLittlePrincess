from dataclasses import replace

import numpy as np
import pytest

from princess_graphology.context import build_measurement_context, estimate_x_height
from princess_graphology.measurements.size import measure_size
from conftest import Box, context, rectangle_mask, values


def test_mode_rejects_punctuation_and_tall_outliers():
    boxes = tuple([Box(10 + 10*i, 30, 5, 12) for i in range(8)] +
                  [Box(100, 20, 5, 24), Box(120, 20, 5, 28), Box(130, 50, 2, 2)])
    mask = rectangle_mask(boxes)
    ctx = build_measurement_context(np.where(mask, 10, 255).astype(np.uint8), mask)
    assert ctx.x_height_px == 12
    assert len(ctx.x_height_indices) == 8
    assert not ctx.mask.flags.writeable
    assert not ctx.gray.flags.writeable
    assert not ctx.labels.flags.writeable
    assert values(measure_size(ctx))['GLYPH_HEIGHT_MEAN'] > 12


def test_sparse_and_ambiguous_modes_are_missing():
    boxes = [Box(i*10, 0, 5, 12) for i in range(5)]
    assert estimate_x_height(boxes, tuple(range(5)))[0] is None
    boxes = [Box(i*10, 0, 5, 12 if i < 6 else 24) for i in range(12)]
    assert estimate_x_height(boxes, tuple(range(12)))[2] == 'ambiguous_component_height_modes'


def test_large_component_set_no_quadratic_memory():
    boxes = [Box(i*10, 0, 5, 12) for i in range(20000)]
    height, selected, _ = estimate_x_height(boxes, tuple(range(len(boxes))))
    assert height == 12 and len(selected) == 20000


@pytest.mark.parametrize('height', [0, -1, float('nan'), float('inf'), True])
def test_invalid_normalizer_rejected(height):
    with pytest.raises(ValueError):
        replace(context(), x_height_px=height)


def test_no_components_no_fake_size():
    assert all(m.raw_value is None for m in measure_size(context(xheight=None)))
