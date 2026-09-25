import pytest

from princess_graphology.measurements.segmentation import measure_segmentation
from conftest import Box, context, rectangle_mask, values


def test_area_uses_enclosing_bounds_not_sum_of_overlapping_boxes():
    lines = [Box(20, 20, 100, 20), Box(20, 30, 100, 20)]
    ctx = context(rectangle_mask(lines), lines=lines)
    m = values(measure_segmentation(ctx))
    assert m['PAGE_TEXT_AREA_RATIO'] == pytest.approx(3000/(120*240))
    assert m['PAGE_INK_AREA_RATIO'] == m['PAGE_TEXT_AREA_RATIO']
    assert m['PAGE_LINE_COUNT'] == 2
    assert m['PAGE_COMPONENT_COUNT'] == 1


def test_empty_counts_are_observed_zero():
    measurements = measure_segmentation(context())
    assert all(m.raw_value == 0 for m in measurements)
    assert all(m.n_observations == 1 for m in measurements)
