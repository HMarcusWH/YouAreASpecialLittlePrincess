import pytest

from princess_graphology.measurements.layout import measure_layout
from conftest import Box, context, values


def test_margin_normalizer_and_half_open_bounds():
    ctx = context(lines=[Box(20, 30, 100, 10), Box(30, 70, 120, 10)], xheight=10.)
    m = values(measure_layout(ctx))
    assert m['MARGIN_LEFT_REL'] == 2
    assert m['MARGIN_RIGHT_REL'] == 9
    assert m['MARGIN_TOP_REL'] == 3
    assert m['MARGIN_BOTTOM_REL'] == 4
    assert m['LINE_LENGTH_MEAN_REL'] == pytest.approx(110/240)
    assert m['MARGIN_LEFT_VARIABILITY'] == pytest.approx(5/25)
    assert m['MARGIN_SYMMETRY'] == pytest.approx(1-70/110)
    assert m['LINE_START_DRIFT'] == pytest.approx((10/240)/(40/120))


def test_layout_scale_invariance():
    lines = [Box(20, 30, 100, 10), Box(30, 70, 120, 10)]
    a = values(measure_layout(context(lines=lines)))
    doubled = [Box(*(2*v for v in b.as_tuple())) for b in lines]
    b = values(measure_layout(context(shape=(240, 480), lines=doubled, xheight=20.)))
    for key in a:
        assert a[key] == pytest.approx(b[key])


def test_no_xheight_only_dependent_metrics_missing():
    m = values(measure_layout(context(lines=[Box(20, 30, 100, 10)], xheight=None)))
    assert m['MARGIN_LEFT_REL'] is None
    assert m['LINE_LENGTH_MEAN_REL'] == pytest.approx(100/240)
    assert m['MARGIN_LEFT_VARIABILITY'] is None
    assert m['LINE_START_DRIFT'] is None


def test_zero_margin_denominator_is_missing():
    m = values(measure_layout(context(lines=[Box(0, 20, 240, 10), Box(0, 50, 240, 10)])))
    assert m['MARGIN_LEFT_REL'] == 0
    assert m['MARGIN_LEFT_VARIABILITY'] is None
    assert m['MARGIN_SYMMETRY'] is None
