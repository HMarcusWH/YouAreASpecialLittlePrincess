"""Isolated offline FAST/SIFT descriptor *research* baselines.

This is NOT identity verification, writer attribution or calibrated probability.
No persistent descriptor database, model weights, training, network or Free use.
Independently implemented using public OpenCV APIs (no HAT code imported).
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np

MAX_SIDE = 3000
MAX_KEYPOINTS = 512


@dataclass(frozen=True)
class DescriptorSet:
    descriptors: np.ndarray
    angles: np.ndarray
    method: str

    def __post_init__(self):
        if self.descriptors.ndim != 2 or self.descriptors.shape[1] != 128:
            raise ValueError("expected Nx128 SIFT descriptors")
        if self.angles.shape != (len(self.descriptors),):
            raise ValueError("descriptor/angle mismatch")
        self.descriptors.flags.writeable = False
        self.angles.flags.writeable = False


def angular_distance_deg(a: float, b: float) -> float:
    """Shortest circular separation; 359 and 1 degrees are 2 apart."""
    if not np.isfinite(a) or not np.isfinite(b):
        raise ValueError("nonfinite orientation")
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def extract(image: np.ndarray, *, detector: str = "sift",
            max_keypoints: int = MAX_KEYPOINTS) -> DescriptorSet:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 2 or not image.size:
        raise ValueError("decoded grayscale uint8 image required")
    if max(image.shape) > MAX_SIDE or not 1 <= max_keypoints <= MAX_KEYPOINTS:
        raise ValueError("image/keypoint budget exceeded")
    if detector not in ("sift", "fast_sift"):
        raise ValueError("unsupported detector")
    sift = cv2.SIFT_create(nfeatures=max_keypoints)
    if detector == "fast_sift":
        fast = cv2.FastFeatureDetector_create(threshold=10, nonmaxSuppression=True)
        keypoints = sorted(fast.detect(image), key=lambda k: (-k.response, k.pt[1], k.pt[0]))[:max_keypoints]
    else:
        keypoints = sorted(sift.detect(image), key=lambda k: (-k.response, k.pt[1], k.pt[0]))[:max_keypoints]
    if not keypoints:
        return DescriptorSet(np.zeros((0, 128), np.float32), np.zeros(0, np.float32), detector)
    keypoints, descriptors = sift.compute(image, keypoints)
    if descriptors is None or keypoints is None or len(keypoints) == 0:
        return DescriptorSet(np.zeros((0, 128), np.float32), np.zeros(0, np.float32), detector)
    return DescriptorSet(np.ascontiguousarray(descriptors, dtype=np.float32),
                         np.asarray([k.angle for k in keypoints], dtype=np.float32), detector)


def match_descriptors(query: DescriptorSet, reference: DescriptorSet, *,
                      ratio: float = 0.75, max_angle_diff_deg: float | None = None) -> dict:
    """Lowe-style ratio matches; descriptive counts, not identity confidence.

    Explicitly handle fewer than two reference descriptors. Optional circular
    orientation consistency is evaluated only on keypoints with known angles.
    """
    if not 0 < ratio < 1:
        raise ValueError("invalid match ratio")
    if max_angle_diff_deg is not None and not 0 <= max_angle_diff_deg <= 180:
        raise ValueError("invalid angle threshold")
    nq, nr = len(query.descriptors), len(reference.descriptors)
    if nq == 0 or nr < 2:
        return {"query_n": nq, "reference_n": nr, "matched_n": 0,
                "match_fraction": None, "status": "insufficient_descriptors"}
    matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    neighbor_rows = matcher.knnMatch(query.descriptors, reference.descriptors, k=2)
    matched = 0
    for row in neighbor_rows:
        if len(row) < 2:
            continue
        best, runner_up = row
        if runner_up.distance <= 0 or best.distance >= ratio * runner_up.distance:
            continue
        if max_angle_diff_deg is not None:
            query_angle = float(query.angles[best.queryIdx])
            reference_angle = float(reference.angles[best.trainIdx])
            # FAST descriptors may have angle=-1 (unknown), which is not 359°.
            # Suppress unverifiable orientation instead of treating two unknowns as aligned.
            if (not np.isfinite(query_angle) or not np.isfinite(reference_angle)
                    or not 0 <= query_angle < 360 or not 0 <= reference_angle < 360
                    or angular_distance_deg(query_angle, reference_angle) > max_angle_diff_deg):
                continue
        matched += 1
    return {"query_n": nq, "reference_n": nr, "matched_n": matched,
            "match_fraction": matched / nq, "status": "experimental"}
