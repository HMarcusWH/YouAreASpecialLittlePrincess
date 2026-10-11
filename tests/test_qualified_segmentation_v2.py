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

def test_unqualified_measures_preserve_canonical_feature_ids_and_missing_reasons():
    image, _, _ = grid_only(ruling='none')
    result = qualified(image)
    assert len(result.measurements) == 64
    for feature in ('PAGE_LINE_COUNT', 'PAGE_WORD_COUNT', 'PAGE_TEXT_AREA_RATIO',
                    'BASELINE_ANGLE_MEAN', 'INK_DARKNESS_MEAN', 'MARGIN_LEFT_REL'):
        item = result.measurements[feature]
        assert item.raw_value is None and item.quality_flag == 'MISSING'
        assert item.missing_reason and item.n_observations == 0
    for feature in ('IMG_WIDTH_PX', 'IMG_HEIGHT_PX', 'IMG_MEGAPIXELS', 'IMG_ASPECT_RATIO'):
        assert result.measurements[feature].raw_value is not None


def test_original_and_analysis_transform_round_trip_for_inset_page():
    from princess_graphology.context import prepare_context
    image, _, _ = page(ruling='gray', background=True)
    context = prepare_context(image, grid_profile='qualified-v2', deskew_enabled=False)
    forward = np.asarray(context.metadata['original_to_analysis'])
    inverse = np.asarray(context.metadata['analysis_to_original'])
    assert np.allclose(forward @ inverse, np.eye(3), atol=1e-7)
    assert np.allclose(inverse @ forward, np.eye(3), atol=1e-7)
    assert context.metadata['document_geometry']['version'] == 'document-roi-v1'
    assert context.original_width == image.shape[1]
    assert context.original_height == image.shape[0]


def test_word_detector_contour_modes_are_bounded_and_traceable():
    import cv2
    from princess_graphology.segmentation import detect_words
    image, _, _ = page(ruling='none')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    external, internal = {}, {}
    a = detect_words(gray, retrieval='external', diagnostics=external)
    b = detect_words(gray, retrieval='list', diagnostics=internal)
    assert external['raw_contours'] <= internal['raw_contours']
    assert len(a) <= external['raw_contours']
    assert len(b) <= internal['raw_contours']
    with pytest.raises(ValueError, match='retrieval'):
        detect_words(gray, retrieval='undefined')

def test_partial_qualification_never_selects_invalid_highlight_support():
    from princess_app.domain.reports.assembly import facts_from_result
    from princess_app.domain.content import select_highlights
    image, _, _ = grid_only(ruling='none')
    result = qualified(image)
    facts, issues = facts_from_result(result.to_dict())
    assert not issues
    assert all(f['value'] is None and f['availability'] == 'MISSING'
               for f in facts if f['feature_id'] in ('PAGE_LINE_COUNT', 'PAGE_WORD_COUNT',
                                                      'BASELINE_ANGLE_MEAN'))
    assert all(all(fact_id not in ('fact.PAGE_LINE_COUNT', 'fact.PAGE_WORD_COUNT',
                                  'fact.BASELINE_ANGLE_MEAN') for fact_id in item.support_fact_ids)
               for item in select_highlights(facts, limit=3))

def test_unqualified_lines_never_produce_baseline_evidence():
    image, _, _ = grid_only(ruling='none')
    result, evidence = GraphologyEngine(
        grid_profile='qualified-v2', deskew_enabled=False).analyze_with_evidence(image)
    assert result.measurements['BASELINE_ANGLE_MEAN'].raw_value is None
    assert not [r for r in result.regions if r.scope in ('LINE', 'WORD')]
    assert not [r for r in evidence['regions'] if r['scope'] in ('LINE', 'WORD', 'BASELINE_POINT')]
    assert not [row for row in evidence['observations'] if row['feature_id'].startswith('BASELINE_')]

@pytest.mark.parametrize("ruling", ["gray", "blue"])
def test_grid_v2_never_deletes_dark_strokes_at_grid_crossings(ruling):
    import cv2
    from princess_graphology.preprocessing.grid_v2 import separate_grid_v2
    image, pen_mask, _ = page(ruling=ruling, pen="black")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    out = separate_grid_v2(image, gray, raw)
    assert out.status in ("cleaned", "detected_no_contamination")
    observed_pen = (raw > 0) & (pen_mask > 0)
    if np.any(observed_pen):
        assert np.mean(out.retained_mask[observed_pen] > 0) >= 0.99


@pytest.mark.parametrize("perspective", [False, True])
def test_inset_paper_perspective_never_launders_grid_into_layout(perspective):
    image, pen_mask, _ = page(ruling="gray", pen="black",
                              background=True, perspective=perspective)
    try:
        result = GraphologyEngine(grid_profile="qualified-v2").analyze(image)
    except GridQualityError:
        return
    assert result.measurements["PAGE_LINE_COUNT"].raw_value in (None, 1, 2)
    area = result.measurements["PAGE_TEXT_AREA_RATIO"]
    assert area.raw_value is None or area.raw_value < .8
    # The source footprint itself may be rectified, so require exact output
    # lineage rather than comparing analysis-frame boxes to source pixels.
    a = np.asarray(result.metadata["original_to_analysis"])
    b = np.asarray(result.metadata["analysis_to_original"])
    assert np.allclose(a @ b, np.eye(3), atol=1e-6)
    assert np.count_nonzero(pen_mask) > 0


def test_quality_capture_error_copy_is_actionable_not_an_internal_code():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    web = (root / "apps/web/app/analyses/[runId]/JobStatus.tsx").read_text("utf-8")
    native = (root / "apps/mobile/src/i18n/copy.ts").read_text("utf-8")
    assert "grid_ink_separation_ambiguous:" in web
    assert '"work.grid_ink_separation_ambiguous"' in native
    assert "no_handwriting_after_grid_removal:" in web
    assert '"work.no_handwriting_after_grid_removal"' in native
