"""Research-only ranking; no real specimen data in CI."""
import numpy as np
import pytest
from evaluation.style_similarity.descriptors import DescriptorSet
from evaluation.style_similarity.evaluate import rank_samples, evaluate_manifest


def ds(v):
    a = np.full((4, 128), v, np.float32)
    for i in range(4):
        a[i, i] = v + i + 1
    return DescriptorSet(a, np.zeros(4, np.float32), "sift")


def test_rank_results_are_bounded_and_deterministic():
    query = ds(1)
    references = [ds(7), ds(1), ds(10)]
    ranked = rank_samples(query, references)
    assert len(ranked) == 3
    assert [x[0] for x in ranked] == [x[0] for x in rank_samples(query, references)]
    assert all(not isinstance(record, dict) for record in ranked)


def test_real_manifest_requires_explicit_gate(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text('{"schema_version":1,"split":"holdout","queries":[{"sample_id":"q",'
                 '"writer_group":"A","capture_group":"C1"}],'
                 '"references":[{"sample_id":"r","writer_group":"A","capture_group":"C2"}]}')
    with pytest.raises(ValueError, match="approved-real-data"):
        evaluate_manifest(p, image_root=tmp_path)
    p.write_text('{"schema_version":1,"split":"holdout","queries":[{"sample_id":"q",'
                 '"writer_group":"A","capture_group":"C1"}],'
                 '"references":[{"sample_id":"r","writer_group":"A","capture_group":"C1"}]}')
    with pytest.raises(ValueError, match="missing authorized sample property"):
        evaluate_manifest(p, image_root=tmp_path, authorized=True)
    # With all required fields present, the same capture must fail independently.
    valid = {
        "schema_version": 1, "split": "holdout",
        "queries": [{"sample_id": "q", "writer_group": "A", "capture_group": "same",
                     "image_path": "q.png", "rights_decision_id": "synthetic-self-generated",
                     "sha256": "a" * 64}],
        "references": [{"sample_id": "r", "writer_group": "A", "capture_group": "same",
                        "image_path": "r.png", "rights_decision_id": "synthetic-self-generated",
                        "sha256": "b" * 64}],
    }
    import json
    p.write_text(json.dumps(valid))
    with pytest.raises(ValueError, match="same-capture"):
        evaluate_manifest(p, image_root=tmp_path, authorized=True)



def test_protected_runner_exercises_both_detector_modes_with_local_synthetic_images(tmp_path):
    import hashlib
    import json
    import cv2
    image = np.full((240, 300), 255, dtype=np.uint8)
    for x in range(20, 260, 32):
        cv2.circle(image, (x, 65 + (x % 4) * 11), 7, 0, 2)
    samples = []
    for key, capture in (("q", "capture-query"), ("r", "capture-reference")):
        variant = image.copy()
        if key == "r":
            cv2.line(variant, (12, 180), (135, 181), 0, 2)
        blob = cv2.imencode(".png", variant)[1].tobytes()
        path = tmp_path / (key + ".png")
        path.write_bytes(blob)
        samples.append({
            "sample_id": key, "writer_group": "synthetic-writer-1",
            "capture_group": capture, "image_path": path.name,
            "rights_decision_id": "synthetic-self-generated",
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "split": "development",
                                    "queries": [samples[0]], "references": [samples[1]]}))
    for mode in ("sift", "fast_sift"):
        result = evaluate_manifest(manifest, image_root=tmp_path,
                                   authorized=True, detector=mode)
        assert result["queries_n"] == 1
        assert result["references_n"] == 1
        assert result["status"] == "UNVALIDATED_RESEARCH_ONLY"



def test_identical_content_is_rejected_even_with_different_capture_ids(tmp_path):
    import json
    payload = {"schema_version": 1, "split": "development",
               "queries": [{"sample_id": "q", "writer_group": "w", "capture_group": "query",
                            "image_path": "q.png", "rights_decision_id": "synthetic-self-generated",
                            "sha256": "b" * 64}],
               "references": [{"sample_id": "r", "writer_group": "w", "capture_group": "reference",
                               "image_path": "r.png", "rights_decision_id": "synthetic-self-generated",
                               "sha256": "b" * 64}]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="identical"):
        evaluate_manifest(manifest, image_root=tmp_path, authorized=True)
