import numpy as np
import pytest

from princess_graphology.measurements.ink import measure_ink, stroke_width_samples
from conftest import Box, context, rectangle_mask, values


def test_darkness_and_saturation():
    mask = rectangle_mask([Box(20, 20, 100, 10)])
    gray = np.full(mask.shape, 255, np.uint8)
    gray[mask > 0] = 51
    m = values(measure_ink(context(mask, gray=gray)))
    assert m['INK_DARKNESS_MEAN'] == pytest.approx(.8)
    assert m['INK_DARKNESS_STD'] == pytest.approx(0, abs=1e-12)
    assert m['INK_DARKNESS_CV'] == pytest.approx(0, abs=1e-12)
    assert m['INK_SATURATION_FRACTION'] == 0
    gray[mask > 0] = 0
    assert values(measure_ink(context(mask, gray=gray)))['INK_SATURATION_FRACTION'] == 1


def test_medial_width_not_all_ink_radius_average():
    mask = rectangle_mask([Box(20, 20, 160, 10)])
    widths = stroke_width_samples(mask)
    assert np.median(widths) == pytest.approx(10, abs=1)
    assert np.mean(widths) > 8.5  # All-foreground averaging gives approximately 6.
    doubled = np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1)
    assert np.median(stroke_width_samples(doubled)) == pytest.approx(20, abs=1)
    assert np.array_equal(widths, stroke_width_samples(mask))


def test_zero_darkness_cv_missing_not_infinity():
    mask = rectangle_mask([Box(20, 20, 100, 10)])
    m = values(measure_ink(context(mask, gray=np.full(mask.shape, 255, np.uint8))))
    assert m['INK_DARKNESS_MEAN'] == 0
    assert m['INK_DARKNESS_CV'] is None


def test_widths_are_proxies_never_pressure():
    measurements = measure_ink(context(rectangle_mask([Box(20, 20, 100, 10)])))
    assert all(m.evidence_status == 'COMPUTATIONAL_PROXY' for m in measurements)
    assert not any('PRESSURE' in m.feature_id for m in measurements)
