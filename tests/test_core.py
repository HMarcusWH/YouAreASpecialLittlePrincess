import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from princess_graphology import GraphologyEngine
from princess_graphology.comparison import baseline_profile, mahalanobis_distance
from princess_graphology.segmentation import detect_words


def test_engine_smoke(page):
    result = GraphologyEngine().analyze(page)
    assert result.measurements['PAGE_LINE_COUNT'].raw_value == 3
    assert result.measurements['PAGE_WORD_COUNT'].raw_value >= 3
    assert result.measurements['INK_DARKNESS_MEAN'].raw_value is not None
    assert result.measurements['BASELINE_ANGLE_MEAN'].raw_value is not None


def test_word_detector_numpy2_compatible(page):
    assert len(detect_words(page, min_area=30)) > 0


def test_real_mahalanobis():
    samples = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.], [.5, .5]])
    profile = baseline_profile(samples)
    assert mahalanobis_distance(np.array([.5, .5]), profile['mean'], profile['covariance']) < 1e-6


def test_deterministic_and_input_not_modified(page):
    before = page.copy()
    a = GraphologyEngine().analyze(page).to_json()
    b = GraphologyEngine().analyze(page).to_json()
    assert a == b
    assert np.array_equal(page, before)


@pytest.mark.parametrize('value', [0, 100, 255])
def test_uniform_no_fake_measurements(value):
    r = GraphologyEngine().analyze(np.full((80, 100), value, np.uint8))
    assert r.width == 100 and r.height == 80
    assert r.measurements['PAGE_LINE_COUNT'].raw_value == 0
    assert r.measurements['PAGE_COMPONENT_COUNT'].raw_value == 0
    for key in ['X_HEIGHT_PX', 'IMG_ROTATION_DEG', 'WORD_SPACING_CV', 'MARGIN_LEFT_REL', 'STROKE_WIDTH_MEAN']:
        assert r.measurements[key].raw_value is None
        assert r.measurements[key].missing_reason
    assert json.loads(r.to_json())


@pytest.mark.parametrize('bad', [np.zeros((0, 5), np.uint8), np.zeros((10, 10), float),
                                 np.zeros((10, 10), np.uint16), np.zeros((10, 10, 2), np.uint8),
                                 np.zeros((10,), np.uint8), [], None])
def test_invalid_inputs(bad):
    with pytest.raises(ValueError):
        GraphologyEngine().analyze(bad)


@pytest.mark.parametrize('size', [0, -1, True, 2.5])
def test_invalid_max_dimension(size):
    with pytest.raises(ValueError):
        GraphologyEngine(max_dimension=size)


def test_alpha_and_file_cli(tmp_path):
    image = np.zeros((30, 40, 4), np.uint8)
    r = GraphologyEngine().analyze(image)
    assert r.measurements['PAGE_INK_AREA_RATIO'].raw_value == 0
    path = tmp_path / 'transparent.png'
    cv2.imwrite(str(path), image)
    result = GraphologyEngine().analyze_file(path)
    assert result.source == str(path)
    run = subprocess.run([sys.executable, '-m', 'princess_graphology.cli', str(path)],
                         check=True, text=True, capture_output=True)
    assert len(json.loads(run.stdout)['measurements']) == 64
    with pytest.raises(FileNotFoundError):
        GraphologyEngine().analyze_file(tmp_path / 'missing.png')
