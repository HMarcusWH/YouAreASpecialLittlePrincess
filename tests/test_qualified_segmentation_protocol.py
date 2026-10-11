"""Protected data never in CI: exercise the protocol with synthetic manifests."""
from __future__ import annotations

import hashlib
import json

import pytest

from evaluation.segmentation.qualification import predeclared_holdout_gate, score_holdout


def data(split, writer, capture):
    return {"schema_version": 2, "annotation_frame": "original_image",
            "split": split, "specimens": [{
                "specimen_id": split + "-1", "writer_group": writer,
                "capture_group": capture, "image_path": "not-loaded-here.png",
                "sha256": ("a" if split == "development" else "b") * 64,
                "rights_decision_id": "synthetic-protocol-test"}]}


def setup(tmp_path):
    dev, hold, policy = (tmp_path / name for name in ("dev.json", "hold.json", "policy.json"))
    dev.write_text(json.dumps(data("development", "writer-a", "capture-a")))
    hold.write_text(json.dumps(data("holdout", "writer-b", "capture-b")))
    policy.write_text(json.dumps({
        "schema_version": 1,
        "holdout_manifest_sha256": hashlib.sha256(hold.read_bytes()).hexdigest(),
        "thresholds": {"minimum_holdout_n": 1, "min_line_macro_f1": 0.7,
                       "min_word_macro_f1": 0.7, "min_qualified_fraction": 0.5,
                       "max_false_zero_words": 0}}))
    return dev, hold, policy


def test_writer_disjoint_manifest_hash_and_frozen_acceptance(tmp_path):
    dev, hold, policy = setup(tmp_path)
    qualified = predeclared_holdout_gate(dev, hold, policy)
    assert qualified["protocol_qualified"]
    metrics = {"overall": {"count": 1, "measured": 1, "partial": 0,
                           "false_zero_words": 0,
                           "lines": {"macro_f1": .9}, "words": {"macro_f1": .8}}}
    assert score_holdout(metrics, qualified)["accepted"]
    metrics["overall"]["words"]["macro_f1"] = None
    assert not score_holdout(metrics, qualified)["accepted"]


def test_cross_split_writer_or_capture_leakage_is_a_hard_error(tmp_path):
    dev, hold, policy = setup(tmp_path)
    edited = data("holdout", "writer-a", "capture-b")
    hold.write_text(json.dumps(edited))
    p = json.loads(policy.read_text())
    p["holdout_manifest_sha256"] = hashlib.sha256(hold.read_bytes()).hexdigest()
    policy.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="writer_group leakage"):
        predeclared_holdout_gate(dev, hold, policy)
    edited["specimens"][0]["writer_group"] = "writer-b"
    edited["specimens"][0]["capture_group"] = "capture-a"
    hold.write_text(json.dumps(edited))
    p["holdout_manifest_sha256"] = hashlib.sha256(hold.read_bytes()).hexdigest()
    policy.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="capture_group leakage"):
        predeclared_holdout_gate(dev, hold, policy)


def test_holdout_changes_require_new_frozen_policy(tmp_path):
    dev, hold, policy = setup(tmp_path)
    item = json.loads(hold.read_text())
    item["specimens"][0]["paper"] = "gray_grid"
    hold.write_text(json.dumps(item))
    with pytest.raises(ValueError, match="predeclared"):
        predeclared_holdout_gate(dev, hold, policy)
