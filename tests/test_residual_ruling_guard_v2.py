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


def test_v2_digest_changes_guarded_identity_but_preserves_disabled_production():
    assert GUARD_POLICY_VERSION == "evidence-support/2"
    legacy = ("engine:max_dimension=2200;deskew=true;" + INTAKE_POLICY_VERSION).encode()
    old_v1 = ("engine:max_dimension=2200;deskew=true;"
              "evidence_support=evidence-support/1;" + INTAKE_POLICY_VERSION).encode()
    current = analysis_config_sha256(evidence_guard_enabled=True)
    assert current != hashlib.sha256(old_v1).hexdigest()
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


def test_real_engine_accepts_predeclared_clean_ruled_handwriting_positive():
    """Reject-every-ruled-photo cannot satisfy the release engineering test.

    No real user handwriting, OCR, artificially supplied candidate boxes,
    and no catch-and-pass on a quality refusal.
    """
    from grid_v2_cases import page
    from princess_graphology.preprocessing.grid import GridQualityError
    image, true_ink, _ = page(ruling="gray", pen="black")
    engine = GraphologyEngine(grid_profile="qualified-v2",
                             deskew_enabled=False, evidence_guard_enabled=True)
    try:
        report, evidence = engine.analyze_with_evidence(image)
    except GridQualityError as exc:
        pytest.fail(f"predeclared ruled-positive was refused: {exc.code}")
    assert "evidence_support" not in report.metadata, report.metadata.get("evidence_support")
    assert report.measurements["PAGE_LINE_COUNT"].raw_value == 1
    assert report.measurements["PAGE_WORD_COUNT"].raw_value >= 2
    lines = [r for r in report.regions if r.scope == "LINE"]
    words = [r for r in report.regions if r.scope == "WORD"]
    assert len(lines) == 1 and len(words) >= 2
    transform = np.asarray(report.metadata["original_to_analysis"], np.float64)
    ink = cv2.warpPerspective(true_ink, transform, (report.width, report.height),
                              flags=cv2.INTER_NEAREST)
    for region in (*lines, *words):
        box = region.box
        assert np.count_nonzero(ink[box.y:box.y2, box.x:box.x2]) > 0
    assert any(x["scope"] == "LINE" for x in evidence["regions"])
    assert report.metadata["evidence_support_audit"]["status"] == "no_abstention_not_calibrated"
    assert report.metadata["evidence_support_audit"]["ruling"]["foreground_stage"] == "qualified_line_selected"
    assert report.metadata["evidence_support_audit"]["ruling"]["pre_line_selection"] is not None
