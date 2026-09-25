import numpy as np
import pytest

from princess_graphology import GraphologyEngine
from princess_graphology.measurements.quality import measure_quality
from conftest import context, values


def test_acquisition_dimensions_not_downsampled_canvas(page):
    r = GraphologyEngine(max_dimension=350, deskew_enabled=False).analyze(page)
    m = r.measurements
    assert m['IMG_WIDTH_PX'].raw_value == 700
    assert m['IMG_HEIGHT_PX'].raw_value == 300
    assert r.width == 350 and r.height == 150
    assert m['IMG_MEGAPIXELS'].raw_value == pytest.approx(.21)
    assert m['IMG_ASPECT_RATIO'].raw_value == pytest.approx(7/3)
    forward = np.asarray(r.metadata['original_to_analysis'])
    inverse = np.asarray(r.metadata['analysis_to_original'])
    assert np.allclose(inverse @ forward, np.eye(3))
    assert m['IMG_WIDTH_PX'].confidence == 1
    assert m['IMG_ROTATION_DEG'].confidence is None


def test_undefined_advanced_quality_not_emitted():
    m = values(measure_quality(context()))
    assert 'IMG_GLARE_SCORE' not in m
    assert 'IMG_QUALITY_OVERALL' not in m
