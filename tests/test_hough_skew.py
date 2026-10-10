"""Regression for OpenCV HoughLinesP shape drift seen on Railway.

OpenCV variants may yield (N, 1, 4), (N, 4), or one flat four-item row.
All must produce the same deterministic skew measurement without killing a job.
"""
from __future__ import annotations

import numpy as np
import pytest

from princess_graphology import GraphologyEngine
from princess_graphology.preprocessing import geometry


@pytest.mark.parametrize("representation", ["wrapped", "flat", "single"])
def test_hough_line_array_shapes_are_normalized(monkeypatch, representation):
    rows = np.asarray([[5, 20, 195, 20], [5, 70, 195, 70]], dtype=np.int32)
    if representation == "wrapped":
        lines = rows.reshape(2, 1, 4)
    elif representation == "flat":
        lines = rows
    else:
        lines = rows[0]
    monkeypatch.setattr(geometry.cv2, "HoughLinesP", lambda *_a, **_kw: lines)
    estimate = geometry.estimate_skew_hough(np.zeros((220, 220), dtype=np.uint8))
    assert estimate.method == "hough"
    assert estimate.angle_degrees == pytest.approx(0.0)
    assert estimate.confidence == pytest.approx(1.0)


def test_hough_no_segments_returns_missing_confidence(monkeypatch):
    monkeypatch.setattr(geometry.cv2, "HoughLinesP", lambda *_a, **_kw: None)
    result = geometry.estimate_skew_hough(np.zeros((200, 200), dtype=np.uint8))
    assert result.method == "hough" and result.confidence == 0.0


def test_engine_succeeds_when_hough_yields_flat_lines(page, monkeypatch):
    monkeypatch.setattr(geometry, "estimate_skew_projection",
                        lambda *_args, **_kwargs: geometry.SkewEstimate(0.0, "projection-variance", 0.0))
    segments = np.asarray([[10, 40, 650, 40]], dtype=np.int32)
    monkeypatch.setattr(geometry.cv2, "HoughLinesP", lambda *_a, **_kw: segments)
    outcome = GraphologyEngine().analyze(page)
    assert outcome.measurements["PAGE_LINE_COUNT"].raw_value == 3
    assert outcome.metadata["skew_method"] == "hough"
