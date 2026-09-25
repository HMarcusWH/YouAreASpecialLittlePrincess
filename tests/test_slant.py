import cv2
import numpy as np
import pytest

from princess_graphology.measurements.slant import axis_slant, measure_slant
from conftest import context, values


def bars():
    mask = np.zeros((100, 240), np.uint8)
    for x in (30, 80, 130, 180):
        cv2.line(mask, (x, 80), (x+20, 20), 255, 3)
    return mask


def test_axis_direction_invariance():
    assert axis_slant(1., -3.) == pytest.approx(axis_slant(-1., 3.))
    assert axis_slant(1., -3.) > 0


def test_mirror_flips_slant_and_fraction_partition():
    a = values(measure_slant(context(bars())))
    b = values(measure_slant(context(np.fliplr(bars()))))
    assert a['SLANT_ANGLE_MEAN'] > 10
    assert a['SLANT_ANGLE_MEAN'] == pytest.approx(-b['SLANT_ANGLE_MEAN'], abs=.01)
    assert a['SLANT_RIGHT_FRACTION'] == b['SLANT_LEFT_FRACTION'] == 1
    assert sum(a[k] for k in ('SLANT_LEFT_FRACTION', 'SLANT_VERTICAL_FRACTION', 'SLANT_RIGHT_FRACTION')) == 1
    assert a['SLANT_P05'] <= a['SLANT_P95']


def test_round_component_axis_is_not_stroke_slant():
    mask = np.zeros((100, 100), np.uint8)
    cv2.circle(mask, (50, 50), 12, 255, 2)
    assert values(measure_slant(context(mask)))['SLANT_ANGLE_MEAN'] is None
