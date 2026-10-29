"""Rights-safe Issue #92 four-profile probe; no real handwriting sources."""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest

from grid_v2_cases import grid_only, page
from evaluation.segmentation.issue92_probe import (
    CANDIDATES, PROBE_VERSION, run_synthetic_manifest,
)
from princess_app.application.intake import analysis_config_sha256


def _manifest(tmp_path, cases, *, version=2, split="synthetic",
              synthetic=True, annotation_frame="original_image"):
    rows = []
    for index, (image, paper, annotations) in enumerate(cases):
        payload = cv2.imencode(".png", image)[1].tobytes()
        name = f"generated-{index}.png"
        (tmp_path / name).write_bytes(payload)
        row = {
            "specimen_id": f"generated-{index}",
            "writer_group": f"synthetic-writer-{index}",
            "capture_group": f"synthetic-capture-{index}",
            "image_path": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "paper": paper,
            **annotations,
        }
        rows.append(row)
    path = tmp_path / "synthetic-manifest.json"
    path.write_text(json.dumps({
        "schema_version": version, "split": split, "synthetic": synthetic,
        "annotation_frame": annotation_frame, "specimens": rows,
    }), encoding="utf-8")
    return path


def _known_positive():
    image, ink, boxes = page(ruling="gray", pen="black")
    ys, xs = np.where(ink > 0)
    assert len(xs) > 0
    line = [int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
    return image, "grid", {"lines": [line], "words": [list(box) for box in boxes]}


def test_same_decoded_input_is_compared_in_four_distinct_pinned_profiles(tmp_path):
    path = _manifest(tmp_path, [_known_positive()])
    result = run_synthetic_manifest(path, tmp_path)
    assert result["probe_version"] == PROBE_VERSION
    assert result["data_origin"] == "SYNTHETIC_FIXTURE"
    assert result["public_qualification"] == "NOT_AUTHORIZED"
    assert result["thresholds_or_accuracy_approval"] is None
    case = result["cases"][0]
    assert case["reference_lines_n"] == 1
    assert case["reference_words_n"] == 3
    assert [row["profile"] for row in case["profiles"]] == [c[0] for c in CANDIDATES]
    assert len({row["analysis_config_sha256"] for row in case["profiles"]}) == 4
    assert case["profiles"][-1]["analysis_config_sha256"] == analysis_config_sha256(
        grid_profile="qualified-v2", evidence_guard_enabled=True,
    )
    assert case["profiles"][-1]["status"] == "MEASURED"
    assert case["profiles"][-1]["line_count"] == 1
    assert case["profiles"][-1]["word_group_count"] >= 2
    assert case["profiles"][-1]["support_abstention"] is None
    assert case["profiles"][-1]["line_match"] is not None
    assert case["profiles"][-1]["word_match"] is not None
    assert case["profiles"][-1]["word_audit"] is not None
    assert result["profiles"]["qualified-v2-guard-v5"]["lines"]["nonempty_coverage"] == 1.0
    encoded = json.dumps(result, allow_nan=False)
    for forbidden in ("generated-0", "synthetic-writer", "image_path",
                      "input_pixels_sha256", "source_image_sha256", "capture_group"):
        assert forbidden not in encoded


def test_unknown_annotations_remain_unknown_not_ground_truth_zero(tmp_path):
    image, _, _ = page(ruling="none")
    path = _manifest(tmp_path, [(image, "blank", {})])
    result = run_synthetic_manifest(path, tmp_path)
    assert result["cases"][0]["reference_lines_n"] is None
    assert result["cases"][0]["reference_words_n"] is None
    for row in result["cases"][0]["profiles"]:
        assert row["line_match"] is None and row["word_match"] is None
        assert row["false_zero_words"] is None
    assert result["profiles"]["qualified-v2"]["lines"]["nonempty_coverage"] is None


def test_true_blank_is_not_a_measured_zero_under_v5(tmp_path):
    image, _, _ = grid_only(ruling="none")
    path = _manifest(tmp_path, [(image, "blank", {"lines": [], "words": []})])
    result = run_synthetic_manifest(path, tmp_path)
    guarded = result["cases"][0]["profiles"][-1]
    assert guarded["status"] == "UNQUALIFIED"
    assert guarded["line_count"] is None and guarded["word_group_count"] is None
    assert guarded["line_match"] is None and guarded["word_match"] is None
    assert guarded["baseline_points"] == 0
    assert guarded["support_abstention"]


@pytest.mark.parametrize("change", [
    {"split": "development"}, {"split": "holdout"},
    {"synthetic": False}, {"synthetic": "true"},
    {"annotation_frame": "analysis_canvas"},
    {"version": 1},
])
def test_real_or_unqualified_manifest_mode_fails_before_image_read(tmp_path, change):
    image, _, _ = grid_only(ruling="none")
    keys = dict(version=2, split="synthetic", synthetic=True,
                annotation_frame="original_image")
    keys.update(change)
    path = _manifest(tmp_path, [(image, "blank", {"lines": []})], **keys)
    with pytest.raises(ValueError, match="synthetic-only"):
        run_synthetic_manifest(path, tmp_path)


def test_digest_mismatch_rejected_before_decoding(tmp_path, monkeypatch):
    from evaluation.segmentation import issue92_probe
    image, _, _ = grid_only(ruling="none")
    path = _manifest(tmp_path, [(image, "blank", {"lines": []})])
    doc = json.loads(path.read_text())
    doc["specimens"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(doc))
    def decoder_must_not_run(*_args, **_kwargs):
        pytest.fail("unverified bytes reached OpenCV")
    monkeypatch.setattr(issue92_probe.cv2, "imdecode", decoder_must_not_run)
    with pytest.raises(ValueError, match="SHA256"):
        run_synthetic_manifest(path, tmp_path)


def test_symlinked_sample_is_rejected_without_decoding(tmp_path):
    image, _, _ = grid_only(ruling="none")
    path = _manifest(tmp_path, [(image, "blank", {"lines": []})])
    original = tmp_path / "generated-0.png"
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(original)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported on this platform")
    doc = json.loads(path.read_text())
    doc["specimens"][0]["image_path"] = "linked.png"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="admission"):
        run_synthetic_manifest(path, tmp_path)


def test_duplicate_manifest_keys_and_nonfinite_json_fail_closed(tmp_path):
    path = tmp_path / "synthetic-manifest.json"
    path.write_bytes(b'{"schema_version":2,"schema_version":2}')
    with pytest.raises(ValueError, match="duplicate"):
        run_synthetic_manifest(path, tmp_path)
    path.write_bytes(b'{"schema_version":NaN}')
    with pytest.raises(ValueError, match="nonfinite"):
        run_synthetic_manifest(path, tmp_path)
