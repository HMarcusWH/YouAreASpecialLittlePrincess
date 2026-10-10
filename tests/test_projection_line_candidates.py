import numpy as np
import pytest
from princess_graphology.segmentation_projection import propose_lines


def test_blank_mask_is_no_lines():
    out = propose_lines(np.zeros((200, 400), np.uint8))
    assert not out.boxes and not out.peak_rows
    assert out.diagnostics["candidates"] == 0


def test_three_bands_reproducible_and_bounded():
    img = np.zeros((400, 600), np.uint8)
    for y in (50, 170, 290):
        img[y:y + 12, 30:550] = 255
    before = img.copy()
    a = propose_lines(img)
    assert a == propose_lines(img)
    assert 2 <= len(a.boxes) <= 4
    assert all(0 <= b.x < b.x2 <= 600 and 0 <= b.y < b.y2 <= 400 for b in a.boxes)
    np.testing.assert_array_equal(img, before)


def test_invalid_inputs_fail_closed():
    with pytest.raises(ValueError):
        propose_lines(np.ones((5, 5), np.float32))
    with pytest.raises(ValueError):
        propose_lines(np.ones((5, 5), np.uint8))
    with pytest.raises(ValueError):
        propose_lines(np.zeros((5, 5), np.uint8), sigma_px=-1)


def test_no_authoritative_engine_integration():
    import inspect
    import princess_graphology.context as ctx
    import princess_graphology.engine as engine
    assert "propose_lines" not in inspect.getsource(ctx)
    assert "propose_lines" not in inspect.getsource(engine)
