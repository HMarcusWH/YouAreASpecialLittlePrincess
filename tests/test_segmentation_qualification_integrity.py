"""Synthetic-only frozen holdout adversarial tests: NEVER human handwriting."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from evaluation.segmentation import benchmark
from evaluation.segmentation.qualification import (
    _verify_loaded_evaluation_modules,
    current_local_identity,
    predeclared_holdout_gate_v2 as _production_predeclared_holdout_gate_v2,
    public_safe_receipt,
    run_frozen_synthetic_qualification as _production_run_frozen_synthetic_qualification,
    score_holdout,
)
from princess_graphology.models import Box


# The full pytest suite exercises and temporarily places alternate wheel
# metadata on sys.path (e.g. packaging 26.0 alongside the locked 26.3).
# That intentionally contaminates the parent process's distributions() view.
# Standalone evaluation stays STRICT; these synthetic unit tests supply the
# exact reviewed mapping and test the genuine check in a fresh subprocess.
REPOSITORY = Path(__file__).resolve().parents[1]
SYNTHETIC_WHEEL_METADATA = (
    b"Wheel-Version: 1.0\nGenerator: synthetic-test\n"
    b"Root-Is-Purelib: true\nTag: py3-none-any\n"
)


def _externally_provisioned_test_bootstrap(tmp_path: Path) -> Path:
    """Test the protocol using an out-of-tree bootstrap copy, not approval."""
    external = tmp_path / "external-bootstrap"
    external.mkdir(exist_ok=True)
    installed = external / "qualification_bootstrap.py"
    installed.write_bytes((REPOSITORY / "tools" / "qualification_bootstrap.py").read_bytes())
    return installed


def _bootstrap_args(bootstrap: Path, *args):
    return [sys.executable, "-I", "-S", "-B", str(bootstrap),
            "--repository", str(REPOSITORY), *args]


def _approval_file(policy: Path) -> Path:
    """Independent, immutable-for-a-test approval fixture kept outside the policy."""
    return Path(str(policy) + ".approved.sha256")


def _reapprove_policy_for_validation_test(policy: Path) -> None:
    """For tests targeting schema/runtime failures, approve the edited bytes first."""
    _approval_file(policy).write_text(hashlib.sha256(policy.read_bytes()).hexdigest())


def predeclared_holdout_gate_v2(development, validation, holdout, policy):
    return _production_predeclared_holdout_gate_v2(
        development, validation, holdout, policy,
        expected_policy_sha256=_approval_file(policy).read_text(),
    )


def run_frozen_synthetic_qualification(development, validation, holdout, policy, image_root):
    return _production_run_frozen_synthetic_qualification(
        development, validation, holdout, policy, image_root,
        expected_policy_sha256=_approval_file(policy).read_text(),
    )


@pytest.fixture(autouse=True)
def _unit_test_with_clean_reviewed_distribution_view(monkeypatch):
    from tools import verify_ci_lock as locks

    target = locks.running_target()[0].replace(".", "")
    reviewed = locks.read_lock(REPOSITORY / "requirements" / f"ci-py{target}.lock")
    installed = {**reviewed, "special-little-princess-graphology": "0.1.0"}
    monkeypatch.setattr(locks, "installed_distributions", lambda: dict(installed))


def test_actual_reviewed_runtime_matches_lock_in_fresh_interpreter():
    """Independently verify live distributions without the unit-test shim."""
    script = (
        "from evaluation.segmentation.qualification import current_local_identity; "
        "record = current_local_identity()['environment']; "
        "assert record['lock_sha256']; "
        "assert record['installed_distributions_sha256']"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(REPOSITORY / "src"), str(REPOSITORY)))
    run = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY, env=env, text=True, capture_output=True,
        timeout=45, check=False,
    )
    assert run.returncode == 0, run.stderr[-1200:]


TARGETS = {
    "minimum_holdout_n": 1,
    "minimum_holdout_writers": 1,
    "minimum_nonempty_line_n": 1,
    "minimum_nonempty_word_n": 1,
    "min_line_nonempty_macro_f1": 0.01,
    "min_word_nonempty_macro_f1": 0.01,
    "min_line_coverage": 1.0,
    "min_word_coverage": 1.0,
    "min_nonempty_line_coverage": 1.0,
    "min_nonempty_word_coverage": 1.0,
    "minimum_empty_line_n": 1,
    "minimum_empty_word_n": 1,
    "minimum_available_empty_line_n": 1,
    "minimum_available_empty_word_n": 1,
    "min_empty_line_coverage": 1.0,
    "min_empty_word_coverage": 1.0,
    "max_empty_line_false_positive_pages": 0,
    "max_empty_word_false_positive_pages": 0,
    "max_false_zero_words": 0,
}


def _fixtures(tmp_path, holdout_n=2, *, blank_last=True, empty_count=1):
    root = tmp_path / "images"
    root.mkdir(exist_ok=True)
    manifests = {}
    for split, count in (("development", 1), ("validation", 1), ("holdout", holdout_n)):
        rows = []
        for i in range(count):
            is_empty = split == "holdout" and blank_last and i >= count - empty_count
            # Different empty captures must have distinct exact encoded bytes.
            background = 245 + (i % 9) if is_empty else 251
            image = np.full((140, 340, 3), background, np.uint8)
            if not is_empty:
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
                "lines": [] if is_empty else [[10, 45, 160, 45]],
                "words": [] if is_empty else [[10, 45, 160, 45]],
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
    _reapprove_policy_for_validation_test(path)


def _fake_results(manifests, *, drop=0, refuse_last=False):
    hold = json.loads(manifests["holdout"].read_text())
    rows = []
    for i, item in enumerate(hold["specimens"]):
        box = Box(10, 45, 160, 45)
        reference_line = [box] if item["lines"] else []
        reference_word = [box] if item["words"] else []
        scored_line = benchmark.match(reference_line, reference_line)
        scored_word = benchmark.match(reference_word, reference_word)
        rejected = refuse_last and i == len(hold["specimens"]) - 1
        rows.append({"specimen_id": item["specimen_id"], "split": "holdout",
                     "data_origin": "SYNTHETIC_FIXTURE",
                     "paper": item["paper"], "status": "REJECTED" if rejected else "MEASURED",
                     "line_reference_n": len(reference_line),
                     "word_reference_n": len(reference_word),
                     "lines": None if rejected else scored_line,
                     "words": None if rejected else scored_word,
                     "false_zero_words": None if rejected else False})
    return {"version": 2, "profile": "qualified-v2", "split": "holdout",
            "data_origin": "SYNTHETIC_FIXTURE",
            "manifest_sha256": hashlib.sha256(manifests["holdout"].read_bytes()).hexdigest(),
            # Deliberately false aggregate: qualification must compute from the rows.
            "summary": {"data_origin": "SYNTHETIC_FIXTURE",
                        "overall": {"data_origin": "SYNTHETIC_FIXTURE",
                                    "count": 999999, "lines": {"macro_f1": 1}}},
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
    assert receipt["specimen_count"] == 2  # Not the 999999 supplied summary.
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"
    assert receipt["data_origin"] == "SYNTHETIC_FIXTURE"
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
    assert not receipt["engineering_gates"]["min_empty_word_coverage"]


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
    "qualification_sha256", "lock_verifier_sha256",
])
def test_code_and_processing_identity_are_checked_against_checkout(key, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    p = json.loads(policy.read_text())
    p[key] = "0" * len(p[key])
    policy.write_text(json.dumps(p))
    _reapprove_policy_for_validation_test(policy)
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
    _reapprove_policy_for_validation_test(policy)
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
             "data_origin": "SYNTHETIC_FIXTURE",
             "public_qualification": "NOT_AUTHORIZED",
             "decision": "ENGINEERING_PASS", "specimen_count": 1,
             "specimen_id": secret, "image_path": secret,
             "manifest_digest": secret, "secret_data": {"name": secret}}
    output = public_safe_receipt(entry)
    assert secret not in json.dumps(output)
    assert "manifest_digest" not in output
    assert output["specimen_count"] is None
    assert output["blank_evidence_scope"] == "SYNTHETIC_FIXTURE_ORACLE_ONLY"
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
    assert receipt["specimen_count"] == 2
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
    assert result["data_origin"] == "SYNTHETIC_FIXTURE"
    assert result["summary"]["overall"]["data_origin"] == "SYNTHETIC_FIXTURE"
    assert all(row["data_origin"] == "SYNTHETIC_FIXTURE" for row in result["results"])
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
    _reapprove_policy_for_validation_test(policy)
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
    _reapprove_policy_for_validation_test(policy)
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
    _reapprove_policy_for_validation_test(policy)
    with pytest.raises(ValueError, match="nonfinite JSON"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_false_positive_line_and_word_on_every_empty_page_block_qualification(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests)
    blank = fake["results"][-1]
    candidate = Box(10, 40, 65, 20)
    blank["lines"] = benchmark.match([], [candidate])
    blank["words"] = benchmark.match([], [candidate])
    # Both nonempty F1 scores are perfect, but both empty false-positive gates fail.
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert receipt["nonempty_line_f1"] == 1.0
    assert receipt["nonempty_word_f1"] == 1.0
    assert not receipt["engineering_gates"]["max_empty_line_false_positive_pages"]
    assert not receipt["engineering_gates"]["max_empty_word_false_positive_pages"]


def test_abstaining_from_empty_pages_is_not_a_false_positive_but_loses_coverage(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests, refuse_last=True)
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert receipt["engineering_gates"]["max_empty_line_false_positive_pages"]
    assert receipt["engineering_gates"]["max_empty_word_false_positive_pages"]
    assert not receipt["engineering_gates"]["min_empty_line_coverage"]
    assert not receipt["engineering_gates"]["min_empty_word_coverage"]


def test_no_empty_annotation_cannot_pass_required_blank_evidence(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path, blank_last=False)
    fake = _fake_results(manifests)
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert not receipt["engineering_gates"]["minimum_empty_line_n"]
    assert not receipt["engineering_gates"]["minimum_empty_word_n"]
    assert not receipt["engineering_gates"]["min_empty_line_coverage"]


def test_correctly_empty_and_written_samples_pass_the_predeclared_engineering_gates(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests)
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_PASS"
    assert all(receipt["engineering_gates"].values())
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"


def test_blank_annotation_is_not_inferred_from_unruled_paper_field():
    from evaluation.segmentation.benchmark import match, summarize

    box = Box(1, 1, 20, 8)
    row = {"specimen_id": "synthetic-plain-paper", "paper": "blank",
           "split": "synthetic", "data_origin": "SYNTHETIC_FIXTURE", "status": "MEASURED",
           "line_reference_n": 1, "word_reference_n": 1,
           "lines": match([box], [box]), "words": match([box], [box]),
           "false_zero_words": False}
    stats = summarize([row])["overall"]
    assert stats["lines"]["empty_eligible_n"] == 0
    assert stats["lines"]["nonempty_eligible_n"] == 1


def test_runtime_environment_is_bound_to_the_frozen_processing_identity(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    identity = current_local_identity()
    assert identity["environment"]["lock_sha256"]
    assert identity["environment"]["installed_distributions_sha256"]
    assert identity["environment"]["python_target"] in ("3.10", "3.11", "3.12")
    assert identity["environment"]["numpy_module_version"]
    assert identity["environment"]["opencv_module_version"]
    frozen = json.loads(policy.read_text())
    assert frozen["environment"] == identity["environment"]
    assert predeclared_holdout_gate_v2(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy,
    )["identity"]["environment"] == identity["environment"]


@pytest.mark.parametrize("key", [
    "python_version", "numpy_module_version", "opencv_module_version",
    "lock_sha256", "manifest_sha256", "installed_distributions_sha256",
])
def test_frozen_environment_identity_mutations_are_rejected(key, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    p = json.loads(policy.read_text())
    p["environment"][key] = "tampered"
    policy.write_text(json.dumps(p))
    _reapprove_policy_for_validation_test(policy)
    with pytest.raises(ValueError, match="identity mismatch"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_replaced_installed_numpy_version_is_refused(monkeypatch, tmp_path):
    from tools import verify_ci_lock as locks

    manifests, policy, _ = _fixtures(tmp_path)
    original = locks.installed_distributions
    def altered():
        value = original()
        value["numpy"] = "0.0.0"
        return value
    monkeypatch.setattr(locks, "installed_distributions", altered)
    with pytest.raises(ValueError, match="installed environment differs"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_unsupported_python_target_or_platform_refused(monkeypatch, tmp_path):
    from tools import verify_ci_lock as locks

    manifests, policy, _ = _fixtures(tmp_path)
    monkeypatch.setattr(locks, "running_target", lambda: ("3.13", "Linux", "x86_64"))
    with pytest.raises(ValueError, match="no reviewed qualification dependency"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_modified_lock_to_manifest_mapping_is_refused(monkeypatch, tmp_path):
    from tools import verify_ci_lock as locks

    manifests, policy, _ = _fixtures(tmp_path)
    original = locks.read_lock
    def altered(path):
        return {**original(path), "numpy": "999.0"}
    monkeypatch.setattr(locks, "read_lock", altered)
    with pytest.raises(ValueError, match="reviewed dependency versions"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_lock_verifier_source_hash_is_frozen_and_pinned(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    expected = hashlib.sha256(
        (REPOSITORY / "tools" / "verify_ci_lock.py").read_bytes()
    ).hexdigest()
    identity = current_local_identity()
    assert identity["lock_verifier_sha256"] == expected
    assert json.loads(policy.read_text())["lock_verifier_sha256"] == expected
    assert predeclared_holdout_gate_v2(
        manifests["development"], manifests["validation"], manifests["holdout"], policy
    )["identity"]["lock_verifier_sha256"] == expected


@pytest.mark.parametrize("modified_file", [
    "tools/verify_ci_lock.py",
    "src/princess_app/application/intake.py",
    "src/princess_contracts/runtime.py",
    "evaluation/segmentation/benchmark.py",
    "requirements/ci-py310.lock",
    "requirements/ci-py311.txt",
    "requirements/ci-targets.json",
])
def test_dirty_dependency_verifier_or_reviewed_snapshot_refuses_qualification(
    monkeypatch, modified_file,
):
    # No tracked files are modified; simulate Git's actual dirty signal while
    # also checking that the pathspec includes the modified file.
    import evaluation.segmentation.qualification as qualification

    real_run = qualification.subprocess.run
    observed = []
    def mocked_run(command, **kwargs):
        if command[:3] == ["git", "status", "--porcelain"]:
            paths = command[command.index("--") + 1:]
            assert any(
                modified_file == path or modified_file.startswith(path.rstrip("/") + "/")
                for path in paths
            ), "integrity pathspec does not cover trusted dependency input"
            observed.append(modified_file)
            return subprocess.CompletedProcess(
                command, 0, stdout=f" M {modified_file}\n", stderr=""
            )
        return real_run(command, **kwargs)

    monkeypatch.setattr(qualification.subprocess, "run", mocked_run)
    with pytest.raises(ValueError, match="unreviewed evaluation changes"):
        current_local_identity()
    assert observed == [modified_file]


def test_foreign_imported_lock_verifier_refused(monkeypatch):
    from tools import verify_ci_lock as locks

    unrelated_file = REPOSITORY / "tests" / "test_ci_lock.py"
    assert unrelated_file.is_file()
    monkeypatch.setattr(locks, "__file__", str(unrelated_file))
    with pytest.raises(ValueError, match="unreviewed imported evaluation module|lock verifier module origin"):
        current_local_identity()


@pytest.mark.parametrize("target", ("min_empty_line_coverage", "min_empty_word_coverage"))
@pytest.mark.parametrize("value", (0, 0.0, -0.1, None, float("nan")))
def test_zero_or_invalid_blank_coverage_policy_is_refused_before_scoring(
    target, value, tmp_path,
):
    manifests, policy, root = _fixtures(tmp_path)
    configuration = json.loads(policy.read_text())
    configuration["thresholds"][target] = value
    policy.write_text(json.dumps(configuration))
    _reapprove_policy_for_validation_test(policy)
    # The strict JSON decoder rejects NaN before threshold validation.
    expected_error = "nonfinite JSON" if value != value else "invalid frozen fraction"
    with pytest.raises(ValueError, match=expected_error):
        run_frozen_synthetic_qualification(
            manifests["development"], manifests["validation"], manifests["holdout"],
            policy, root,
        )


@pytest.mark.parametrize(
    "target", ("minimum_available_empty_line_n", "minimum_available_empty_word_n")
)
def test_zero_available_empty_minimum_is_refused(target, tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    configuration = json.loads(policy.read_text())
    configuration["thresholds"][target] = 0
    policy.write_text(json.dumps(configuration))
    _reapprove_policy_for_validation_test(policy)
    with pytest.raises(ValueError, match="invalid frozen count"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"], manifests["holdout"], policy
        )


def test_available_blank_minimum_blocks_abstentions_even_with_positive_coverage(
    monkeypatch, tmp_path,
):
    # One nonempty and two genuinely empty annotated images. The detector
    # measures only one blank (50% blank coverage) but the reviewed policy
    # requires two available blank measurements in each family.
    manifests, policy, root = _fixtures(tmp_path, holdout_n=3, empty_count=2)
    thresholds = {
        **TARGETS,
        "min_line_coverage": 0.6,
        "min_word_coverage": 0.6,
        "min_empty_line_coverage": 0.5,
        "min_empty_word_coverage": 0.5,
        "minimum_available_empty_line_n": 2,
        "minimum_available_empty_word_n": 2,
    }
    _freeze_policy(manifests, policy, thresholds=thresholds)
    fake = _fake_results(manifests, refuse_last=True)
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"], manifests["holdout"],
        policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert receipt["engineering_gates"]["min_empty_line_coverage"]
    assert receipt["engineering_gates"]["min_empty_word_coverage"]
    assert not receipt["engineering_gates"]["minimum_available_empty_line_n"]
    assert not receipt["engineering_gates"]["minimum_available_empty_word_n"]
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"


def test_production_policy_digest_is_required_before_reading_holdout(tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    args = (manifests["development"], manifests["validation"], manifests["holdout"], policy)
    with pytest.raises(TypeError, match="expected_policy_sha256"):
        _production_predeclared_holdout_gate_v2(*args)
    with pytest.raises(TypeError, match="expected_policy_sha256"):
        _production_run_frozen_synthetic_qualification(*args, root)
    for invalid in ("", "0" * 63, "f" * 63 + "G", None, 42):
        with pytest.raises(ValueError, match="independently approved"):
            _production_predeclared_holdout_gate_v2(*args, expected_policy_sha256=invalid)


def test_unapproved_policy_mutation_never_reaches_benchmark(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    approved_digest = _approval_file(policy).read_text()
    altered = json.loads(policy.read_text())
    altered["thresholds"]["min_word_nonempty_macro_f1"] = 0.0
    altered["thresholds"]["minimum_holdout_n"] = 1
    altered["thresholds"]["max_false_zero_words"] = 100
    policy.write_text(json.dumps(altered))
    called = []
    monkeypatch.setattr(benchmark, "run_manifest", lambda *a, **k: called.append("run"))
    with pytest.raises(ValueError, match="independently approved policy digest mismatch"):
        _production_run_frozen_synthetic_qualification(
            manifests["development"], manifests["validation"], manifests["holdout"],
            policy, root, expected_policy_sha256=approved_digest,
        )
    assert not called


def test_reapproved_bytes_are_not_proof_of_prior_independent_authorization(tmp_path):
    manifests, policy, _ = _fixtures(tmp_path)
    digest = _approval_file(policy).read_text()
    assert digest == hashlib.sha256(policy.read_bytes()).hexdigest()
    altered = json.loads(policy.read_text())
    altered["thresholds"]["min_line_nonempty_macro_f1"] = 0.25
    policy.write_text(json.dumps(altered))
    # Freshly computing the same new hash is mathematically possible. An operator
    # must obtain and verify a prior independent approval record outside this API.
    assert hashlib.sha256(policy.read_bytes()).hexdigest() != digest
    with pytest.raises(ValueError, match="independently approved policy digest mismatch"):
        _production_predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"], manifests["holdout"],
            policy, expected_policy_sha256=digest,
        )


@pytest.mark.parametrize("malformed", ("row_missing", "row_real", "top_missing", "top_real"))
def test_synthetic_qualification_rejects_lost_or_forged_data_origin(monkeypatch, tmp_path, malformed):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests)
    if malformed.startswith("row"):
        target = fake["results"][0]
    else:
        target = fake
    if malformed.endswith("missing"):
        target.pop("data_origin")
    else:
        target["data_origin"] = "REAL_SOURCE_DECLARED"
    monkeypatch.setattr(benchmark, "run_manifest", lambda *args, **kwargs: fake)
    with pytest.raises(ValueError, match="metadata mismatch|benchmark identity"):
        run_frozen_synthetic_qualification(
            manifests["development"], manifests["validation"], manifests["holdout"], policy, root,
        )


def test_mixed_or_unknown_benchmark_provenance_never_aggregates_as_real():
    from evaluation.segmentation.benchmark import summarize

    base = {"specimen_id": "a", "split": "holdout", "paper": "blank",
            "data_origin": "SYNTHETIC_FIXTURE", "status": "REJECTED",
            "line_reference_n": 0, "word_reference_n": 0,
            "lines": None, "words": None, "false_zero_words": None}
    for bad in ({**base, "specimen_id": "b", "data_origin": "REAL_SOURCE_DECLARED"},
                {**base, "specimen_id": "b", "data_origin": None},
                {k: v for k, v in base.items() if k != "data_origin"}):
        with pytest.raises(ValueError, match="unknown or mixed benchmark data origin"):
            summarize([base, bad])
    summary = summarize([base])
    assert summary["data_origin"] == "SYNTHETIC_FIXTURE"
    assert summary["overall"]["data_origin"] == "SYNTHETIC_FIXTURE"
    assert all(r["data_origin"] == "SYNTHETIC_FIXTURE" for r in summary["conditions"].values())


def test_synthetic_manifest_cannot_use_real_data_admission(tmp_path):
    manifests, _, image_root = _fixtures(tmp_path)
    for split in ("development", "validation", "holdout"):
        with pytest.raises(ValueError, match="synthetic inputs cannot use"):
            benchmark.run_manifest(
                manifests[split], image_root, allow_real=True, synthetic_split=True,
            )


@pytest.mark.parametrize("module_name", (
    "evaluation.segmentation.benchmark",
    "princess_graphology.context",
    "princess_app.application.intake",
    "princess_contracts.runtime",
))
def test_shadowed_project_module_refused(monkeypatch, tmp_path, module_name):
    import importlib
    import importlib.util
    import sys
    import types

    importlib.import_module(module_name)
    shadow = tmp_path / "shadowed.py"
    shadow.write_text("# unreviewed source\n")
    injected = types.ModuleType(module_name)
    injected.__file__ = str(shadow)
    injected.__spec__ = importlib.util.spec_from_file_location(module_name, shadow)
    monkeypatch.setitem(sys.modules, module_name, injected)
    with pytest.raises(ValueError, match="unreviewed imported evaluation module"):
        _verify_loaded_evaluation_modules()


@pytest.mark.parametrize("module_name", ("numpy", "cv2"))
def test_shadowed_numerical_module_with_matching_version_refused(monkeypatch, tmp_path, module_name):
    import importlib
    import importlib.util
    import sys
    import types

    original = importlib.import_module(module_name)
    shadow = tmp_path / (module_name + ".py")
    shadow.write_text("__version__ = " + repr(original.__version__) + "\n")
    injected = types.ModuleType(module_name)
    injected.__file__ = str(shadow)
    injected.__version__ = original.__version__
    injected.__spec__ = importlib.util.spec_from_file_location(module_name, shadow)
    monkeypatch.setitem(sys.modules, module_name, injected)
    with pytest.raises(ValueError, match="unreviewed imported evaluation module"):
        _verify_loaded_evaluation_modules()


def test_shadow_numpy_cannot_pass_in_fresh_interpreter(tmp_path):
    shadow = tmp_path / "numpy"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("__version__ = '999.0'\n")
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(tmp_path)!r}); "
        "import numpy; "
        "from evaluation.segmentation.qualification import _verify_loaded_evaluation_modules; "
        "_verify_loaded_evaluation_modules()"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(REPOSITORY / "src"), str(REPOSITORY)))
    run = subprocess.run(
        [sys.executable, "-c", script], cwd=REPOSITORY,
        env=env, text=True, capture_output=True, timeout=45,
    )
    assert run.returncode != 0
    assert "unreviewed imported evaluation module" in run.stderr


def test_unreviewed_lazy_import_after_benchmark_is_refused(monkeypatch, tmp_path):
    import importlib.util
    import sys
    import types

    manifests, policy, image_root = _fixtures(tmp_path)
    original = _fake_results(manifests)
    shadow = tmp_path / "shadow_benchmark.py"
    shadow.write_text("# injected during execution\n")

    def runner(*args, **kwargs):
        injected = types.ModuleType("princess_graphology.shadowed_lazy")
        injected.__file__ = str(shadow)
        injected.__spec__ = importlib.util.spec_from_file_location(injected.__name__, shadow)
        sys.modules[injected.__name__] = injected
        return original

    monkeypatch.setattr(benchmark, "run_manifest", runner)
    try:
        with pytest.raises(ValueError, match="unreviewed imported evaluation module"):
            run_frozen_synthetic_qualification(
                manifests["development"], manifests["validation"],
                manifests["holdout"], policy, image_root,
            )
    finally:
        sys.modules.pop("princess_graphology.shadowed_lazy", None)


def test_isolated_launcher_refuses_unapproved_policy_and_hides_paths(tmp_path):
    manifests, policy, image_root = _fixtures(tmp_path)
    approval = tmp_path / "external-review.sha256"
    approval.write_text("0" * 64)
    launcher = REPOSITORY / "evaluation" / "segmentation" / "run_qualification.py"
    args = [
        "--development", str(manifests["development"]),
        "--validation", str(manifests["validation"]),
        "--holdout", str(manifests["holdout"]),
        "--policy", str(policy),
        "--approved-digest-file", str(approval),
        "--image-root", str(image_root),
    ]
    rejected = subprocess.run(
        [sys.executable, str(launcher), *args],
        cwd=REPOSITORY, text=True, capture_output=True, timeout=45,
    )
    assert rejected.returncode == 2
    assert "Isolation requires python -I -S -B" in rejected.stderr
    bootstrap = _externally_provisioned_test_bootstrap(tmp_path)
    result = subprocess.run(
        _bootstrap_args(bootstrap, *args),
        cwd=REPOSITORY, text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 2
    assert "[Q_POLICY]" in result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


def test_isolated_launcher_returns_only_redacted_synthetic_receipt(tmp_path):
    manifests, policy, image_root = _fixtures(tmp_path)
    approval = tmp_path / "prior-review.sha256"
    approval.write_text(_approval_file(policy).read_text())
    bootstrap = _externally_provisioned_test_bootstrap(tmp_path)
    result = subprocess.run(_bootstrap_args(
        bootstrap,
        "--development", str(manifests["development"]),
        "--validation", str(manifests["validation"]),
        "--holdout", str(manifests["holdout"]),
        "--policy", str(policy),
        "--approved-digest-file", str(approval),
        "--image-root", str(image_root),
    ), cwd=REPOSITORY, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    safe = json.loads(result.stdout)
    assert safe["mode"] == "synthetic"
    assert safe["data_origin"] == "SYNTHETIC_FIXTURE"
    assert safe["public_qualification"] == "NOT_AUTHORIZED"
    assert safe["specimen_count"] is None
    assert str(tmp_path) not in result.stdout


def test_holdout_manifest_is_not_reopened_after_preflight(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    target = manifests["holdout"].resolve()
    original_read = Path.read_bytes
    seen = []

    def observed_read(path):
        if path.resolve() == target:
            seen.append("read")
            if len(seen) > 1:
                raise AssertionError("holdout manifest reopened after validation")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", observed_read)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert len(seen) == 1
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"


def test_frozen_manifest_snapshot_survives_replacement_before_benchmark(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    original_runner = benchmark.run_manifest
    approved = manifests["holdout"].read_bytes()
    bad_pixels = cv2.imencode(".png", np.zeros((50, 50, 3), np.uint8))[1].tobytes()
    (root / "unapproved.png").write_bytes(bad_pixels)
    changed = json.loads(approved)
    changed["specimens"][0]["image_path"] = "unapproved.png"
    changed["specimens"][0]["sha256"] = hashlib.sha256(bad_pixels).hexdigest()
    observed = []
    decoder = cv2.imdecode

    def verified_decode(data, flags):
        raw = data.tobytes()
        observed.append(raw)
        assert raw != bad_pixels, "unapproved pixels were decoded"
        return decoder(data, flags)

    def swap_after_preflight(*args, **kwargs):
        manifests["holdout"].write_text(json.dumps(changed))
        assert kwargs["manifest_bytes"] == approved
        return original_runner(*args, **kwargs)

    monkeypatch.setattr(cv2, "imdecode", verified_decode)
    monkeypatch.setattr(benchmark, "run_manifest", swap_after_preflight)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"
    assert observed and bad_pixels not in observed


def test_verified_image_bytes_refuse_symlinks_and_swapped_digest(tmp_path):
    from evaluation.segmentation.benchmark import _read_verified_image

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"private pixels")
    (root / "link.png").symlink_to(outside)
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="specimen admission failed"):
        _read_verified_image(root, "link.png", digest)

    approved = root / "approved.png"
    approved.write_bytes(b"original reviewed bytes")
    digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    approved.write_bytes(b"replaced image")
    with pytest.raises(ValueError, match="image SHA256 mismatch"):
        _read_verified_image(root, "approved.png", digest)
    with pytest.raises(ValueError, match="invalid specimen image path"):
        _read_verified_image(root, "../secret.png", digest)


def test_wheel_record_tamper_cannot_override_reviewed_archive(monkeypatch, tmp_path):
    """A forged installed RECORD is not accepted as independent file evidence."""
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "repo"
    lock_dir = root / "requirements"
    lock_dir.mkdir(parents=True)
    site = tmp_path / "site"
    (site / "demo").mkdir(parents=True)
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    trusted = b"print('reviewed')\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", trusted)
        archive.writestr("demo-1.0.dist-info/WHEEL", SYNTHETIC_WHEEL_METADATA)
        archive.writestr("demo-1.0.dist-info/RECORD", b"")
    approved_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    target = f"{sys.version_info.major}{sys.version_info.minor}"
    (lock_dir / f"ci-py{target}.lock").write_text(
        "demo==1.0 --hash=sha256:" + approved_sha + "\n"
    )
    (site / "demo" / "__init__.py").write_bytes(trusted)
    (site / "demo-1.0.dist-info").mkdir()
    (site / "demo-1.0.dist-info" / "WHEEL").write_bytes(SYNTHETIC_WHEEL_METADATA)
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheelhouse)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)

    altered = b"print('attacker')\n"
    (site / "demo" / "__init__.py").write_bytes(altered)
    (site / "demo-1.0.dist-info").mkdir(exist_ok=True)
    (site / "demo-1.0.dist-info" / "RECORD").write_text(
        "demo/__init__.py,sha256:" + hashlib.sha256(altered).hexdigest()
    )
    with pytest.raises(ValueError, match="differs from authenticated locked wheel"):
        trust.preflight_reviewed_environment(root)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", altered)
    trust._trusted_files.cache_clear()
    with pytest.raises(ValueError, match="wheel archive differs"):
        trust.preflight_reviewed_environment(root)


def test_forged_timestamp_matching_bytecode_is_rejected(tmp_path):
    import importlib.util
    import marshal
    import types
    from evaluation.segmentation.runtime_integrity import _check_project_bytecode

    source = tmp_path / "reviewed.py"
    source.write_bytes(b"answer = 42\n")
    cached = Path(importlib.util.cache_from_source(str(source)))
    cached.parent.mkdir()
    magic = importlib.util.MAGIC_NUMBER + b"\x00" * 12
    good = marshal.dumps(compile(source.read_bytes(), str(source), "exec", dont_inherit=True))
    fake = marshal.dumps(compile(b"answer = 0\n", str(source), "exec"))
    module = types.SimpleNamespace(__cached__=str(cached))
    cached.write_bytes(magic + good)
    _check_project_bytecode(module, source)
    cached.write_bytes(magic + fake)
    with pytest.raises(ValueError, match="unverified cached project bytecode"):
        _check_project_bytecode(module, source)


@pytest.mark.parametrize("name", ("hmac", "lazy_loader", "imageio"))
def test_all_module_import_origins_reject_unreviewed_shadow(monkeypatch, tmp_path, name):
    import importlib.util
    import types
    from evaluation.segmentation.runtime_integrity import verify_loaded_module_closure

    attacker = tmp_path / f"{name}.py"
    attacker.write_text("FAKE = True\n")
    injected = types.ModuleType(name)
    injected.__file__ = str(attacker)
    injected.__spec__ = importlib.util.spec_from_file_location(name, attacker)
    monkeypatch.setitem(sys.modules, name, injected)
    with pytest.raises(ValueError, match="unreviewed imported evaluation module"):
        verify_loaded_module_closure(REPOSITORY)


def test_preflight_refuses_forged_installed_bytecode_before_import(monkeypatch, tmp_path):
    import importlib.util
    import marshal
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "repo"
    (root / "requirements").mkdir(parents=True)
    site = tmp_path / "site"
    (site / "demo").mkdir(parents=True)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    good = b"answer = 42\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", good)
        archive.writestr("demo-1.0.dist-info/WHEEL", SYNTHETIC_WHEEL_METADATA)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text("demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest())
    source = site / "demo" / "__init__.py"
    source.write_bytes(good)
    (site / "demo-1.0.dist-info").mkdir()
    (site / "demo-1.0.dist-info" / "WHEEL").write_bytes(SYNTHETIC_WHEEL_METADATA)
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir()
    header = importlib.util.MAGIC_NUMBER + b"\x00" * 12
    cache.write_bytes(header + marshal.dumps(compile(good, str(source), "exec", dont_inherit=True)))
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheelhouse)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)
    cache.write_bytes(header + marshal.dumps(compile(b"answer = 0\n", str(source), "exec")))
    with pytest.raises(ValueError, match="unreviewed installed bytecode cache"):
        trust.preflight_reviewed_environment(root)



def test_direct_staged_worker_from_normal_checkout_is_not_authorized(tmp_path):
    """Hidden worker selection must not bypass source-stage authentication."""
    manifests, policy, image_root = _fixtures(tmp_path)
    launcher = REPOSITORY / "evaluation" / "segmentation" / "run_qualification.py"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(launcher), "--_staged",
         "--development", str(manifests["development"]),
         "--validation", str(manifests["validation"]),
         "--holdout", str(manifests["holdout"]),
         "--policy", str(policy),
         "--approved-digest-file", str(_approval_file(policy)),
         "--image-root", str(image_root)],
        cwd=REPOSITORY, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 2
    assert "Frozen synthetic evaluation rejected" in result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


def test_direct_staged_worker_rejects_modified_checkout_before_import(tmp_path):
    """Exercise a truly dirty detached worktree without touching repository files."""
    manifests, policy, image_root = _fixtures(tmp_path)
    checkout = tmp_path / "attacker-worktree"
    marker = tmp_path / "ATTACK_EXECUTED"
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "worktree", "add",
         "--detach", str(checkout), "HEAD"],
        cwd=REPOSITORY, capture_output=True, text=True, check=True, timeout=45,
    )
    try:
        qualification = checkout / "evaluation" / "segmentation" / "qualification.py"
        original_source = qualification.read_text()
        # Append rather than prepend: imports before __future__ annotations
        # would cause SyntaxError and let a vulnerable worker appear safe.
        qualification.write_text(
            original_source + "\nfrom pathlib import Path\nPath(" +
            repr(str(marker)) + ").write_text('bad import executed')\n"
        )
        launcher = checkout / "evaluation" / "segmentation" / "run_qualification.py"
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(launcher), "--_staged",
             "--development", str(manifests["development"]),
             "--validation", str(manifests["validation"]),
             "--holdout", str(manifests["holdout"]),
             "--policy", str(policy),
             "--approved-digest-file", str(_approval_file(policy)),
             "--image-root", str(image_root)],
            cwd=checkout, capture_output=True, text=True, timeout=45,
        )
        assert result.returncode == 2
        assert not marker.exists(), "unapproved source ran before stage verification"
        assert "Frozen synthetic evaluation rejected" in result.stderr

        # Even ignored untracked source is not permitted in a supposedly
        # authenticated stage: ordinary git status would hide this payload.
        qualification.write_text(original_source)
        ignored = checkout / "dist" / "unreviewed.py"
        ignored.parent.mkdir(parents=True)
        ignored.write_text("print('unreviewed')")
        second = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(launcher), "--_staged",
             "--development", str(manifests["development"]),
             "--validation", str(manifests["validation"]),
             "--holdout", str(manifests["holdout"]),
             "--policy", str(policy),
             "--approved-digest-file", str(_approval_file(policy)),
             "--image-root", str(image_root)],
            cwd=checkout, capture_output=True, text=True, timeout=45,
        )
        assert second.returncode == 2
        assert "Frozen synthetic evaluation rejected" in second.stderr
    finally:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null",
             "worktree", "remove", "--force", str(checkout)],
            cwd=REPOSITORY, capture_output=True, check=False, timeout=45,
        )


def test_isolated_launcher_binds_relative_inputs_to_invocation_directory(tmp_path):
    manifests, policy, image_root = _fixtures(tmp_path)
    bootstrap = _externally_provisioned_test_bootstrap(tmp_path)
    result = subprocess.run(
        _bootstrap_args(
            bootstrap,
            "--development", "development.json",
            "--validation", "validation.json",
            "--holdout", "holdout.json",
            "--policy", "policy.json",
            "--approved-digest-file", "policy.json.approved.sha256",
            "--image-root", "images",
        ),
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    safe = json.loads(result.stdout)
    assert safe["mode"] == "synthetic"
    assert safe["data_origin"] == "SYNTHETIC_FIXTURE"
    assert safe["public_qualification"] == "NOT_AUTHORIZED"
    assert safe["decision"] in ("ENGINEERING_PASS", "ENGINEERING_FAIL")
    assert str(tmp_path) not in result.stdout


def test_masked_or_deleted_project_cache_never_proves_trusted_execution(tmp_path):
    import importlib.util
    import marshal
    import types
    from evaluation.segmentation.runtime_integrity import _check_project_bytecode

    source = tmp_path / "reviewed.py"
    source.write_bytes(b"value = 42\n")
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir(parents=True)
    altered = marshal.dumps(compile(
        b"value = 'tampered'\n", str(source), "exec", dont_inherit=True,
    ))
    cache.write_bytes(importlib.util.MAGIC_NUMBER + b"\x00" * 12 + altered)
    with pytest.raises(ValueError, match="unverified cached project bytecode"):
        _check_project_bytecode(types.SimpleNamespace(__cached__=None), source)
    cache.unlink()
    if not sys.flags.dont_write_bytecode:
        with pytest.raises(ValueError, match="unverified cached project bytecode"):
            _check_project_bytecode(types.SimpleNamespace(__cached__=None), source)


def test_versioned_native_wheel_libraries_and_relocated_files_are_authenticated(monkeypatch, tmp_path):
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "repo"
    (root / "requirements").mkdir(parents=True)
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    site = tmp_path / "site"
    site.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    payloads = {
        "demo/__init__.py": b"ANSWER = 42\n",
        "demo.libs/libexample.so.5": b"reviewed-native-binary",
        "demo.libs/libexample.so.5.0.0": b"reviewed-versioned-binary",
        "demo-1.0.data/purelib/relocated.py": b"FLAG = 1\n",
        "demo-1.0.dist-info/WHEEL": SYNTHETIC_WHEEL_METADATA,
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in payloads.items():
            archive.writestr(name, content)
    for name, content in payloads.items():
        parts = name.split("/")
        target = site.joinpath(*(parts[2:] if parts[0].endswith(".data") else parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text(
        "demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheelhouse)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)
    for changed in ("libexample.so.5", "libexample.so.5.0.0"):
        target = site / "demo.libs" / changed
        original = target.read_bytes()
        target.write_bytes(b"modified-native-code")
        with pytest.raises(ValueError, match="differs from authenticated locked wheel"):
            trust.preflight_reviewed_environment(root)
        target.write_bytes(original)
    (site / "demo.libs" / "unreviewed.so.5").write_bytes(b"extra-native-code")
    with pytest.raises(ValueError, match="unreviewed installed native library"):
        trust.preflight_reviewed_environment(root)


def test_unowned_cython_namespace_module_is_not_whitelisted(monkeypatch):
    import types
    from evaluation.segmentation.runtime_integrity import verify_loaded_module_closure

    injected = types.ModuleType("cython.fake_unowned")
    monkeypatch.setitem(sys.modules, "cython.fake_unowned", injected)
    with pytest.raises(ValueError, match="unreviewed imported evaluation module"):
        verify_loaded_module_closure(REPOSITORY)



def test_real_python_virtualenv_site_root_resolves_under_isolated_minus_s(tmp_path):
    """Exercise the documented -I -S -B invocation on an actual local venv."""
    import venv

    env_root = tmp_path / "qualified-venv"
    venv.EnvBuilder(with_pip=False).create(env_root)
    executable = env_root / "bin" / "python"
    assert executable.is_file()
    script = (
        "import sys; from pathlib import Path; "
        f"sys.path.append({str(REPOSITORY)!r}); "
        "from evaluation.segmentation.runtime_integrity import _site_roots; "
        "p=_site_roots(); "
        f"prefix=Path({str(env_root)!r}); "
        "v=f'python{sys.version_info.major}.{sys.version_info.minor}'; "
        "pure=prefix/'lib'/v/'site-packages'; "
        "plat=prefix/sys.platlibdir/v/'site-packages'; "
        "assert p==(pure.resolve(strict=True),plat.resolve(strict=True)),(p,pure,plat)"
    )
    result = subprocess.run(
        [str(executable), "-I", "-S", "-B", "-c", script],
        cwd=tmp_path, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr


def test_uniform_light_synthetic_blank_is_scored_without_annotation_leakage(tmp_path):
    """Only independent uniform-light fixture evidence makes empty measured."""
    image = np.full((140, 340, 3), 245, dtype=np.uint8)
    base = {
        "specimen_id": "synthetic-uniform-white",
        "writer_group": "synthetic-writer",
        "capture_group": "synthetic-capture",
        "image_path": "fixture.png",
        "sha256": "a" * 64,
        "paper": "blank",
        "lines": [],
        "words": [],
    }
    clean = benchmark.evaluate(
        image, base, split="holdout", profile="qualified-v2",
        synthetic_fixture=True, annotation_frame="original_image",
    )
    assert clean["status"] == "MEASURED"
    assert clean["qualification"]["lines"] == "qualified_empty"
    assert clean["qualification"]["words"] == "qualified_empty"
    assert clean["qualification"]["empty_evidence"] == "uniform_light_synthetic_fixture"
    assert clean["lines"]["detected_n"] == clean["words"]["detected_n"] == 0
    assert clean["lines"]["f1"] == clean["words"]["f1"] == 1.0

    # The blank decision never consults the reference annotation: a falsely
    # annotated nonempty fixture must score FNs, not magically pass.
    not_empty_reference = {
        **base,
        "lines": [[10, 45, 100, 15]],
        "words": [[10, 45, 100, 15]],
    }
    missed = benchmark.evaluate(
        image, not_empty_reference, split="holdout", profile="qualified-v2",
        synthetic_fixture=True, annotation_frame="original_image",
    )
    assert missed["status"] == "MEASURED"
    assert missed["qualification"]["empty_evidence"] == "uniform_light_synthetic_fixture"
    assert missed["lines"]["fn"] == missed["words"]["fn"] == 1
    assert missed["false_zero_words"] is True

    # Synthetic or real-looking direct programmatic calls cannot gain the
    # special authority merely from a white page or annotated-empty labels.
    no_fixture = benchmark.evaluate(image, base, split="synthetic", profile="qualified-v2")
    assert no_fixture["status"] != "MEASURED"
    assert no_fixture.get("qualification", {}).get("empty_evidence") is None

    ambiguous = image.copy()
    ambiguous[25, 25, :] = 30
    noisy = benchmark.evaluate(
        ambiguous, base, split="holdout", profile="qualified-v2",
        synthetic_fixture=True, annotation_frame="original_image",
    )
    assert noisy.get("qualification", {}).get("empty_evidence") is None


def test_actual_frozen_holdout_has_nonzero_available_uniform_blank_evidence(tmp_path):
    """P1 regression: the existing positive blank gates must be reachable."""
    manifests, _, image_root = _fixtures(tmp_path)
    actual = benchmark.run_manifest(
        manifests["holdout"], image_root,
        profile="qualified-v2", synthetic_split=True,
    )
    empty = [r for r in actual["results"]
             if r["line_reference_n"] == 0 and r["word_reference_n"] == 0]
    assert empty
    assert all(r["status"] == "MEASURED" for r in empty)
    assert all(r["qualification"]["empty_evidence"] == "uniform_light_synthetic_fixture"
               for r in empty)
    assert all(r["lines"]["detected_n"] == 0 and r["words"]["detected_n"] == 0
               for r in empty)
    overall = actual["summary"]["overall"]
    assert overall["lines"]["empty_available_n"] >= 1
    assert overall["words"]["empty_available_n"] >= 1
    assert overall["lines"]["empty_coverage"] > 0
    assert overall["words"]["empty_coverage"] > 0
    assert actual["data_origin"] == "SYNTHETIC_FIXTURE"
    assert "public_qualification" not in actual  # Direct benchmark is not a rights receipt.



@pytest.mark.parametrize("key", ("min_line_nonempty_macro_f1", "min_word_nonempty_macro_f1"))
@pytest.mark.parametrize("invalid", (0, 0.0, -0.01, None))
def test_frozen_nonempty_f1_floor_must_be_strictly_positive(tmp_path, key, invalid):
    manifests, policy, _ = _fixtures(tmp_path)
    record = json.loads(policy.read_text())
    record["thresholds"][key] = invalid
    policy.write_text(json.dumps(record))
    _reapprove_policy_for_validation_test(policy)
    with pytest.raises(ValueError, match="invalid frozen fraction"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_fully_available_but_zero_f1_does_not_pass_engineering_gate(monkeypatch, tmp_path):
    manifests, policy, root = _fixtures(tmp_path)
    fake = _fake_results(manifests)
    reference = Box(10, 45, 160, 45)
    mismatched = Box(230, 95, 50, 15)
    assert benchmark.match([reference], [mismatched])["f1"] == 0
    fake["results"][0]["lines"] = benchmark.match([reference], [mismatched])
    monkeypatch.setattr(benchmark, "run_manifest", lambda *args, **kwargs: fake)
    receipt = run_frozen_synthetic_qualification(
        manifests["development"], manifests["validation"],
        manifests["holdout"], policy, root,
    )
    assert receipt["decision"] == "ENGINEERING_FAIL"
    assert receipt["engineering_gates"]["min_line_coverage"]
    assert not receipt["engineering_gates"]["min_line_nonempty_macro_f1"]
    assert receipt["public_qualification"] == "NOT_AUTHORIZED"



def test_clean_but_unapproved_commit_cannot_import_modified_worker_code(tmp_path):
    """The approved policy's source SHA, not merely clean Git HEAD, owns execution."""
    manifests, policy, image_root = _fixtures(tmp_path)
    checkout = tmp_path / "unapproved-committed-worktree"
    marker = tmp_path / "UNAPPROVED_MODULE_EXECUTED"
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "worktree", "add",
         "--detach", str(checkout), "HEAD"],
        cwd=REPOSITORY, capture_output=True, text=True, check=True, timeout=45,
    )
    try:
        module = checkout / "evaluation" / "segmentation" / "runtime_integrity.py"
        module.write_text(
            module.read_text() + "\nfrom pathlib import Path\nPath(" +
            repr(str(marker)) + ").write_text('unreviewed module executed')\n"
        )
        subprocess.run(
            ["git", "-c", "user.name=synthetic-test",
             "-c", "user.email=synthetic-test@example.invalid",
             "-c", "core.hooksPath=/dev/null", "commit", "-am",
             "synthetic adversarial committed source change"],
            cwd=checkout, capture_output=True, text=True, check=True, timeout=45,
        )
        check = subprocess.run(
            ["git", "status", "--porcelain"], cwd=checkout,
            text=True, capture_output=True, check=True, timeout=20,
        )
        assert check.stdout == "", "the attack must use a genuinely clean committed checkout"
        runner = checkout / "evaluation" / "segmentation" / "run_qualification.py"
        attempted = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(runner), "--_staged",
             "--development", str(manifests["development"]),
             "--validation", str(manifests["validation"]),
             "--holdout", str(manifests["holdout"]),
             "--policy", str(policy),
             "--approved-digest-file", str(_approval_file(policy)),
             "--image-root", str(image_root)],
            cwd=checkout, capture_output=True, text=True, timeout=45,
        )
        assert attempted.returncode == 2
        assert not marker.exists(), "unapproved committed source executed before approved revision check"
        assert "Frozen synthetic evaluation rejected" in attempted.stderr
    finally:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "worktree",
             "remove", "--force", str(checkout)],
            cwd=REPOSITORY, capture_output=True, check=False, timeout=45,
        )



def test_split_virtualenv_roots_are_separately_selected(monkeypatch, tmp_path):
    """Simulate a genuine lib/lib64 layout independent of this host platlibdir."""
    from evaluation.segmentation import runtime_integrity as trust

    venv_root = tmp_path / "reviewed-virtualenv"
    (venv_root / "bin").mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("home = /reviewed/python\n")
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    pure = venv_root / "lib" / version / "site-packages"
    plat = venv_root / "lib64" / version / "site-packages"
    pure.mkdir(parents=True)
    plat.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(venv_root / "bin" / "python"))
    monkeypatch.setattr(sys, "platlibdir", "lib64")
    assert trust._site_roots() == (pure.resolve(strict=True), plat.resolve(strict=True))


def test_reviewed_native_wheel_uses_platlib_not_purelib(monkeypatch, tmp_path):
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "source"
    (root / "requirements").mkdir(parents=True)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    pure = tmp_path / "purelib"
    plat = tmp_path / "platlib"
    pure.mkdir()
    plat.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    native_metadata = SYNTHETIC_WHEEL_METADATA.replace(
        b"Root-Is-Purelib: true", b"Root-Is-Purelib: false",
    )
    payloads = {
        "demo/__init__.py": b"import os\n",
        "demo.libs/libsample.so.5": b"reviewed-native-object",
        "demo-1.0.dist-info/WHEEL": native_metadata,
        "demo-1.0.data/purelib/relocated.py": b"RELOCATED = True\n",
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, raw in payloads.items():
            archive.writestr(name, raw)
    for name, raw in payloads.items():
        parts = name.split("/")
        dest = pure if parts[0].endswith(".data") else plat
        relative = parts[2:] if parts[0].endswith(".data") else parts
        target = dest.joinpath(*relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text(
        "demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(trust, "_site_roots", lambda: (pure, plat))
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheelhouse)
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)
    changed = plat / "demo.libs" / "libsample.so.5"
    changed.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs from authenticated locked wheel"):
        trust.preflight_reviewed_environment(root)


def test_external_bootstrap_never_executes_unapproved_launcher(tmp_path):
    """A clean, unapproved HEAD with executable injected launcher must not run."""
    manifests, policy, images = _fixtures(tmp_path)
    bootstrap = _externally_provisioned_test_bootstrap(tmp_path)
    marker = tmp_path / "UNAPPROVED_LAUNCHER_EXECUTED"
    alternate = tmp_path / "alternate-checked-out-revision"
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "worktree", "add",
         "--detach", str(alternate), "HEAD"],
        cwd=REPOSITORY, capture_output=True, check=True, timeout=45,
    )
    try:
        launcher = alternate / "evaluation" / "segmentation" / "run_qualification.py"
        source = launcher.read_text()
        anchor = "from __future__ import annotations\n"
        assert source.count(anchor) == 1
        injected = (
            "from pathlib import Path\nPath(" + repr(str(marker)) +
            ").write_text('unapproved launcher executed')\n"
        )
        launcher.write_text(source.replace(anchor, anchor + injected))
        subprocess.run(
            ["git", "-c", "user.name=synthetic-test",
             "-c", "user.email=synthetic-test@example.invalid",
             "-c", "core.hooksPath=/dev/null", "commit", "-am",
             "synthetic malicious launcher revision"],
            cwd=alternate, capture_output=True, check=True, timeout=45,
        )
        assert not subprocess.run(
            ["git", "status", "--porcelain"], cwd=alternate,
            capture_output=True, check=True, timeout=15,
        ).stdout.strip()
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(bootstrap),
             "--repository", str(alternate),
             "--development", str(manifests["development"]),
             "--validation", str(manifests["validation"]),
             "--holdout", str(manifests["holdout"]),
             "--policy", str(policy),
             "--approved-digest-file", str(_approval_file(policy)),
             "--image-root", str(images)],
            cwd=tmp_path, text=True, capture_output=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert not marker.exists(), "unapproved launcher executed"
        output = json.loads(result.stdout)
        assert output["public_qualification"] == "NOT_AUTHORIZED"
        assert output["data_origin"] == "SYNTHETIC_FIXTURE"
    finally:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "worktree",
             "remove", "--force", str(alternate)],
            cwd=REPOSITORY, capture_output=True, check=False, timeout=45,
        )



@pytest.mark.parametrize(
    "key",
    ("min_line_coverage", "min_word_coverage",
     "min_nonempty_line_coverage", "min_nonempty_word_coverage"),
)
@pytest.mark.parametrize("invalid", (0, 0.0, -0.01, None))
def test_frozen_nonempty_and_overall_coverage_cannot_be_zero(tmp_path, key, invalid):
    manifests, policy, _ = _fixtures(tmp_path)
    reviewed = json.loads(policy.read_text())
    reviewed["thresholds"][key] = invalid
    policy.write_text(json.dumps(reviewed))
    _reapprove_policy_for_validation_test(policy)
    with pytest.raises(ValueError, match="invalid frozen fraction"):
        predeclared_holdout_gate_v2(
            manifests["development"], manifests["validation"],
            manifests["holdout"], policy,
        )


def test_alpha_composited_synthetic_blanks_use_visible_pixels_not_raw_alpha():
    record = {
        "specimen_id": "synthetic-alpha-blank",
        "writer_group": "synthetic-alpha-writer",
        "capture_group": "synthetic-alpha-capture",
        "image_path": "fixture.png",
        "sha256": "a" * 64,
        "paper": "blank",
        "lines": [], "words": [],
    }
    image = np.zeros((120, 320, 4), dtype=np.uint8)
    image[:, :, :3] = 2  # Opaque black would NOT be qualified empty.
    image[:, :, 3] = 0  # Fully transparent: composites to solid white.
    result = benchmark.evaluate(
        image, record, split="holdout", profile="qualified-v2",
        synthetic_fixture=True, annotation_frame="original_image",
    )
    assert result["status"] == "MEASURED"
    assert result["qualification"]["empty_evidence"] == "uniform_light_synthetic_fixture"
    assert result["lines"]["detected_n"] == result["words"]["detected_n"] == 0

    opaque = image.copy()
    opaque[30:35, 20:40, 3] = 255
    changed = benchmark.evaluate(
        opaque, record, split="holdout", profile="qualified-v2",
        synthetic_fixture=True, annotation_frame="original_image",
    )
    assert changed.get("qualification", {}).get("empty_evidence") is None

    # The production/non-fixture path cannot borrow synthetic oracle authority.
    ordinary = benchmark.evaluate(image, record, split="synthetic", profile="qualified-v2")
    assert ordinary.get("qualification", {}).get("empty_evidence") is None


def test_installed_wheel_cache_must_match_hash_reviewed_source(monkeypatch, tmp_path):
    """Bundled/generated pycs may differ bytewise; executable code may not."""
    import importlib.util
    import marshal
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "repo"
    (root / "requirements").mkdir(parents=True)
    site = tmp_path / "site"
    (site / "demo").mkdir(parents=True)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    filename = "demo/__pycache__/__init__.cpython-" + str(sys.version_info.major) + str(sys.version_info.minor) + ".pyc"
    original_source = b"answer = 42\n"
    header = importlib.util.MAGIC_NUMBER + b"\x00" * 12
    original_cache = header + marshal.dumps(
        compile(original_source, "/approved/build/demo/__init__.py", "exec", dont_inherit=True)
    )
    wheel = wheels / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", original_source)
        archive.writestr(filename, original_cache)
        archive.writestr("demo-1.0.dist-info/WHEEL", SYNTHETIC_WHEEL_METADATA)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text("demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest())
    (site / "demo" / "__init__.py").write_bytes(original_source)
    (site / "demo-1.0.dist-info").mkdir()
    (site / "demo-1.0.dist-info" / "WHEEL").write_bytes(SYNTHETIC_WHEEL_METADATA)
    cache = site / filename
    cache.parent.mkdir(parents=True, exist_ok=True)
    regenerated = header + marshal.dumps(compile(
        original_source, "/different/installer/location.py", "exec", dont_inherit=True
    ))
    assert regenerated != original_cache
    cache.write_bytes(regenerated)
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheels)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)

    cache.write_bytes(header + marshal.dumps(compile(
        b"answer = -1\n", "/different/installer/location.py", "exec", dont_inherit=True
    )))
    with pytest.raises(ValueError, match="unreviewed installed bytecode cache"):
        trust.preflight_reviewed_environment(root)


def test_orphan_wheel_cache_drift_is_not_an_executable_whitelist(monkeypatch, tmp_path):
    """Without independently approved source, changed bytecode is refused."""
    import importlib.util
    import marshal
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "root"
    (root / "requirements").mkdir(parents=True)
    site = tmp_path / "site"
    site.mkdir()
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    cache_name = "demo/__pycache__/orphan.cpython-" + str(sys.version_info.major) + str(sys.version_info.minor) + ".pyc"
    baseline = importlib.util.MAGIC_NUMBER + b"\x00" * 12 + marshal.dumps(
        compile(b"test = 1\n", "/builder/orphan.py", "exec", dont_inherit=True)
    )
    wheel = wheels / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr(cache_name, baseline)
        z.writestr("demo-1.0.dist-info/WHEEL", SYNTHETIC_WHEEL_METADATA)
    (site / "demo" / "__pycache__").mkdir(parents=True)
    installed = site / cache_name
    installed.write_bytes(baseline + b"attacker")
    (site / "demo-1.0.dist-info").mkdir()
    (site / "demo-1.0.dist-info" / "WHEEL").write_bytes(SYNTHETIC_WHEEL_METADATA)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text("demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest())
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheels)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()
    with pytest.raises(ValueError, match="unverified installed bytecode cache"):
        trust.preflight_reviewed_environment(root)


def test_sealed_policy_is_immune_to_both_original_files_rotating(monkeypatch, tmp_path, capsys):
    """The child must score the original approved policy, not swapped paths."""
    from types import SimpleNamespace
    from tools import qualification_bootstrap as bootstrap

    manifests, policy, images = _fixtures(tmp_path)
    bootstrap_file = _approval_file(policy)
    original_digest = bootstrap_file.read_text()
    original_runner = subprocess.run
    replaced = []

    def swap_at_child_start(command, *args, **kwargs):
        if isinstance(command, list) and "--_staged" in command and not replaced:
            replaced.append(True)
            tampered = json.loads(policy.read_text())
            tampered["holdout_manifest_sha256"] = "0" * 64
            policy.write_text(json.dumps(tampered))
            bootstrap_file.write_text(hashlib.sha256(policy.read_bytes()).hexdigest())
            assert bootstrap_file.read_text() != original_digest
            assert len(kwargs.get("pass_fds", ())) == 2
        return original_runner(command, *args, **kwargs)

    monkeypatch.setattr(bootstrap.subprocess, "run", swap_at_child_start)
    inputs = SimpleNamespace(
        repository=REPOSITORY,
        development=manifests["development"],
        validation=manifests["validation"],
        holdout=manifests["holdout"],
        policy=policy, approved_digest_file=bootstrap_file,
        image_root=images, wheelhouse=None,
    )
    assert bootstrap._run(inputs) == 0
    assert replaced
    public = json.loads(capsys.readouterr().out)
    assert public["public_qualification"] == "NOT_AUTHORIZED"
    assert public["data_origin"] == "SYNTHETIC_FIXTURE"



def test_unreviewed_python_shadow_in_purelib_is_blocked_before_platlib_import(
    monkeypatch, tmp_path,
):
    """Codex P1: a loose cv2.py must not shadow the reviewed native cv2 wheel."""
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "reviewed-source"
    (root / "requirements").mkdir(parents=True)
    purelib = tmp_path / "purelib"
    platlib = tmp_path / "platlib"
    wheels = tmp_path / "wheels"
    for directory in (purelib, platlib, wheels):
        directory.mkdir()
    wheel = wheels / "cv2-1.0-py3-none-any.whl"
    metadata = SYNTHETIC_WHEEL_METADATA.replace(
        b"Root-Is-Purelib: true", b"Root-Is-Purelib: false"
    )
    signed_source = b"REVIEWED = True\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("cv2/__init__.py", signed_source)
        archive.writestr("cv2-1.0.dist-info/WHEEL", metadata)
    (platlib / "cv2").mkdir()
    (platlib / "cv2" / "__init__.py").write_bytes(signed_source)
    (platlib / "cv2-1.0.dist-info").mkdir()
    (platlib / "cv2-1.0.dist-info" / "WHEEL").write_bytes(metadata)
    lock = root / "requirements" / f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    lock.write_text(
        "cv2==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheels)
    monkeypatch.setattr(trust, "_site_roots", lambda: (purelib, platlib))
    trust._trusted_files.cache_clear()
    trust.preflight_reviewed_environment(root)

    attacker = purelib / "cv2.py"
    attacker.write_text("REVIEWED = False\n")
    with pytest.raises(ValueError, match="unreviewed installed Python"):
        trust.preflight_reviewed_environment(root)
    attacker.unlink()

    import importlib.util
    import marshal
    cache = purelib / "__pycache__" / (
        f"cv2.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc"
    )
    cache.parent.mkdir()
    cache.write_bytes(
        importlib.util.MAGIC_NUMBER + b"\x00" * 12
        + marshal.dumps(compile(b"REVIEWED = False\n", "/unapproved/cv2.py", "exec"))
    )
    with pytest.raises(ValueError, match="unverified installed bytecode cache"):
        trust.preflight_reviewed_environment(root)



@pytest.mark.parametrize("optimize", (0, 1, 2))
@pytest.mark.parametrize("wheel_bundled_cache", (False, True))
def test_optimized_installed_cache_requires_canonical_tag_and_reviewed_code(
    tmp_path, monkeypatch, optimize, wheel_bundled_cache,
):
    """Generated and wheel-bundled optimized caches are validated against
    independently hash-reviewed source with the matching optimization level.
    """
    import importlib.util
    import marshal
    import zipfile
    from evaluation.segmentation import runtime_integrity as trust

    root = tmp_path / "reviewed"
    (root / "requirements").mkdir(parents=True)
    site = tmp_path / "site"
    package = site / "demo"
    package.mkdir(parents=True)
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    source = package / "__init__.py"
    source_bytes = b'"""source docstring"""\nassert 1 + 1 == 2\nanswer = 42\n'
    source.write_bytes(source_bytes)
    cache = Path(importlib.util.cache_from_source(
        str(source), optimization=str(optimize) if optimize else "",
    ))
    cache.parent.mkdir(parents=True)
    name = cache.relative_to(site).as_posix()
    prefix = importlib.util.MAGIC_NUMBER + b"\x00" * 12
    compiled_approved = prefix + marshal.dumps(compile(
        source_bytes, "/wheel-builder/demo/__init__.py",
        "exec", dont_inherit=True, optimize=optimize,
    ))
    compiled_installed = prefix + marshal.dumps(compile(
        source_bytes, "/installed/demo/__init__.py",
        "exec", dont_inherit=True, optimize=optimize,
    ))
    assert compiled_approved != compiled_installed
    if optimize:
        assert compile(
            source_bytes, "/builder/file.py", "exec",
            dont_inherit=True, optimize=0,
        ) != compile(
            source_bytes, "/builder/file.py", "exec",
            dont_inherit=True, optimize=optimize,
        )
    wheel = wheels / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", source_bytes)
        archive.writestr("demo-1.0.dist-info/WHEEL", SYNTHETIC_WHEEL_METADATA)
        if wheel_bundled_cache:
            archive.writestr(name, compiled_approved)
    (site / "demo-1.0.dist-info").mkdir()
    (site / "demo-1.0.dist-info" / "WHEEL").write_bytes(SYNTHETIC_WHEEL_METADATA)
    cache.write_bytes(compiled_installed)
    lock = root / "requirements" / (
        f"ci-py{sys.version_info.major}{sys.version_info.minor}.lock"
    )
    lock.write_text(
        "demo==1.0 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(trust, "_wheelhouse_path", lambda: wheels)
    monkeypatch.setattr(trust, "_site_roots", lambda: (site,))
    trust._trusted_files.cache_clear()

    trust.preflight_reviewed_environment(root)
    cache.write_bytes(prefix + marshal.dumps(compile(
        b'"""source docstring"""\nassert 1 + 1 == 2\nanswer = -1\n',
        "/installed/demo/__init__.py", "exec",
        dont_inherit=True, optimize=optimize,
    )))
    with pytest.raises(ValueError, match="unverified installed bytecode cache"):
        trust.preflight_reviewed_environment(root)


@pytest.mark.parametrize("tag", ("3", "01", "unexpected"))
def test_unrecognized_optimized_cache_names_fail_closed(tmp_path, tag):
    import importlib.util
    import marshal
    from evaluation.segmentation.runtime_integrity import _verify_cached_code_matches_source

    source = tmp_path / "package" / "reviewed.py"
    source.parent.mkdir()
    original = b'"""source docstring"""\nassert True\nanswer = 42\n'
    source.write_bytes(original)
    malformed = Path(importlib.util.cache_from_source(
        str(source), optimization=tag,
    ))
    malformed.parent.mkdir()
    malformed.write_bytes(
        importlib.util.MAGIC_NUMBER + b"\x00" * 12
        + marshal.dumps(compile(
            original, "/builder/reviewed.py", "exec",
            dont_inherit=True, optimize=1,
        ))
    )
    approved = {source.absolute(): (hashlib.sha256(original).hexdigest(), "test", "package/reviewed.py")}
    with pytest.raises(ValueError, match="unverified installed bytecode cache"):
        _verify_cached_code_matches_source(malformed, source, approved)


def test_externally_provisioned_bootstrap_refuses_optimized_interpreter(tmp_path):
    manifests, policy, images = _fixtures(tmp_path)
    bootstrap = _externally_provisioned_test_bootstrap(tmp_path)
    args = _bootstrap_args(
        bootstrap,
        "--development", str(manifests["development"]),
        "--validation", str(manifests["validation"]),
        "--holdout", str(manifests["holdout"]),
        "--policy", str(policy),
        "--approved-digest-file", str(_approval_file(policy)),
        "--image-root", str(images),
    )
    args.insert(1, "-O")
    run = subprocess.run(
        args, cwd=REPOSITORY, text=True, capture_output=True, timeout=25,
    )
    assert run.returncode == 2
    assert "[Q_ISOLATION]" in run.stderr
    assert not run.stdout
