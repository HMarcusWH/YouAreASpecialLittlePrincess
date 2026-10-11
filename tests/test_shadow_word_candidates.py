import numpy as np
import pytest
from princess_graphology.models import Box
from princess_graphology.segmentation_words import propose_words


def test_two_visible_groups_are_candidates_not_recognized_words():
    mask = np.zeros((120, 350), np.uint8)
    for x in (20, 30, 40, 95, 105, 115):
        mask[30:50, x:x + 5] = 255
    line = Box(0, 20, 200, 40)
    a = propose_words(mask, (line,))
    assert len(a.boxes) == 2
    assert a.line_indices == (0, 0)
    assert a.diagnostics["method"] == "ink_gap_groups_shadow_v1"
    assert a == propose_words(mask, (line,))


def test_empty_line_does_not_invent_a_word():
    mask = np.zeros((120, 350), np.uint8)
    assert propose_words(mask, (Box(0, 20, 200, 40),)).boxes == ()


def test_rejects_invalid_image_or_line():
    with pytest.raises(ValueError):
        propose_words(np.zeros((120, 350), np.float32), ())
    with pytest.raises(ValueError):
        propose_words(np.zeros((120, 350), np.uint8), (Box(300, 20, 100, 40),))


def test_remains_out_of_authoritative_engine():
    import inspect
    import princess_graphology.context as context
    assert "propose_words" not in inspect.getsource(context)
