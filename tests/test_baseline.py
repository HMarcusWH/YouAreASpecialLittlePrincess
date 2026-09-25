import numpy as np
import pytest

from princess_graphology.measurements.baseline import measure_baseline
from conftest import Box, context, values


def trace_context(slopes=(.1, -.1), scale=1, curve=0):
    mask = np.zeros((160*scale, 240*scale), np.uint8)
    lines = []
    for i, slope in enumerate(slopes):
        y0 = 35 + 65*i
        for x in range(20, 220):
            y = round(y0 + slope*(x-20) + curve*((x-120)/100)**2)
            mask[y*scale:(y+2)*scale, x*scale:(x+1)*scale] = 255
        lines.append(Box(20*scale, (y0-25)*scale, 200*scale, 55*scale))
    return context(mask, lines=lines, xheight=10.*scale)


def test_baseline_sign_absolute_angle_not_cancellation():
    m = values(measure_baseline(trace_context()))
    assert abs(m['BASELINE_ANGLE_MEAN']) < .05
    assert m['BASELINE_ABS_SLOPE'] == pytest.approx(np.degrees(np.arctan(.1)), abs=.1)
    assert values(measure_baseline(trace_context((-.1,))))['BASELINE_ANGLE_MEAN'] > 0


def test_flat_baseline():
    m = values(measure_baseline(trace_context((0., 0.))))
    assert m['BASELINE_WAVINESS'] == pytest.approx(0, abs=1e-10)
    assert m['BASELINE_STABILITY'] == pytest.approx(1)
    assert m['BASELINE_CURVATURE'] == pytest.approx(0, abs=1e-10)


def test_curved_baseline_normalization_and_scaling():
    a = values(measure_baseline(trace_context((0.,), curve=10)))
    b = values(measure_baseline(trace_context((0.,), scale=2, curve=10)))
    assert a['BASELINE_WAVINESS'] > .2
    assert a['BASELINE_WAVINESS'] == pytest.approx(b['BASELINE_WAVINESS'], rel=.02)
    assert a['BASELINE_CURVATURE'] == pytest.approx(1, abs=.1)
    assert a['BASELINE_STABILITY'] == pytest.approx(1/(1+a['BASELINE_WAVINESS']))
    assert a['BASELINE_ANGLE_STD'] is None


def test_historical_display_band_uses_canonical_angle_sign():
    from princess_graphology.traditional import baseline_band
    assert baseline_band(1) == 'ascending'
    assert baseline_band(-1) == 'descending'
    assert baseline_band(0) == 'straight'
