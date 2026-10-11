"""Regression for Issue #92: ruling, paper edges and false-zero word counts."""
from __future__ import annotations

import numpy as np
import pytest

from grid_v2_cases import grid_only, page
from princess_graphology import GraphologyEngine
from princess_graphology.preprocessing.grid import GridQualityError


def qualified(image):
    return GraphologyEngine(grid_profile="qualified-v2", deskew_enabled=False).analyze(image)


@pytest.mark.parametrize("ruling", ["gray", "blue"])
@pytest.mark.parametrize("background", [False, True])
def test_full_frame_and_tabletop_grid_cannot_be_six_false_lines(ruling, background):
    image, mask, _ = page(ruling=ruling, background=background)
    try:
        result = qualified(image)
    except GridQualityError:
        return  # safer than an unsupported handwriting claim
    count = result.measurements["PAGE_LINE_COUNT"]
    assert count.raw_value is None or 1 <= count.raw_value <= 2
    area = result.measurements["PAGE_TEXT_AREA_RATIO"]
    assert area.raw_value is None or area.raw_value < 0.75
    accepted = [region for region in result.regions if region.scope == "LINE"]
    assert len(accepted) <= 2
    for line in accepted:
        part = mask[line.box.y:line.box.y2, line.box.x:line.box.x2]
        assert np.count_nonzero(part) > 0, "page ruling accepted as handwriting"


@pytest.mark.parametrize("ruling", ["gray", "blue", "black"])
def test_grid_without_text_is_not_authoritative_handwriting(ruling):
    image, _, _ = grid_only(ruling=ruling)
    try:
        result = qualified(image)
    except GridQualityError:
        return
    assert result.measurements["PAGE_LINE_COUNT"].raw_value is None
    assert result.measurements["PAGE_WORD_COUNT"].raw_value is None
    assert not [region for region in result.regions if region.scope == "LINE"]


def test_gray_grid_detects_qualified_ink_or_refuses_dossier():
    image, pen_mask, _ = page(ruling="gray", pen="black")
    try:
        result = qualified(image)
    except GridQualityError:
        return
    line_count = result.measurements["PAGE_LINE_COUNT"]
    assert line_count.raw_value == 1
    assert any(region.scope == "LINE" for region in result.regions)
    for region in result.regions:
        if region.scope == "LINE":
            assert np.count_nonzero(pen_mask[region.box.y:region.box.y2,
                                            region.box.x:region.box.x2]) > 0


def test_no_false_factual_zero_from_unqualified_word_detection():
    image, _, _ = page(ruling="gray", pen="blue")
    try:
        result = qualified(image)
    except GridQualityError:
        return
    word_count = result.measurements["PAGE_WORD_COUNT"]
    assert word_count.raw_value is None or word_count.raw_value >= 1
    if word_count.raw_value is None:
        assert word_count.quality_flag == "MISSING" and word_count.missing_reason


def test_same_tone_grid_and_pen_fail_closed_or_withhold_text():
    image, _, _ = page(ruling="black", pen="same")
    try:
        result = qualified(image)
    except GridQualityError:
        return
    assert result.measurements["PAGE_LINE_COUNT"].raw_value is None
    assert result.measurements["PAGE_TEXT_AREA_RATIO"].raw_value is None


def test_near_edge_pen_must_not_be_clipped_into_invalid_evidence():
    image, pen_mask, _ = page(ruling="gray", pen="black", near_edge=True)
    try:
        result = qualified(image)
    except GridQualityError:
        return
    for region in result.regions:
        if region.scope == "LINE":
            assert np.count_nonzero(pen_mask[region.box.y:region.box.y2,
                                            region.box.x:region.box.x2]) > 0


def test_legacy_default_is_unchanged_by_new_profile():
    image, _, _ = page(ruling="none")
    a = GraphologyEngine(deskew_enabled=False).analyze(image)
    b = GraphologyEngine(deskew_enabled=False, grid_profile="legacy").analyze(image)
    assert {k: v.to_dict() for k, v in a.measurements.items()} == {
        k: v.to_dict() for k, v in b.measurements.items()}
