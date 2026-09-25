import cv2
import numpy as np
from princess_graphology import GraphologyEngine
from princess_graphology.comparison import mahalanobis_distance, baseline_profile
from princess_graphology.segmentation import detect_words

def synthetic_page():
    image = np.full((300, 700), 245, np.uint8)
    for i, text in enumerate(["special little princess", "handwriting analysis", "deterministic measurements"]):
        cv2.putText(image, text, (25, 70 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 20, 2, cv2.LINE_AA)
    return image

def test_engine_smoke():
    result = GraphologyEngine().analyze(synthetic_page())
    assert result.measurements["LINE_COUNT"].raw_value >= 3
    assert result.measurements["WORD_COUNT"].raw_value >= 3
    assert "INK_DARKNESS_MEAN" in result.measurements
    assert "BASELINE_ANGLE_MEAN" in result.measurements

def test_word_detector_numpy2_compatible():
    assert len(detect_words(synthetic_page(), min_area=30)) > 0

def test_real_mahalanobis():
    samples = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.], [.5, .5]])
    profile = baseline_profile(samples)
    distance = mahalanobis_distance(np.array([.5, .5]), profile["mean"], profile["covariance"])
    assert distance < 1e-6
