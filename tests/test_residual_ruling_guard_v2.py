"""Issue #92: synthetic-only v2 residual ruling guard and nonvacuous controls."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from residual_ruling_cases import residual_page
from princess_app.application.intake import analysis_config_sha256, engine_config_sha256
from princess_app.domain.intake import INTAKE_POLICY_VERSION
from princess_graphology import GraphologyEngine
from princess_graphology.evidence_support import (
    GUARD_POLICY_VERSION, IMAGE_DIMENSION_FACTS, WORD_AUDIT_VERSION, assess_support,
    foreground_ruling_counts, _distinct_hough_bands, MAX_RULING_CANDIDATES,
)
from princess_graphology.models import Box


def _context(foreground, *, lines, words, components=()):
    h, w = foreground.shape
    return SimpleNamespace(
        height=h, width=w, original_height=h, original_width=w,
        mask=foreground, lines=tuple(lines), words=tuple(words),
        components=tuple(components), x_height_px=20.0,
    )


def _ruling_boxes(mask):
    n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [Box(*(int(v) for v in stats[i, :4])) for i in range(1, n)]
    return sorted(boxes, key=lambda b: (b.y, b.x))


@pytest.mark.parametrize("tabletop", [False, True])
@pytest.mark.parametrize("ink", ["black", "blue", "same"])
def test_neutral_ruling_detected_even_with_accepted_word_groups(tabletop, ink):
    _image, case = residual_page(tabletop=tabletop, ink=ink)
    assert case["synthetic_only"] and case["true_line"] is not None
    assert len(case["true_words"]) == 3
    ctx = _context(case["observed_foreground"],
                   lines=_ruling_boxes(case["ruling_mask"]),
                   words=case["true_words"], components=case["true_words"])
    verdict = assess_support(ctx, {"raw_proposals": 7, "after_geometry_filter": 4,
                                   "reject_no_unique_line": 2})
    assert verdict["reason"] == "residual_page_ruling"
    assert verdict["status"] == "unqualified"
    assert verdict["ruling"]["dense_horizontal_bands"] >= 2
    assert verdict["word_stages"]["counts"]["raw_proposals"] == 7
    assert verdict["word_stages"]["status"] == "accepted_groups"


@pytest.mark.parametrize("tabletop", [False, True])
def test_angle_tolerant_audit_rejects_skewed_synthetic_ruling(tabletop):
    _image, case = residual_page(tabletop=tabletop, tilted=True, ink="black")
    ctx = _context(case["observed_foreground"],
                   lines=_ruling_boxes(case["ruling_mask"]),
                   words=case["true_words"], components=case["true_words"])
    audit = assess_support(ctx)
    assert audit["ruling"]["near_horizontal_long_bands"] >= 2
    assert audit["reason"] == "residual_page_ruling"
    assert np.isfinite(case["page_polygon"]).all()


@pytest.mark.parametrize("near_edge", [False, True])
def test_clear_writing_without_printed_bands_is_not_deleted(near_edge):
    _image, case = residual_page(ruling="none", near_edge=near_edge)
    assert case["true_line"] is not None
    ctx = _context(case["ink_mask"], lines=[case["true_line"]],
                   words=case["true_words"], components=case["true_words"])
    audit = assess_support(ctx)
    assert audit["reason"] is None
    assert audit["status"] == "no_abstention_not_calibrated"
    assert audit["ruling"]["dense_horizontal_bands"] == 0
    assert audit["ruling"]["near_horizontal_long_bands"] == 0


def test_no_accepted_groups_are_unknown_not_factual_zero():
    _image, case = residual_page(ruling="none", near_edge=True)
    ctx = _context(case["ink_mask"], lines=[case["true_line"]], words=(),
                   components=case["true_words"])
    audit = assess_support(ctx, {"raw_contours": 12, "raw_proposals": 8,
                                 "after_geometry_filter": 3,
                                 "reject_no_unique_line": 3})
    assert audit["reason"] == "word_groups_unqualified"
    assert audit["word_stages"]["counts"]["raw_proposals"] == 8
    assert audit["word_stages"]["counts"]["after_geometry_filter"] == 3
    assert audit["word_stages"]["accepted_geometric_groups"] == 0
    assert audit["word_stages"]["status"] == "no_accepted_groups"


def test_no_lines_are_not_proof_of_blank_handwriting_page():
    ctx = _context(np.zeros((520, 760), np.uint8), lines=[], words=[])
    audit = assess_support(ctx)
    assert audit["reason"] == "no_verified_text_lines"
    assert audit["word_stages"]["status"] == "not_invoked"
    assert audit["word_stages"]["counts"]["raw_proposals"] is None


def test_word_trace_allowlist_does_not_export_pixels_or_untrusted_fields():
    _image, case = residual_page(ruling="none")
    ctx = _context(case["ink_mask"], lines=[case["true_line"]],
                   words=case["true_words"])
    trace = {"raw_contours": 14, "raw_proposals": 9,
             "reject_oversized_proposal": 2, "after_geometry_filter": 7,
             "pixels": np.zeros((5, 5), np.uint8),
             "raw_text": "forbidden transcription",
             "accepted_words": 3,
             "reject_exact_duplicate": 10 ** 10}
    audit = assess_support(ctx, trace)["word_stages"]
    assert audit["version"] == WORD_AUDIT_VERSION
    assert audit["counts"]["raw_proposals"] == 9
    assert audit["counts"]["reject_exact_duplicate"] is None
    assert audit["counts"]["qualified_gap_candidates"] is None
    assert set(audit) == {"version", "status", "accepted_geometric_groups",
                          "counts", "reattachment"}
    assert set(audit["reattachment"]) == {"status", "counts"}
    assert audit["reattachment"]["status"] == "unavailable"
    assert all(value is None for value in audit["reattachment"]["counts"].values())
    assert not any(isinstance(v, (str, bytes, np.ndarray, dict, list))
                   for v in audit["reattachment"]["counts"].values())
    assert not any(isinstance(v, (str, bytes, np.ndarray, dict, list))
                   for v in audit["counts"].values())


def test_v5_digest_changes_guarded_identity_but_preserves_disabled_production():
    assert GUARD_POLICY_VERSION == "evidence-support/5"
    legacy = ("engine:max_dimension=2200;deskew=true;" + INTAKE_POLICY_VERSION).encode()
    old_v1 = ("engine:max_dimension=2200;deskew=true;"
              "evidence_support=evidence-support/1;" + INTAKE_POLICY_VERSION).encode()
    old_v2 = ("engine:max_dimension=2200;deskew=true;"
              "evidence_support=evidence-support/2;" + INTAKE_POLICY_VERSION).encode()
    old_v3 = ("engine:max_dimension=2200;deskew=true;"
              "evidence_support=evidence-support/3;" + INTAKE_POLICY_VERSION).encode()
    old_v4 = ("engine:max_dimension=2200;deskew=true;"
              "evidence_support=evidence-support/4;" + INTAKE_POLICY_VERSION).encode()
    current = analysis_config_sha256(evidence_guard_enabled=True)
    assert current != hashlib.sha256(old_v1).hexdigest()
    assert current != hashlib.sha256(old_v2).hexdigest()
    assert current != hashlib.sha256(old_v3).hexdigest()
    assert current != hashlib.sha256(old_v4).hexdigest()
    assert analysis_config_sha256() == hashlib.sha256(legacy).hexdigest()
    assert current == hashlib.sha256((
        "engine:max_dimension=2200;deskew=true;"
        f"evidence_support={GUARD_POLICY_VERSION};" + INTAKE_POLICY_VERSION).encode()).hexdigest()
    assert engine_config_sha256(GraphologyEngine(evidence_guard_enabled=True)) == current
    assert GraphologyEngine().evidence_guard_enabled is False


def test_actual_guarded_engine_abstains_without_regions_or_observations():
    image = np.full((800, 640, 3), 248, np.uint8)
    for y in range(45, 790, 96):
        cv2.line(image, (0, y), (639, y), (210, 190, 170), 2)
    result, bundle = GraphologyEngine(evidence_guard_enabled=True).analyze_with_evidence(
        image, source="synthetic-ruling-only")
    assert len(result.measurements) == 64
    assert {k for k, row in result.measurements.items()
            if row.raw_value is not None} == IMAGE_DIMENSION_FACTS
    assert result.metadata["evidence_support"]["policy"] == GUARD_POLICY_VERSION
    assert result.metadata["evidence_support_audit"]["status"] == "unqualified"
    assert [r.scope for r in result.regions] == ["PAGE"]
    assert bundle["observations"] == []
    assert {r["scope"] for r in bundle["regions"]} == {"PAGE"}
    assert all(row.raw_value is None and row.quality_flag == "MISSING" and row.n_observations == 0
               for k, row in result.measurements.items() if k not in IMAGE_DIMENSION_FACTS)


def test_clear_writing_keeps_measurements_and_regions_under_v2_audit():
    image = np.full((800, 640, 3), 248, np.uint8)
    for i, text in enumerate(("Alpha Beta Gamma", "Delta Zeta Eta", "Theta Iota Kappa")):
        cv2.putText(image, text, (40, 150 + 170 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (18, 18, 18), 2, cv2.LINE_AA)
    baseline = GraphologyEngine().analyze(image)
    candidate = GraphologyEngine(evidence_guard_enabled=True).analyze(image)
    assert candidate.metadata["evidence_support_audit"]["reason"] is None
    assert "evidence_support" not in candidate.metadata
    assert baseline.to_dict()["measurements"] == candidate.to_dict()["measurements"]
    assert baseline.to_dict()["regions"] == candidate.to_dict()["regions"]
    assert candidate.metadata["evidence_support_audit"]["word_stages"]["status"] == "accepted_groups"


def test_qualified_v2_photo_never_publishes_unqualified_baselines():
    from grid_v2_cases import page
    from princess_graphology.preprocessing.grid import GridQualityError
    image, _pen_mask, _ = page(ruling="gray", pen="black", background=True)
    try:
        result, evidence = GraphologyEngine(
            grid_profile="qualified-v2", evidence_guard_enabled=True
        ).analyze_with_evidence(image)
    except GridQualityError:
        return  # a quality refusal is safer than invented text geometry
    assert "evidence_support_audit" in result.metadata
    assert len(result.measurements) == 64
    if result.metadata.get("evidence_support", {}).get("status") == "unqualified":
        assert [r.scope for r in result.regions] == ["PAGE"]
        assert evidence["observations"] == []
        assert result.measurements["BASELINE_ANGLE_MEAN"].raw_value is None
    else:
        # A non-abstaining guard is not empirical proof. Qualified-v2 still
        # controls its own independent line and word evidence.
        status = result.metadata["qualification"]
        if status["lines"] != "qualified":
            assert result.measurements["BASELINE_ANGLE_MEAN"].raw_value is None
        if status["words"] != "qualified":
            assert result.measurements["PAGE_WORD_COUNT"].raw_value is None


@pytest.mark.parametrize("extra_axis", [False, True])
def test_opencv_hough_endpoint_shape_is_wheel_independent(monkeypatch, extra_axis):
    # Some pinned OpenCV wheels return N×4 and others N×1×4.
    _image, case = residual_page()
    ctx = _context(case["observed_foreground"],
                   lines=_ruling_boxes(case["ruling_mask"]),
                   words=case["true_words"], components=case["true_words"])
    detected = np.array([[8, 81, 750, 81], [8, 240, 750, 241]], np.int32)
    response = detected[:, None, :] if extra_axis else detected
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs: response)
    assert assess_support(ctx)["ruling"]["near_horizontal_long_bands"] == 2


@pytest.mark.parametrize("kind", ["thick", "slanted", "underline"])
def test_one_real_hough_stroke_is_not_two_independent_ruling_bands(kind):
    """The actual pinned OpenCV operation, not stubbed HoughSegments."""
    h, w = 520, 760
    foreground = np.zeros((h, w), np.uint8)
    if kind == "slanted":
        cv2.line(foreground, (0, 105), (w - 1, 180), 255, 2)
    else:
        y = 210 if kind == "underline" else 110
        cv2.line(foreground, (0, y), (w - 1, y), 255, 7)
    ctx = _context(foreground, lines=[Box(40, 260, 300, 22)],
                   words=[Box(50, 265, 70, 15)],
                   components=[Box(70, 265, 12, 15)] * 12)
    audit = assess_support(ctx)
    assert audit["ruling"]["near_horizontal_long_bands"] == 1
    assert audit["reason"] is None


@pytest.mark.parametrize("slope", [0, 52])
def test_two_separate_real_hough_rules_remain_two_bands(slope):
    h, w = 520, 760
    foreground = np.zeros((h, w), np.uint8)
    for y in (105, 205):
        cv2.line(foreground, (0, y), (w - 1, y + slope), 255, 3)
    ctx = _context(foreground, lines=[Box(40, 280, 300, 20)],
                   words=[Box(45, 280, 70, 15)],
                   components=[Box(45, 280, 12, 15)] * 12)
    audit = assess_support(ctx)
    assert audit["ruling"]["near_horizontal_long_bands"] == 2
    assert audit["reason"] == "residual_page_ruling"


def test_actual_engine_blank_never_reports_uninvoked_detector_zero():
    image = np.full((520, 760, 3), 250, np.uint8)
    report = GraphologyEngine(evidence_guard_enabled=True).analyze(image)
    audit = report.metadata["evidence_support_audit"]["word_stages"]
    assert audit["status"] == "not_invoked"
    assert audit["accepted_geometric_groups"] is None
    assert audit["counts"]["raw_contours"] is None
    assert audit["counts"]["raw_proposals"] is None
    assert audit["counts"]["after_geometry_filter"] is None
    assert report.measurements["PAGE_WORD_COUNT"].raw_value is None


def test_v2_original_detector_counts_survive_second_word_attachment(monkeypatch):
    from princess_graphology import context as context_mod
    from princess_graphology.segmentation_v2 import LineSelection, WordSelection
    from grid_v2_cases import page
    image, _, _ = page(ruling="none", pen="black")
    def fake_lines(mask):
        h, w = mask.shape
        return LineSelection(mask.copy(), (Box(0, 0, w, h),), "qualified", {})
    def fake_words(_gray, _mask, _lines):
        return WordSelection((Box(100, 220, 150, 32),), "qualified", {
            "raw_contours": 12,
            "raw_proposals": 9,
            "after_geometry_filter": 8,
            "reject_exact_duplicate": 7,
            "reject_no_ink_in_crop": 4,
            "accepted_geometry_groups": 1,
        })
    monkeypatch.setattr(context_mod, "qualified_lines", fake_lines)
    monkeypatch.setattr(context_mod, "qualified_words", fake_words)
    engine = GraphologyEngine(grid_profile="qualified-v2",
                             evidence_guard_enabled=True, deskew_enabled=False)
    report = engine.analyze(image)
    audit = report.metadata["evidence_support_audit"]["word_stages"]
    assert audit["counts"]["raw_proposals"] == 9
    assert audit["counts"]["reject_exact_duplicate"] == 7
    assert audit["counts"]["reject_no_ink_in_crop"] == 4
    assert audit["reattachment"]["status"] == "performed"
    assert audit["reattachment"]["counts"]["reject_exact_duplicate"] == 0
    assert "pre_line_ruling_audit" in report.metadata


def _bounding_box(mask):
    ys, xs = np.nonzero(mask)
    assert len(xs) > 0, "synthetic ground truth must contain actual pen pixels"
    return Box(int(xs.min()), int(ys.min()),
               int(xs.max() - xs.min() + 1),
               int(ys.max() - ys.min() + 1))


def _box_iou(a, b):
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.x2, b.x2), min(a.y2, b.y2)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = a.area + b.area - intersection
    return intersection / union if union else 0.0


def _assert_independent_pen_geometry(line_boxes, word_boxes, pen_mask,
                                     ruling_mask, independent_word_masks):
    """Check all reported regions against independent synthetic ink truth.

    This is intentionally stricter than checking one pixel of overlap. The
    reference boxes come from the drawn pixels, not cv2.getTextSize halos,
    and are never supplied to the engine as proposed detections.
    """
    line_reference = _bounding_box(pen_mask)
    assert len(line_boxes) == 1
    line = line_boxes[0]
    assert _box_iou(line, line_reference) >= 0.45
    assert line.area <= 2.0 * line_reference.area
    assert np.count_nonzero(pen_mask[line.y:line.y2, line.x:line.x2]) >= (
        0.75 * np.count_nonzero(pen_mask)
    )
    assert np.count_nonzero(ruling_mask[line.y:line.y2, line.x:line.x2]) <= (
        0.20 * line.area
    )

    references = [_bounding_box(mask) for mask in independent_word_masks]
    assert len(references) == 3
    assert 2 <= len(word_boxes) <= len(references)
    candidates = sorted(
        ((_box_iou(box, reference), predicted, actual)
         for predicted, box in enumerate(word_boxes)
         for actual, reference in enumerate(references)),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    paired_predictions, paired_references = set(), set()
    for iou, predicted, actual in candidates:
        if iou < 0.45 or predicted in paired_predictions or actual in paired_references:
            continue
        box = word_boxes[predicted]
        reference = references[actual]
        mask = independent_word_masks[actual]
        assert box.area <= 2.0 * reference.area
        assert np.count_nonzero(mask[box.y:box.y2, box.x:box.x2]) >= (
            0.70 * np.count_nonzero(mask)
        )
        assert np.count_nonzero(ruling_mask[box.y:box.y2, box.x:box.x2]) <= (
            0.20 * box.area
        )
        paired_predictions.add(predicted)
        paired_references.add(actual)
    assert len(paired_predictions) == len(word_boxes)
    assert len(paired_references) >= 2


def test_real_engine_accepts_predeclared_clean_ruled_handwriting_positive():
    """Full engine must keep actual pen geometry, not paper-rule false boxes."""
    from grid_v2_cases import page
    from princess_graphology.preprocessing.grid import GridQualityError

    image, source_pen, _approximate_boxes, references = page(
        ruling="gray", pen="black", with_annotations=True,
    )
    engine = GraphologyEngine(grid_profile="qualified-v2",
                             deskew_enabled=False, evidence_guard_enabled=True)
    try:
        report, evidence = engine.analyze_with_evidence(image)
    except GridQualityError as exc:
        pytest.fail(f"predeclared ruled-positive was refused: {exc.code}")
    assert "evidence_support" not in report.metadata, report.metadata.get("evidence_support")
    assert report.measurements["PAGE_LINE_COUNT"].raw_value == 1
    assert report.measurements["PAGE_WORD_COUNT"].raw_value >= 2

    lines = [region.box for region in report.regions if region.scope == "LINE"]
    words = [region.box for region in report.regions if region.scope == "WORD"]
    transform = np.asarray(report.metadata["original_to_analysis"], np.float64)
    size = (report.width, report.height)
    pen = cv2.warpPerspective(source_pen, transform, size, flags=cv2.INTER_NEAREST)
    ruling = cv2.warpPerspective(
        references["ruling_mask"], transform, size, flags=cv2.INTER_NEAREST,
    )
    word_masks = tuple(
        cv2.warpPerspective(mask, transform, size, flags=cv2.INTER_NEAREST)
        for mask in references["word_masks"]
    )
    _assert_independent_pen_geometry(lines, words, pen, ruling, word_masks)

    assert any(region["scope"] == "LINE" for region in evidence["regions"])
    audit = report.metadata["evidence_support_audit"]
    assert audit["status"] == "no_abstention_not_calibrated"
    assert audit["ruling"]["foreground_stage"] == "qualified_line_selected"
    assert audit["ruling"]["pre_line_selection"] is not None


def test_synthetic_positive_geometry_rejects_pagewide_false_regions():
    from grid_v2_cases import page

    image, ink, _legacy_boxes, reference = page(
        ruling="gray", pen="black", with_annotations=True,
    )
    assert image.shape[:2] == ink.shape
    expected_line = _bounding_box(ink)
    words = [_bounding_box(mask) for mask in reference["word_masks"]]
    _assert_independent_pen_geometry(
        [expected_line], words, ink, reference["ruling_mask"],
        reference["word_masks"],
    )
    fake_page = Box(0, 0, image.shape[1], image.shape[0])
    with pytest.raises(AssertionError):
        _assert_independent_pen_geometry(
            [fake_page], words, ink, reference["ruling_mask"],
            reference["word_masks"],
        )
    with pytest.raises(AssertionError):
        _assert_independent_pen_geometry(
            [expected_line], [fake_page, *words[1:]], ink,
            reference["ruling_mask"], reference["word_masks"],
        )


@pytest.mark.parametrize("thickness", [2, 7, 25, 35, 65])
def test_one_heavy_stroke_is_one_physical_ribbon(thickness):
    foreground = np.zeros((520, 760), np.uint8)
    cv2.line(foreground, (0, 110), (759, 110), 255, thickness)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["hough_status"] == "checked"
    assert ruling["near_horizontal_long_bands"] == 1
    assert not ruling["audit_limit_reached"]
    audit = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert audit["reason"] is None


@pytest.mark.parametrize("thickness", [2, 3, 7])
def test_crossing_ruling_remains_two_distinct_bands(thickness):
    foreground = np.zeros((520, 760), np.uint8)
    # Equal center intercept but nonparallel source geometry.
    cv2.line(foreground, (0, 120), (759, 136), 255, thickness)
    cv2.line(foreground, (0, 136), (759, 120), 255, thickness)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["hough_status"] == "checked"
    # Thick crossing strokes form legitimate dense rows; their presence
    # does not excuse a broken independent Hough grouping test.
    assert ruling["hough_status"] == "checked"
    assert ruling["near_horizontal_long_bands"] == 2
    verdict = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert verdict["reason"] == "residual_page_ruling"


def test_subdegree_thin_parallel_rule_detection():
    foreground = np.zeros((520, 760), np.uint8)
    for y in (55, 135):
        cv2.line(foreground, (0, y), (759, y + 7), 255, 2)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["hough_status"] == "checked"
    assert ruling["dense_horizontal_bands"] == 0
    assert ruling["near_horizontal_long_bands"] == 2


@pytest.mark.parametrize("gap, thickness", [(15, 3), (40, 2), (40, 25)])
def test_separated_near_parallel_rules_not_merged(gap, thickness):
    foreground = np.zeros((520, 760), np.uint8)
    cv2.line(foreground, (0, 110), (759, 110), 255, thickness)
    cv2.line(foreground, (0, 110 + gap), (759, 110 + gap), 255, thickness)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["near_horizontal_long_bands"] == 2


def test_ruling_band_partition_independent_of_hough_output_order():
    foreground = np.zeros((520, 760), np.uint8)
    for y in (100, 160):
        cv2.line(foreground, (0, y), (759, y + 6), 255, 7)
    segments = cv2.HoughLinesP(
        foreground, rho=1, theta=np.pi / 720, threshold=max(20, int(0.16 * 760)),
        minLineLength=int(0.67 * 760), maxLineGap=int(0.03 * 760),
    )
    assert segments is not None
    normal = _distinct_hough_bands(segments, foreground)
    reversed_order = _distinct_hough_bands(segments[::-1], foreground)
    assert normal == reversed_order == (2, "checked")


def test_ruling_candidate_budget_refuses_partial_evidence():
    image = np.zeros((520, 760), np.uint8)
    oversized = np.tile(np.array([[0, 110, 759, 110]], np.int32),
                        (MAX_RULING_CANDIDATES + 1, 1))
    assert _distinct_hough_bands(oversized, image) == (None, "budget_exceeded")


def test_high_density_hough_skip_is_unknown_and_guard_abstains():
    foreground = np.zeros((520, 760), np.uint8)
    foreground[:, :300] = 255  # >35% foreground without full-width rows.
    for y in (60, 170):
        cv2.line(foreground, (0, y), (759, y + 50), 255, 2)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["dense_horizontal_bands"] == 0
    assert ruling["near_horizontal_long_bands"] is None
    assert ruling["hough_status"] == "skipped_dense_foreground"
    verdict = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert verdict["reason"] == "residual_ruling_audit_unavailable"


def test_small_canvas_hough_skipped_does_not_report_zero():
    foreground = np.zeros((80, 54), np.uint8)
    ruling = foreground_ruling_counts(foreground)
    assert ruling["near_horizontal_long_bands"] is None
    assert ruling["hough_status"] == "skipped_small_canvas"


def test_reattachment_diagnostics_audited_not_leaked_to_metadata():
    image = np.full((800, 640, 3), 248, np.uint8)
    for i, text in enumerate(("ALPHA BETA GAMMA", "DELTA ZETA ETA")):
        cv2.putText(image, text, (40, 150 + i * 260), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (18, 18, 18), 2, cv2.LINE_AA)
    report = GraphologyEngine(evidence_guard_enabled=True).analyze(image)
    assert "word_reattachment_diagnostics" not in report.metadata
    stages = report.metadata["evidence_support_audit"]["word_stages"]
    assert stages["reattachment"]["status"] == "performed"
    assert stages["reattachment"]["counts"]["reject_exact_duplicate"] is not None
    assert stages["counts"]["raw_contours"] is not None


@pytest.mark.parametrize("layout", [
    np.array([[0, 110], [759, 110]], dtype=np.int32),
    np.array([[0, 110, 759, 110]], dtype=np.float64),
    np.array([[[[0, 110, 759, 110]]]], dtype=np.int32),
    np.array([[0, 110, 759]], dtype=np.int32),
    np.array([[0, 110, 760, 110]], dtype=np.int32),
    np.array([[-1, 110, 759, 110]], dtype=np.int32),
])
def test_malformed_hough_layout_never_becomes_a_measured_line(layout):
    foreground = np.zeros((520, 760), np.uint8)
    cv2.line(foreground, (0, 110), (759, 110), 255, 2)
    assert _distinct_hough_bands(layout, foreground) == (None, "malformed_response")


@pytest.mark.parametrize("shape", [(0, 4), (0, 1, 4)])
def test_valid_empty_hough_layout_is_measured_zero(shape):
    foreground = np.zeros((520, 760), np.uint8)
    assert _distinct_hough_bands(np.empty(shape, np.int32), foreground) == (
        0, "checked",
    )
    assert _distinct_hough_bands(None, foreground) == (0, "checked")


def test_malformed_hough_response_has_distinct_guard_reason(monkeypatch):
    foreground = np.zeros((520, 760), np.uint8)
    cv2.line(foreground, (0, 110), (759, 110), 255, 2)
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs:
                        np.array([[0, 110], [759, 110]], np.int32))
    result = foreground_ruling_counts(foreground)
    assert result["hough_status"] == "malformed_response"
    assert result["near_horizontal_long_bands"] is None
    assert not result["audit_limit_reached"]
    audit = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert audit["reason"] == "residual_ruling_audit_malformed"


def test_unsubstantiated_hough_response_is_not_a_budget_overrun(monkeypatch):
    foreground = np.zeros((520, 760), np.uint8)
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs:
                        np.array([[0, 110, 759, 110]], dtype=np.int32))
    status = foreground_ruling_counts(foreground)
    assert status["hough_status"] == "insufficient_support"
    assert status["near_horizontal_long_bands"] is None
    assert not status["audit_limit_reached"]
    verdict = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert verdict["reason"] == "residual_ruling_audit_insufficient_support"


def test_actual_budget_exhaustion_provenance_is_preserved(monkeypatch):
    foreground = np.zeros((520, 760), np.uint8)
    oversized = np.tile(np.array([[0, 110, 759, 110]], np.int32),
                        (MAX_RULING_CANDIDATES + 1, 1))
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs: oversized)
    result = foreground_ruling_counts(foreground)
    assert result["hough_status"] == "budget_exceeded"
    assert result["near_horizontal_long_bands"] is None
    assert result["audit_limit_reached"]


@pytest.mark.parametrize("thickness", [25, 35])
def test_visually_merged_crossing_is_not_certified_as_one_physical_band(thickness):
    foreground = np.zeros((520, 760), np.uint8)
    cv2.line(foreground, (0, 120), (759, 136), 255, thickness)
    cv2.line(foreground, (0, 136), (759, 120), 255, thickness)
    result = foreground_ruling_counts(foreground)
    assert result["near_horizontal_long_bands"] is None
    assert result["hough_status"] == "insufficient_support"
    verdict = assess_support(_context(
        foreground, lines=[Box(40, 300, 300, 20)],
        words=[Box(50, 305, 80, 12)], components=[Box(50, 305, 12, 12)] * 12,
    ))
    assert verdict["reason"] == "residual_ruling_audit_insufficient_support"


def test_absent_optional_mask_is_not_accepted_in_required_engine_audit():
    from types import SimpleNamespace

    compat = SimpleNamespace(
        width=760, height=520, original_width=760, original_height=520,
        lines=[Box(40, 100, 230, 18)], words=[Box(50, 102, 70, 14)],
        components=[Box(50, 102, 10, 12)] * 16, x_height_px=20.0,
    )
    from princess_graphology.evidence_support import support_warning
    assert support_warning(compat) is None
    checked = assess_support(compat, require_ruling_audit=True)
    assert checked["reason"] == "residual_ruling_audit_unavailable"
    assert checked["ruling"]["near_horizontal_long_bands"] is None


def test_required_audit_parameter_cannot_be_a_truthy_singleton_tuple():
    """Python's trailing comma must never change an explicit False into True."""
    mask = np.zeros((520, 760), np.uint8)
    ctx = _context(mask, lines=[Box(50, 100, 100, 15)],
                   words=[Box(50, 102, 40, 12)],
                   components=[Box(50, 102, 10, 10)] * 12)
    with pytest.raises(ValueError, match="requirement must be boolean"):
        assess_support(ctx, require_ruling_audit=(False,))


def _bridge_ruling(*, connector_type, width=760, height=520):
    """Two distinct long rules with thin perpendicular graph-paper bridges."""
    mask = np.zeros((height, width), np.uint8)
    cv2.line(mask, (0, 100), (width - 1, 105), 255, 2)
    cv2.line(mask, (0, 170), (width - 1, 175), 255, 2)
    if connector_type == "probe_columns":
        xs = np.unique(np.rint(np.linspace(0, width - 1, 17)).astype(int))
    elif connector_type == "shifted_probes":
        xs = np.unique(np.rint(np.linspace(0, width - 1, 17)).astype(int) + 4)
    elif connector_type in ("periodic_20", "periodic_40"):
        pitch = 20 if connector_type == "periodic_20" else 40
        xs = range(0, width, pitch)
    else:
        raise ValueError("unknown synthetic bridge layout")
    for x in xs:
        if 0 <= int(x) < width:
            cv2.line(mask, (int(x), 90), (int(x), 185), 255, 1)
    return mask


@pytest.mark.parametrize("connector_type", [
    "probe_columns", "shifted_probes", "periodic_20", "periodic_40",
])
def test_connected_grid_lines_never_qualify_as_one_physical_ribbon(connector_type):
    """The 17-point signature may connect two rules through thin grid lines."""
    mask = _bridge_ruling(connector_type=connector_type)
    result = foreground_ruling_counts(mask)
    assert result["dense_horizontal_bands"] == 0
    assert (result["hough_status"] == "insufficient_support"
            and result["near_horizontal_long_bands"] is None) or (
            result["hough_status"] == "checked"
            and result["near_horizontal_long_bands"] >= 2
    ), result
    context = _context(
        mask, lines=[Box(30, 300, 300, 24)],
        words=[Box(35, 304, 65, 15)], components=[Box(35, 304, 10, 12)] * 12,
    )
    verdict = assess_support(context)
    assert verdict["reason"] in (
        "residual_page_ruling", "residual_ruling_audit_insufficient_support",
    )


@pytest.mark.parametrize("delta_y", [3, 5, 7, 9, 15])
def test_thin_shallow_rules_are_detected_or_explicitly_unqualified(delta_y):
    mask = np.zeros((520, 760), np.uint8)
    for top in (150, 180):
        cv2.line(mask, (0, top), (759, top + delta_y), 255, 1)
    result = foreground_ruling_counts(mask)
    assert result["dense_horizontal_bands"] == 0
    assert (result["hough_status"] == "insufficient_support"
            and result["near_horizontal_long_bands"] is None) or (
            result["hough_status"] == "checked"
            and result["near_horizontal_long_bands"] >= 2
    ), result
    verdict = assess_support(_context(
        mask, lines=[Box(50, 310, 350, 22)],
        words=[Box(60, 313, 75, 15)], components=[Box(60, 313, 12, 12)] * 12,
    ))
    assert verdict["reason"] in (
        "residual_page_ruling", "residual_ruling_audit_insufficient_support",
    )


@pytest.mark.parametrize("thickness", [1, 2, 3, 7, 15, 25, 35, 65])
def test_secondary_line_evidence_never_splits_a_single_stroke(thickness):
    mask = np.zeros((520, 760), np.uint8)
    cv2.line(mask, (0, 110), (759, 110), 255, thickness)
    result = foreground_ruling_counts(mask)
    assert result["near_horizontal_long_bands"] == 1
    assert result["hough_status"] == "checked"


def test_supplementary_line_detector_does_not_hallucinate_text_ruling():
    mask = np.zeros((520, 760), np.uint8)
    for i, text in enumerate(("ALPHA BETA GAMMA", "DELTA ZETA ETA",
                              "THETA IOTA KAPPA")):
        cv2.putText(mask, text, (40, 140 + i * 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2, cv2.LINE_AA)
    result = foreground_ruling_counts(mask)
    assert result["hough_status"] == "checked"
    assert result["near_horizontal_long_bands"] == 0
    assert result["dense_horizontal_bands"] == 0


def test_supplementary_line_detector_does_not_split_a_real_underline():
    mask = np.zeros((520, 760), np.uint8)
    cv2.putText(mask, "ALPHA BETA GAMMA", (40, 140),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2, cv2.LINE_AA)
    cv2.line(mask, (0, 175), (759, 175), 255, 1)
    result = foreground_ruling_counts(mask)
    assert result["hough_status"] == "checked"
    assert result["near_horizontal_long_bands"] == 1


def test_secondary_peak_response_not_published_as_physical_band_count(monkeypatch):
    from princess_graphology import evidence_support as module
    mask = np.zeros((520, 760), np.uint8)
    # No ink: a mocked strong peak still requires measured foreground support.
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cv2, "HoughLines", lambda *args, **kwargs:
        np.array([[[110.0, np.pi / 2]], [[140.0, np.pi / 2]]], np.float32),
    )
    count, status = module._supplementary_hough_bands(mask)
    assert (count, status) == (0, "checked")
    result = foreground_ruling_counts(mask)
    assert result["near_horizontal_long_bands"] == 0
    assert result["hough_status"] == "checked"


def test_supplementary_hough_invalid_layout_and_budget_are_distinct(monkeypatch):
    from princess_graphology import evidence_support as module
    mask = np.zeros((520, 760), np.uint8)
    monkeypatch.setattr(cv2, "HoughLines", lambda *args, **kwargs:
                        np.ones((2, 2, 2), np.float32))
    assert module._supplementary_hough_bands(mask) == (None, "malformed_response")
    monkeypatch.setattr(cv2, "HoughLines", lambda *args, **kwargs:
                        np.ones((module.MAX_HOUGH_SEGMENTS + 1, 1, 2), np.float32))
    assert module._supplementary_hough_bands(mask) == (None, "budget_exceeded")


def test_supplementary_detector_not_run_for_clear_primary_ruling(monkeypatch):
    mask = np.zeros((520, 760), np.uint8)
    for y in (110, 190):
        cv2.line(mask, (0, y), (759, y), 255, 3)
    def unexpected_fallback(*args, **kwargs):
        pytest.fail("secondary Hough must not run when primary already found two bands")
    monkeypatch.setattr(cv2, "HoughLines", unexpected_fallback)
    audit = foreground_ruling_counts(mask)
    assert audit["hough_status"] == "checked"
    assert audit["near_horizontal_long_bands"] == 2


def test_supplementary_detector_not_run_for_heavy_single_stroke(monkeypatch):
    mask = np.zeros((520, 760), np.uint8)
    cv2.line(mask, (0, 110), (759, 110), 255, 65)
    def unexpected_fallback(*args, **kwargs):
        pytest.fail("secondary Hough must not reinterpret dense thick-stroke peaks")
    monkeypatch.setattr(cv2, "HoughLines", unexpected_fallback)
    audit = foreground_ruling_counts(mask)
    assert audit["hough_status"] == "checked"
    assert audit["near_horizontal_long_bands"] == 1


def test_supplementary_hough_border_rounding_is_not_malformed(monkeypatch):
    from princess_graphology import evidence_support as module
    mask = np.zeros((520, 760), np.uint8)
    mask[519, :] = 255
    # A valid float rho < height can round to height before int conversion.
    monkeypatch.setattr(cv2, "HoughLines", lambda *args, **kwargs:
                        np.array([[[519.8, np.pi / 2]]], np.float32))
    count, status = module._supplementary_hough_bands(mask)
    assert (count, status) == (1, "checked")
