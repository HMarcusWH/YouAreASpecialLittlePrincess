import json
from hashlib import sha256

import cv2
import numpy as np
import pytest

from evaluation.segmentation.benchmark import evaluate, match, run_manifest, summarize, validate_record
from princess_graphology.models import Box


def example():
    return {"specimen_id": "gen-1", "writer_group": "synthetic-1",
            "capture_group": "synthetic-page-1", "paper": "blank",
            "sha256": "a" * 64, "image_path": "image.png",
            "lines": [[10, 20, 70, 10]], "words": [[10, 20, 70, 10]]}


def test_matching_is_one_to_one():
    box = Box(10, 20, 70, 10)
    result = match([box], [box, box])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 0)
    assert result["precision"] == 0.5 and result["recall"] == 1.0
    assert match([], [])["f1"] == 1.0


def test_unannotated_words_are_not_empty_words():
    example_record = example()
    example_record.pop("words")
    assert validate_record(example_record, "synthetic")[1] is None
    example_record["words"] = []
    assert validate_record(example_record, "synthetic")[1] == ()
    with pytest.raises(ValueError, match="rights"):
        validate_record(example(), "holdout", allow_real=True)


def test_benchmark_is_readonly_and_hash_verified(tmp_path):
    image = np.full((180, 360), 255, np.uint8)
    cv2.line(image, (20, 50), (330, 50), 0, 3)
    raw = cv2.imencode(".png", image)[1].tobytes()
    (tmp_path / "image.png").write_bytes(raw)
    record = example()
    record["sha256"] = sha256(raw).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "split": "synthetic",
                                    "specimens": [record]}))
    report = run_manifest(manifest, tmp_path)
    assert report["summary"]["overall"]["count"] == 1
    assert "image_path" not in json.dumps(report)
    record["sha256"] = "f" * 64
    manifest.write_text(json.dumps({"schema_version": 1, "split": "synthetic",
                                    "specimens": [record]}))
    with pytest.raises(ValueError, match="SHA256"):
        run_manifest(manifest, tmp_path)


def test_invalid_and_safe_zero_word_metrics():
    image = np.full((180, 360, 3), 255, np.uint8)
    row = example()
    result = evaluate(image, row)
    assert result["status"] == "MEASURED"
    assert result["false_zero_words"] is True
    assert summarize([result])["overall"]["false_zero_words"] == 1
