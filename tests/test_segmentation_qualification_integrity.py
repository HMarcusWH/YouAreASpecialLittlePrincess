"""Synthetic-only frozen holdout adversarial tests: NEVER human handwriting."""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest

from evaluation.segmentation import benchmark
from evaluation.segmentation.qualification import (
    current_local_identity,
    predeclared_holdout_gate_v2,
    public_safe_receipt,
    run_frozen_synthetic_qualification,
    score_holdout,
)
from princess_graphology.models import Box


TARGETS = {
    "minimum_holdout_n": 1,
    "minimum_holdout_writers": 1,
    "minimum_nonempty_line_n": 1,
    "minimum_nonempty_word_n": 1,
    "min_line_nonempty_macro_f1": 0.0,
    "min_word_nonempty_macro_f1": 0.0,
    "min_line_coverage": 1.0,
    "min_word_coverage": 1.0,
    "min_nonempty_line_coverage": 1.0,
    "min_nonempty_word_coverage": 1.0,
    "max_false_zero_words": 0,
}


def _fixtures(tmp_path, holdout_n=1):
    root = tmp_path / "images"
    root.mkdir(exist_ok=True)
    manifests = {}
    for split, count in (("development", 1), ("validation", 1), ("holdout", holdout_n)):
        rows = []
        for i in range(count):
            image = np.full((140, 340, 3), 251, np.uint8)
            cv2.putText(image, f"{split[:2]}{i}", (18, 80), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (10, 10, 10), 3)
            raw = cv2.imencode(".png", image)[1].tobytes()
            filename = f"{split}-{i}.png"
            (root / filename).write_bytes(raw)
            rows.append({
                "specimen_id": f"{split}-fixture-{i}",
                "writer_group": f"{split}-writer-{i}",
                "capture_group": f"{split}-capture-{i}",
                "source_specimen_group": f"{split}-source-{i}",
                "image_path": filename,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "paper": "blank",
                "lines": [[10, 45, 160, 45]],
                "words": [[10, 45, 160, 45]],
            })
        path = tmp_path / (split + ".json")
        path.write_text(json.dumps({
            "schema_version": 2, "annotation_frame": "original_image",
            "split": split, "synthetic": True, "specimens": rows,
        }), encoding="utf-8")
        manifests[split] = path
    policy = tmp_path / "policy.json"
    _freeze_policy(manifests, policy)
    return manifests, policy, root


def _freeze_policy(manifests, path, *, thresholds=None):
    policy = {"schema_version": 2, "mode": "synthetic",
              "profile": "qualified-v2",
              **{split + "_manifest_sha256": hashlib.sha256(p.read_bytes()).hexdigest()
                 for split, p in manifests.items()},
              **current_local_identity(),
              "thresholds": dict(TARGETS if thresholds is None else thresholds)}
    path.write_text(json.dumps(policy), encoding="utf-8")


def _fake_results(manifests, *, drop=0, refuse_last=False):
    hold = json.loads(manifests["holdout"].read_text())
    rows = []
    for i, item in enumerate(hold["specimens"]):
        box = Box(10, 45, 160, 45)
        success = benchmark.match([box], [box])
        rejected = refuse_last and i == len(hold["specimens"]) - 1
        rows.append({"specimen_id": item["specimen_id"], "split": "holdout",
                     "paper": item["paper"], "status": "REJECTED" if rejected else "MEASURED",
                     "line_reference_n": 1, "word_reference_n": 1,
                     "lines": None if rejected else success,
                     "words": None if rejected else success,
                     "false_zero_words": None if rejected else False})
    return {"version": 2, "profile": "qualified-v2", "split": "holdout",
            "manifest_sha256": hashlib.sha256(manifests["holdout"].read_bytes()).hexdigest(),
            # Deliberately false aggregate: qualification must compute from the rows.
            "summary": {"overall": {"count": 999999, "lines": {"macro_f1": 1}}},
            "results": rows[:len(rows) - drop] if drop else rows}


def test_legacy_aggregate_cannot_be_accepted_even_when_fabricated():
    fake = {"overall": {"count": 10**9, "measured": 10**9,
                         "lines": {"macro_f1": 1.0}, "words": {"macro_f1": 1.0}}}
    assert score_holdout(fake, {"protocol_qualified": True})["accepted"] is False


def test_pinned_synthetic_qualification_recomputes_summary_and_never_authorizes(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    rows = _fake_results(manifests)
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: rows)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"], manifests["holdout"],
        policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_PASS"
    assert receipt["specimen_count"] == 1  # Not the 999999 supplied summary.
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"
    assert receipt["engineering_gates"]["min_nonempty_line_coverage"]


def test_one_perfect_image_cannot_pass_a_hundred_image_holdout(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path, holdout_n=100)
    monkeypatch.setattr(
        benchmark, "run_manifest",
        lambda *a, **k: _fake_results(manifests, drop=99),
    )
    with pytest.raises(ValueError, match="coverage mismatch"):
        run_frozen_synthetic_qualification(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy, root,
        )


def test_one_rejected_hard_image_fails_full_coverage(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path, holdout_n=2)
    monkeypatch.setattr(benchmark, "run_manifest",
                        lambda *a, **k: _fake_results(manifests, refuse_last=True))
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"], manifests["holdout"],
        policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert not receipt["engineering_gates"]["min_line_coverage"]
    assert not receipt["engineering_gates"]["min_nonempty_word_coverage"]


@pytest.mark.parametrize("overlap", [
    "writer_group", "capture_group", "source_specimen_group", "sha256", "specimen_id",
])
def test_every_pair_of_partitions_is_disjoint(overlap, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    val = json.loads(manifests["validation"].read_text())
    dev = json.loads(manifests["development"].read_text())
    val["specimens"][0][overlap] = dev["specimens"][0][overlap]
    manifests["validation"].write_text(json.dumps(val))
    _freeze_policy(manifests, policy)
    with pytest.raises(ValueError, match="leakage"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


@pytest.mark.parametrize("bad", ["holdout", "validation", "development"])
def test_mutated_manifest_fails_frozen_digest(bad, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    manifest = json.loads(manifests[bad].read_text())
    manifest["specimens"][0]["paper"] = "grid"
    manifests[bad].write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="digest mismatch"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


@pytest.mark.parametrize("key", [
    "source_commit_sha", "analysis_config_sha256", "evaluator_sha256",
    "qualification_sha256",
])
def test_code_and_processing_identity_are_checked_against_checkout(key, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    p = json.loads(policy.read_text())
    p[key] = "0" * len(p[key])
    policy.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="identity mismatch"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


@pytest.mark.parametrize("target", ["min_line_coverage", "minimum_holdout_n"])
def test_unset_threshold_is_never_an_approval(target, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    p = json.loads(policy.read_text())
    p["thresholds"][target] = None
    policy.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="invalid frozen"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_annotation_removed_is_rejected_in_frozen_holdout(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    item = json.loads(manifests["holdout"].read_text())
    item["specimens"][0].pop("lines")
    manifests["holdout"].write_text(json.dumps(item))
    _freeze_policy(manifests, policy)
    with pytest.raises(ValueError, match="record shape"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_real_or_unknown_source_is_never_admitted_by_synthetic_runner(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    doc = json.loads(manifests["holdout"].read_text())
    doc["synthetic"] = False
    manifests["holdout"].write_text(json.dumps(doc))
    _freeze_policy(manifests, policy)
    with pytest.raises(ValueError, match="real-data qualification not authorized"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_public_receipt_cannot_echo_private_identifiers():
    secret = "PRIVATE-WRITER-OR-IMAGE-LOCATION"
    entry = {"kind": "segmentation-qualification/2", "mode": "synthetic",
             "public_qualification": "NOT_AUTHORIZED",
             "decision": "ENGINEERING_PASS", "specimen_count": 1,
             "specimen_id": secret, "image_path": secret,
             "manifest_digest": secret, "secret_data": {"name": secret}}
    output = public_safe_receipt(entry)
    assert secret not in json.dumps(output)
    assert "manifest_digest" not in output
    assert output["specimen_count"] is None
    assert output["public_qualification"] == "NOT_AUTHORIZED"
    with pytest.raises(ValueError, match="no publishable"):
        public_safe_receipt({**entry, "mode": "real"})


def test_actual_synthetic_image_pipeline_fails_closed_or_scores_without_authorization(tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"], manifests["holdout"],
        policy, root,
    )
    assert receipt["decision"] in ("ENGINEERING_PASS", "ENGINEERING_FAIL")
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"
    assert receipt["specimen_count"] == 1
    assert len(receipt["engineering_gates"]) == len(TARGETS)


def test_inconsistent_f1_cannot_be_laundered_into_a_passing_receipt(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests)
    fake["results"][0]["lines"]["tp"] = 0  # F1 and bookkeeping still claim success.
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    with pytest.raises(ValueError, match="inconsistent scored metric"):
        run_frozen_synthetic_qualification(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy, root,
        )


def test_private_real_cli_error_does_not_expose_file_path(monkeypatch, capsys):
    import sys

    secret = "/private/a_persons_handwriting_and_name.jpg"

    def failed(*args, **kwargs):
        raise FileNotFoundError(secret)

    monkeypatch.setattr(benchmark, "run_manifest", failed)
    monkeypatch.setattr(sys, "argv", [
        "segmentation-benchmark", "--manifest", secret, "--image-root", secret,
        "--allow-authorized-real",
    ])
    with pytest.raises(SystemExit) as err:
        benchmark.main()
    assert err.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "Protected evaluation failed" in captured.err


def test_validation_split_is_evaluable_only_as_explicit_synthetic_fixture(tmp_path):
    from evaluation.segmentation.benchmark import run_manifest

    manifests, _, image_root = _fixtures(tmp_path)
    result = run_manifest(
        manifests["validation"], image_root, profile="qualified-v2",
        synthetic_split=True,
    )
    assert result["split"] == "validation"
    assert result["manifest_sha256"] == hashlib.sha256(
        manifests["validation"].read_bytes()
    ).hexdigest()
    assert len(result["results"]) == 1
    with pytest.raises(ValueError, match="authorization"):
        run_manifest(manifests["validation"], image_root, profile="qualified-v2")


@pytest.mark.parametrize("split", ("development", "validation", "holdout"))
def test_unmarked_validation_or_other_split_cannot_claim_fixture_authority(split, tmp_path):
    from evaluation.segmentation.benchmark import run_manifest

    manifests, _, root = _fixtures(tmp_path)
    manifest = manifests[split]
    raw = json.loads(manifest.read_text())
    raw["synthetic"] = False
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="authorization"):
        run_manifest(manifest, root, synthetic_split=True)


def test_duplicate_frozen_policy_keys_fail_even_when_values_match(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    raw = policy.read_text()
    policy.write_text(raw.replace('"schema_version": 2',
                                  '"schema_version": 2, "schema_version": 2', 1))
    with pytest.raises(ValueError, match="duplicate JSON"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_duplicate_nested_threshold_keys_fail_before_scoring(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    raw = policy.read_text()
    policy.write_text(raw.replace('"min_line_coverage": 1.0',
                                  '"min_line_coverage": 1.0, "min_line_coverage": 0.0',
                                  1))
    with pytest.raises(ValueError, match="duplicate JSON"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


@pytest.mark.parametrize("split", ("development", "validation", "holdout"))
def test_duplicate_specimen_record_keys_fail_before_digest_check(split, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    manifest = manifests[split]
    raw = manifest.read_text()
    manifest.write_text(raw.replace('"specimen_id":',
                                    '"specimen_id": "injected", "specimen_id":', 1))
    # Freeze the mutated bytes: only the strict parser should cause the failure.
    _freeze_policy(manifests, policy)
    with pytest.raises(ValueError, match="duplicate JSON"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_duplicate_keys_rejected_in_direct_benchmark_invocation(tmp_path):
    from evaluation.segmentation.benchmark import run_manifest

    manifests, _, image_root = _fixtures(tmp_path)
    manifest = manifests["validation"]
    raw = manifest.read_text()
    manifest.write_text(raw.replace('"annotation_frame": "original_image"',
                                    '"annotation_frame": "original_image", "annotation_frame": "original_image"',
                                    1))
    with pytest.raises(ValueError, match="duplicate JSON"):
        run_manifest(manifest, image_root, synthetic_split=True)


def test_nonstandard_nonfinite_json_constant_fails_before_threshold_review(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    raw = policy.read_text()
    policy.write_text(raw.replace('"min_line_coverage": 1.0',
                                  '"min_line_coverage": NaN', 1))
    with pytest.raises(ValueError, match="nonfinite JSON"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )
