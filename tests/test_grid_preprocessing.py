"""Pure NumPy/OpenCV regression tests, no models or network."""
import cv2
import numpy as np
import pytest

from grid_cases import specimen
from princess_graphology.preprocessing.grid import GridQualityError, separate_grid, require_qualified


def prep(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    raw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    return gray, raw


def test_plain_paper_is_exact_noop():
    bgr, _ = specimen(grid='none')
    gray, raw = prep(bgr)
    result = separate_grid(bgr, gray, raw)
    assert result.status == 'absent'
    np.testing.assert_array_equal(result.retained_mask, raw)
    np.testing.assert_array_equal(result.proposal_gray, gray)
    assert result.removed_pixels == 0


def test_blue_square_grid_is_detected_and_handwriting_stays():
    bgr, marks = specimen(grid='blue', text=True, crossing=True)
    gray, raw = prep(bgr)
    result = separate_grid(bgr, gray, raw)
    assert result.status in ('cleaned', 'detected_no_contamination')
    assert 38 <= result.horizontal_pitch_px <= 42
    assert 38 <= result.vertical_pitch_px <= 42
    assert np.count_nonzero(result.proposal_gray != gray) > 15000
    assert np.mean(result.retained_mask[marks > 0] > 0) >= 0.995
    assert np.all(result.proposal_gray[result.removable_mask > 0] == 255)
    # A pale grid may already be omitted by Otsu: no subtraction is correct.
    if result.removed_pixels:
        assert np.count_nonzero(result.retained_mask) < np.count_nonzero(raw)
    else:
        np.testing.assert_array_equal(result.retained_mask, raw)
    require_qualified(result)


@pytest.mark.parametrize('color', ['gray', 'black'])
def test_gray_and_black_grid_refuse_unsafe_pen_deletion(color):
    bgr, _ = specimen(grid=color, text=True)
    gray, raw = prep(bgr)
    result = separate_grid(bgr, gray, raw)
    assert result.status == 'ambiguous'
    np.testing.assert_array_equal(result.retained_mask, raw)
    with pytest.raises(GridQualityError, match='grid_ink_separation_ambiguous'):
        require_qualified(result)


def test_blue_grid_without_handwriting_cannot_produce_report():
    bgr, _ = specimen(grid='blue', text=False)
    gray, raw = prep(bgr)
    result = separate_grid(bgr, gray, raw)
    assert result.status == 'empty_after_clean'
    assert np.count_nonzero(result.retained_mask) == 0
    with pytest.raises(GridQualityError, match='no_handwriting_after_grid_removal'):
        require_qualified(result)


def test_no_colour_information_with_grid_fails_closed():
    bgr, _ = specimen(grid='gray')
    gray, raw = prep(bgr)
    result = separate_grid(None, gray, raw)
    assert result.status == 'ambiguous'
    assert np.array_equal(result.proposal_gray, gray)


def test_a_single_long_underline_survives():
    img = np.full((480, 720, 3), 255, np.uint8)
    cv2.line(img, (45, 270), (680, 270), (17, 17, 17), 2)
    gray, raw = prep(img)
    result = separate_grid(img, gray, raw)
    assert result.status == 'absent'
    np.testing.assert_array_equal(result.retained_mask, raw)


def test_foreground_polarity_and_alignment_validation():
    bgr, _ = specimen(grid='blue')
    gray, raw = prep(bgr)
    with pytest.raises(ValueError, match='co-registered'):
        separate_grid(bgr[:-1], gray, raw)
    with pytest.raises(ValueError, match='0/255'):
        separate_grid(bgr, gray, raw // 255)


def test_quality_error_codes_are_bounded():
    with pytest.raises(ValueError, match='unknown grid quality error'):
        GridQualityError('unsafe_detail_leak')


@pytest.mark.parametrize('pen_bgr,expected', [
    ((220, 175, 142), 'ambiguous'),
    ((210, 100, 80), 'cleaned'),
    ((80, 80, 220), 'cleaned'),
])
def test_colored_pen_intersections_are_not_erased(pen_bgr, expected):
    bgr, marks = specimen(grid='blue')
    bgr[marks > 0] = pen_bgr
    gray, raw = prep(bgr)
    result = separate_grid(bgr, gray, raw)
    assert result.status == expected
    if expected == 'ambiguous':
        with pytest.raises(GridQualityError):
            require_qualified(result)
    else:
        assert np.mean(result.retained_mask[marks > 0] > 0) >= 0.995


def test_diagnostics_do_not_include_original_pixels():
    bgr, _ = specimen(grid='blue')
    gray, raw = prep(bgr)
    diagnostics = separate_grid(bgr, gray, raw).diagnostics()
    assert diagnostics['version'] == 'grid-v1'
    assert set(diagnostics) == {
        'version', 'status', 'horizontal_pitch_px', 'vertical_pitch_px',
        'grid_candidate_pixels', 'grid_removed_pixels', 'grid_uncertain_pixels',
        'grid_separation_policy',
    }
    assert all(not isinstance(x, np.ndarray) for x in diagnostics.values())


def test_repeating_pen_stems_are_not_grid_lines():
    """Three synthetic handwritten bands may have regular vertical strokes."""
    import math
    gray = np.full((360, 900), 245, np.uint8)
    for line in range(3):
        base = 72 + line * 105
        for x in range(35, 860):
            wave = int(8 * math.sin(x / 17.0) + 3 * math.sin(x / 5.0))
            cv2.circle(gray, (x, base + wave), 1, 28, -1)
            if x % 47 < 3:
                cv2.line(gray, (x, base + wave - 26), (x, base + wave + 12), 28, 2)
    raw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    result = separate_grid(None, gray, raw)
    assert result.status == 'absent'
    np.testing.assert_array_equal(result.retained_mask, raw)
