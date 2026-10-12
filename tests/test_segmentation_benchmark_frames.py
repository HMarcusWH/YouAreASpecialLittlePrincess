"""Evaluation-v2 frame mapping and fair shadow metrics, synthetic only."""
import json
from hashlib import sha256

import cv2
import numpy as np
import pytest

from evaluation.segmentation.benchmark import (
    evaluate, match, run_manifest, summarize, to_analysis_boxes, validate_record,
)
from princess_graphology.models import Box


def record(digest="a" * 64):
    return {"specimen_id": "synthetic", "writer_group": "synthetic-a",
            "capture_group": "capture-a", "paper": "blank",
            "image_path": "sample.png", "sha256": digest,
            "lines": [[10, 20, 80, 15]], "words": [[10, 20, 80, 15]]}


def test_resize_frame_maps_all_corners():
    box = Box(40, 20, 80, 20)
    mapped = to_analysis_boxes((box,), [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]],
                               source_size=(400, 200), destination_size=(200, 100))
    assert mapped == (Box(20, 10, 40, 10),)


def test_rotation_mapping_uses_all_four_corners():
    out = to_analysis_boxes((Box(20, 10, 30, 20),),
                            [[0, -1, 80], [1, 0, 0], [0, 0, 1]],
                            source_size=(100, 100), destination_size=(100, 100))
    assert out == (Box(50, 20, 20, 30),)


def test_annotation_frame_rejects_invalid_matrix_and_out_of_bounds():
    with pytest.raises(ValueError, match="transform"):
        to_analysis_boxes((Box(0, 0, 2, 3),), np.zeros((3, 3)),
                          source_size=(10, 10), destination_size=(10, 10))
    with pytest.raises(ValueError, match="exceeds"):
        to_analysis_boxes((Box(9, 9, 2, 2),), np.eye(3),
                          source_size=(10, 10), destination_size=(10, 10))


def test_shadow_scores_aggregate_independently():
    base = {"specimen_id": "fixture-1", "split": "synthetic", "paper": "blank",
            "status": "MEASURED", "data_origin": "SYNTHETIC_FIXTURE", "words": match([], []),
            "lines": match([Box(10, 10, 50, 10)], [Box(10, 10, 50, 10)]),
            "line_shadow": match([Box(10, 10, 50, 10)], []),
            "word_shadow": match([], []), "false_zero_words": False}
    summary = summarize([base])["overall"]
    assert summary["lines"]["macro_f1"] == 1
    assert summary["line_shadow"]["macro_f1"] == 0
    assert summary["word_shadow"]["annotated_n"] == 1
    assert summary["line_shadow"]["macro_count_mae"] == 1


def test_v2_original_frame_manifest_roundtrip(tmp_path):
    im = np.full((180, 400), 255, np.uint8)
    cv2.line(im, (20, 75), (380, 75), 0, 3)
    image = cv2.imencode(".png", im)[1].tobytes()
    (tmp_path / "sample.png").write_bytes(image)
    item = record(sha256(image).hexdigest())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 2, "split": "synthetic",
                                    "annotation_frame": "original_image",
                                    "specimens": [item]}))
    result = run_manifest(manifest, tmp_path, shadow_projection=True, shadow_words=True)
    assert result["annotation_frame"] == "original_image"
    assert result["data_origin"] == "SYNTHETIC_FIXTURE"
    assert result["summary"]["data_origin"] == "SYNTHETIC_FIXTURE"
    assert all(row["data_origin"] == "SYNTHETIC_FIXTURE" for row in result["results"])
    assert result["summary"]["overall"]["line_shadow"]["annotated_n"] == 1
    assert result["summary"]["overall"]["word_shadow"]["annotated_n"] == 1


def test_v2_requires_explicit_frame_and_excessive_boxes_rejected(tmp_path):
    sample = record()
    with pytest.raises(ValueError, match="excessive"):
        validate_record({**sample, "lines": [[1, 1, 2, 2]] * 4097}, "synthetic")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 2, "split": "synthetic", "specimens": []}))
    with pytest.raises(ValueError, match="annotation_frame"):
        run_manifest(manifest, tmp_path)


def test_evaluate_rejects_unsupported_frame():
    im = np.full((100, 200), 255, np.uint8)
    with pytest.raises(ValueError, match="frame"):
        evaluate(im, record(), annotation_frame="pixel_magic")

def test_missing_line_annotation_is_unknown_not_an_empty_page():
    im = np.full((100, 200), 255, np.uint8)
    item = record()
    item.pop("lines")
    assert validate_record(item, "synthetic")[0] is None
    result = evaluate(im, item, split="synthetic")
    assert result["line_reference_n"] is None
    assert result["lines"] is None
    summary = summarize([result])["overall"]["lines"]
    assert summary["eligible_n"] == 0
    assert summary["annotation_unknown_n"] == 1
    assert summary["nonempty_macro_f1"] is None


def test_empty_reference_does_not_improve_nonempty_handwriting_accuracy():
    base = {"specimen_id": "synthetic-blank", "split": "synthetic",
            "data_origin": "SYNTHETIC_FIXTURE",
            "paper": "blank", "status": "MEASURED",
            "line_reference_n": 0, "word_reference_n": 0,
            "lines": match([], []), "words": match([], []),
            "false_zero_words": False}
    group = summarize([base])["overall"]["lines"]
    assert group["macro_f1"] == 1
    assert group["nonempty_macro_f1"] is None
    assert group["nonempty_eligible_n"] == 0
    assert group["empty_correct_n"] == 1


def test_rejected_nonempty_sample_remains_in_coverage_denominator():
    measured = {"specimen_id": "some-ink", "split": "synthetic",
                "data_origin": "SYNTHETIC_FIXTURE",
                "paper": "blank", "status": "MEASURED",
                "line_reference_n": 1, "word_reference_n": 1,
                "lines": match([Box(1, 1, 20, 5)], [Box(1, 1, 20, 5)]),
                "words": match([Box(1, 1, 20, 5)], [Box(1, 1, 20, 5)]),
                "false_zero_words": False}
    rejected = {"specimen_id": "hard-ink", "split": "synthetic",
                "paper": "grid", "status": "REJECTED", "data_origin": "SYNTHETIC_FIXTURE",
                "line_reference_n": 1, "word_reference_n": 1,
                "lines": None, "words": None, "false_zero_words": None}
    block = summarize([measured, rejected])["overall"]
    assert block["count"] == 2 and block["rejected"] == 1
    assert block["lines"]["coverage"] == 0.5
    assert block["words"]["nonempty_coverage"] == 0.5
    assert block["lines"]["nonempty_macro_f1"] == 1
