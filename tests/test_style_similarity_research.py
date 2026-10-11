"""Synthetic descriptor smoke tests, no real handwriting or biometric training."""
import cv2
import numpy as np
import pytest

from evaluation.style_similarity.descriptors import (
    angular_distance_deg, extract, match_descriptors,
)


def test_blank_has_no_descriptors_and_cannot_return_identity_confidence():
    image = np.full((128, 128), 255, np.uint8)
    a = extract(image)
    result = match_descriptors(a, a)
    assert result["status"] == "insufficient_descriptors"
    assert result["match_fraction"] is None
    assert "confidence" not in result and "probability" not in result


def test_fast_sift_and_sift_are_bounded():
    image = np.full((256, 256), 255, np.uint8)
    for i in range(10, 240, 35):
        cv2.circle(image, (i, i), 12, 0, 2)
    for detector in ("fast_sift", "sift"):
        descriptors = extract(image, detector=detector, max_keypoints=64)
        assert descriptors.descriptors.shape[1] == 128
        assert len(descriptors.descriptors) <= 64
        assert not descriptors.descriptors.flags.writeable
        result = match_descriptors(descriptors, descriptors)
        assert result["query_n"] == len(descriptors.descriptors)
        assert 0 <= result["matched_n"] <= result["query_n"]


def test_angles_wrap_and_empty_neighbors():
    assert angular_distance_deg(359, 1) == pytest.approx(2)
    assert angular_distance_deg(10, 190) == pytest.approx(180)
    with pytest.raises(ValueError):
        angular_distance_deg(float("nan"), 0)
    one = extract(np.full((100, 100), 255, np.uint8))
    with pytest.raises(ValueError):
        match_descriptors(one, one, ratio=1.0)


def test_research_code_is_not_imported_in_production_free():
    import inspect
    import princess_graphology.engine as engine
    import princess_graphology.context as context
    assert "style_similarity" not in inspect.getsource(engine)
    assert "style_similarity" not in inspect.getsource(context)



def test_unknown_fast_orientation_never_counts_as_aligned_match():
    from evaluation.style_similarity.descriptors import DescriptorSet
    # Deliberately distinct SIFT rows so nearest and runner-up are unambiguous.
    q = np.zeros((2, 128), np.float32)
    r = np.zeros((3, 128), np.float32)
    q[0, 0] = 1
    q[1, 1] = 1
    r[0] = q[0]
    r[1] = q[1]
    r[2].fill(20)
    query = DescriptorSet(q, np.array([-1, -1], np.float32), "fast_sift")
    reference = DescriptorSet(r, np.array([-1, -1, 10], np.float32), "fast_sift")
    unconstrained = match_descriptors(query, reference)
    oriented = match_descriptors(query, reference, max_angle_diff_deg=15)
    assert unconstrained["matched_n"] >= 1
    assert oriented["matched_n"] == 0
