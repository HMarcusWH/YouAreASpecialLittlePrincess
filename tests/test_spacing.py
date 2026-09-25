from dataclasses import replace

import pytest

from princess_graphology.measurements.spacing import measure_spacing
from princess_graphology.segmentation import attach_words
from conftest import Box, context, records, rectangle_mask, values


def test_23_pixels_over_11_5_xheight():
    lines = [Box(20, 10, 100, 10), Box(20, 43, 100, 10), Box(20, 76, 100, 10)]
    m = records(measure_spacing(context(lines=lines, xheight=11.5)))
    assert m['LINE_SPACING_PX'].raw_value == 23
    assert m['LINE_SPACING_REL'].raw_value == 2
    assert m['LINE_SPACING_CV'].raw_value == 0
    assert m['LINE_SPACING_REL'].std_dev == 0


def test_cv_is_not_pixel_standard_deviation():
    lines = [Box(20, 0, 100, 10), Box(20, 20, 100, 10), Box(20, 60, 100, 10)]
    m = records(measure_spacing(context(lines=lines)))
    assert m['LINE_SPACING_PX'].raw_value == 20
    assert m['LINE_SPACING_PX'].std_dev == 10
    assert m['LINE_SPACING_CV'].raw_value == .5
    assert m['LINE_SPACING_REL'].std_dev == 1


def test_overlap_not_clamped_into_zero_gap():
    ctx = context(lines=[Box(20, 10, 100, 20), Box(20, 20, 100, 20)])
    m = records(measure_spacing(ctx))
    assert m['LINE_SPACING_PX'].raw_value is None
    assert m['LINE_SPACING_PX'].method_metadata['excluded_overlapping_pairs'] == 1


def test_single_gap_cv_missing_and_touching_zero_gap():
    m = values(measure_spacing(context(lines=[Box(20, 10, 100, 10), Box(20, 20, 100, 10)])))
    assert m['LINE_SPACING_PX'] == 0
    assert m['LINE_SPACING_CV'] is None


def test_words_assigned_only_to_overlapping_lines_and_deduplicated():
    line = Box(10, 20, 180, 12)
    words = [Box(20, 20, 20, 12), Box(55, 20, 30, 12), Box(105, 20, 20, 12)]
    mask = rectangle_mask(words)
    ctx = context(mask, lines=[line], words=words + [words[0], Box(20, 100, 20, 10)])
    assert len(ctx.words) == 3
    m = records(measure_spacing(ctx))
    assert m['WORD_SPACING_PX'].raw_value == 17.5
    assert m['WORD_SPACING_REL'].raw_value == 1.75
    assert m['WORD_SPACING_CV'].raw_value == pytest.approx(2.5/17.5)
    accepted, _ = attach_words([Box(20, 90, 20, 10)], [line], mask)
    assert not accepted
    overlapping = replace(ctx, words=(Box(20, 20, 30, 12), Box(40, 20, 30, 12)), word_lines=(0, 0))
    assert values(measure_spacing(overlapping))['WORD_SPACING_PX'] is None
