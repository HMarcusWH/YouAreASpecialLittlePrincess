"""Word proposal instrumentation is observational; boxes stay unchanged."""
import cv2
import numpy as np

from princess_graphology.context import prepare_context
from princess_graphology.models import Box
from princess_graphology.segmentation import (
    WordDetection, attach_words, detect_words, filter_word_proposals,
)


def test_raw_filter_and_assignment_rejections():
    mask = np.zeros((100, 250), np.uint8)
    mask[20:40, 20:70] = 255
    lines = (Box(0, 10, 120, 40), Box(0, 45, 120, 40))
    raw = [
        WordDetection(Box(20, 20, 50, 20), 500),
        WordDetection(Box(20, 20, 50, 20), 500),
        WordDetection(Box(150, 20, 70, 20), 500),
    ]
    trace = {}
    filtered = filter_word_proposals(raw, mask.shape, diagnostics=trace)
    before = attach_words([w.box for w in filtered], lines, mask)
    after = attach_words([w.box for w in filtered], lines, mask, diagnostics=trace)
    assert before == after
    assert trace["accepted_words"] == 1
    assert trace["reject_no_ink_in_crop"] == 1
    assert trace["reject_nested_duplicate"] == 1


def test_trace_never_changes_measurements_or_accepted_boxes():
    image = np.full((160, 440, 3), 255, np.uint8)
    cv2.putText(image, "hello world", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
    a = prepare_context(image, deskew_enabled=False)
    trace = {}
    b = prepare_context(image, deskew_enabled=False, word_trace=trace)
    assert a.lines == b.lines and a.words == b.words
    assert a.metadata == b.metadata
    assert isinstance(trace["raw_contours"], int)
    assert isinstance(trace["raw_proposals"], int)
    assert trace["raw_proposals"] >= trace["after_geometry_filter"] >= trace["accepted_words"]
    assert not any(isinstance(value, (np.ndarray, bytes)) for value in trace.values())


def test_no_lines_trace_is_empty_not_synthetic_words():
    trace = {}
    a = prepare_context(np.full((60, 100), 255, np.uint8), word_trace=trace)
    assert not a.lines and not a.words
    assert trace["accepted_words"] == 0 and trace["raw_proposals"] == 0
