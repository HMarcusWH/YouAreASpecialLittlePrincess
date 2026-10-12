"""Rights-gated protocol qualification: writer-disjoint and predeclared holdout.

This is a protocol checker, not a license/consent validator and not a
substitute for reviewing raw evidence with authorized annotators.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import math
import platform
from pathlib import Path

from .strict_json import strict_loads


def _records(path: Path, expected_split: str):
    raw = path.read_bytes()
    data = strict_loads(raw)
    if data.get("schema_version") != 2 or data.get("split") != expected_split:
        raise ValueError("expected v2 " + expected_split + " manifest")
    if data.get("annotation_frame") not in ("original_image", "analysis_canvas"):
        raise ValueError("annotation frame must be explicit")
    records = data.get("specimens")
    if not isinstance(records, list) or not records or len(records) > 256:
        raise ValueError("invalid specimen count")
    for row in records:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k]
                for k in ("specimen_id", "writer_group", "capture_group",
                          "sha256", "rights_decision_id")):
            raise ValueError("missing specimen identity/rights fields")
    for field in ("specimen_id", "sha256"):
        if len({x[field] for x in records}) != len(records):
            raise ValueError("duplicate " + field)
    return data, hashlib.sha256(raw).hexdigest()


def predeclared_holdout_gate(development: Path, holdout: Path, policy: Path) -> dict:
    """Check frozen policy/holdout identity without disclosing writer IDs."""
    dev, _ = _records(development, "development")
    held, digest = _records(holdout, "holdout")
    approved = strict_loads(policy.read_bytes())
    if approved.get("schema_version") != 1 or approved.get("holdout_manifest_sha256") != digest:
        raise ValueError("holdout manifest does not match predeclared reviewed SHA")
    for label in ("writer_group", "capture_group", "sha256"):
        a = {r[label] for r in dev["specimens"]}
        b = {r[label] for r in held["specimens"]}
        if a & b:
            raise ValueError("development/holdout " + label + " leakage")
    targets = approved.get("thresholds")
    required = {"minimum_holdout_n", "min_line_macro_f1", "min_word_macro_f1",
                "min_qualified_fraction", "max_false_zero_words"}
    if not isinstance(targets, dict) or set(targets) != required:
        raise ValueError("all acceptance thresholds must be predeclared")
    for key, value in targets.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid acceptance threshold")
    if not (0 <= targets["min_line_macro_f1"] <= 1
            and 0 <= targets["min_word_macro_f1"] <= 1
            and 0 <= targets["min_qualified_fraction"] <= 1
            and type(targets["minimum_holdout_n"]) is int
            and type(targets["max_false_zero_words"]) is int):
        raise ValueError("invalid metric bounds")
    return {"schema_version": 1, "protocol_qualified": True,
            "development_n": len(dev["specimens"]),
            "holdout_n": len(held["specimens"]),
            "holdout_manifest_sha256": digest, "thresholds": targets}


def score_holdout(summary: dict, approved: dict) -> dict:
    """Legacy v1 aggregates cannot establish a qualified benchmark result.

    Kept for historical synthetic test callers; never returns authorization.
    Use run_frozen_synthetic_qualification for an internally computed result.
    """
    return {"accepted": False, "reason": "unverifiable_legacy_aggregate",
            "public_qualification": "NOT_AUTHORIZED"}


# V2 is deliberately fixture-only while T11 pilot_rights_consent is pending.
# This module has no option to authorize real participants or promote a profile.
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
THRESHOLD_KEYS = frozenset((
    "minimum_holdout_n", "minimum_holdout_writers",
    "minimum_nonempty_line_n", "minimum_nonempty_word_n",
    "min_line_nonempty_macro_f1", "min_word_nonempty_macro_f1",
    "min_line_coverage", "min_word_coverage",
    "min_nonempty_line_coverage", "min_nonempty_word_coverage",
    "minimum_empty_line_n", "minimum_empty_word_n",
    "minimum_available_empty_line_n", "minimum_available_empty_word_n",
    "min_empty_line_coverage", "min_empty_word_coverage",
    "max_empty_line_false_positive_pages", "max_empty_word_false_positive_pages",
    "max_false_zero_words",
))
FRACTION_TARGETS = frozenset((
    "min_line_nonempty_macro_f1", "min_word_nonempty_macro_f1",
    "min_line_coverage", "min_word_coverage",
    "min_nonempty_line_coverage", "min_nonempty_word_coverage",
    "min_empty_line_coverage", "min_empty_word_coverage",
))
INTEGER_TARGETS = THRESHOLD_KEYS - FRACTION_TARGETS
POSITIVE_COVERAGE_TARGETS = frozenset(("min_empty_line_coverage", "min_empty_word_coverage"))


def _reviewed_runtime_identity() -> dict:
    """Fail closed unless running from an exact reviewed CI dependency snapshot.

    Only Linux x86_64, Python 3.10..3.12 currently have approved lock files.
    Other platforms need separately reviewed locks before qualification.
    """
    import cv2
    import numpy as np
    from tools import verify_ci_lock as locks

    verifier_file = ROOT / "tools" / "verify_ci_lock.py"
    try:
        module_origin = Path(locks.__file__).resolve(strict=True)
        expected_origin = verifier_file.resolve(strict=True)
    except (AttributeError, OSError, TypeError) as exc:
        raise ValueError("unreviewed lock verifier module origin") from exc
    if verifier_file.is_symlink() or module_origin != expected_origin:
        raise ValueError("unreviewed lock verifier module origin")

    target = locks.running_target()
    if target[1:] != ("Linux", "x86_64") or target[0] not in ("3.10", "3.11", "3.12"):
        raise ValueError("no reviewed qualification dependency target")
    interpreter = target[0].replace(".", "")
    manifest_path = ROOT / "requirements" / f"ci-py{interpreter}.txt"
    lock_path = ROOT / "requirements" / f"ci-py{interpreter}.lock"
    if (manifest_path.is_symlink() or lock_path.is_symlink()
            or not manifest_path.is_file() or not lock_path.is_file()):
        raise ValueError("missing or unreviewed dependency snapshot")

    try:
        manifest = locks.read_manifest(manifest_path)
        reviewed = locks.read_lock(lock_path)
        installed = locks.installed_distributions()
        lock_target = locks.read_lock_target(lock_path)
        numpy_distribution = importlib.metadata.version("numpy")
        opencv_distribution = importlib.metadata.version("opencv-python-headless")
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        raise ValueError("dependency snapshot cannot be verified") from exc
    if (lock_target != target or manifest != reviewed
            or reviewed.get("numpy") != numpy_distribution
            or reviewed.get("opencv-python-headless") != opencv_distribution):
        raise ValueError("reviewed dependency versions or platform mismatch")

    expected_installed = dict(reviewed)
    expected_installed["special-little-princess-graphology"] = "0.1.0"
    if installed != expected_installed:
        raise ValueError("installed environment differs from reviewed dependency lock")
    if np.__version__ != reviewed["numpy"]:
        raise ValueError("imported NumPy differs from reviewed dependency lock")
    if not isinstance(cv2.__version__, str) or not cv2.__version__:
        raise ValueError("unverifiable imported OpenCV runtime")

    distribution_bytes = json.dumps(
        installed, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_target": target[0],
        "os": target[1],
        "architecture": target[2],
        "numpy_module_version": np.__version__,
        "opencv_module_version": cv2.__version__,
        "numpy_distribution_version": numpy_distribution,
        "opencv_distribution_version": opencv_distribution,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "installed_distributions_sha256": hashlib.sha256(distribution_bytes).hexdigest(),
    }


def current_local_identity() -> dict:
    """Read code/config identity from actual checkout, not caller-supplied claims.

    Not a signed attestation: external review, source-control access and process
    integrity remain requirements for protected evaluation.
    """
    from princess_app.application.intake import analysis_config_sha256

    try:
        run = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("source revision cannot be verified") from exc
    # HEAD alone does not establish which code actually executed: an edited
    # working tree could behave differently while still advertising that SHA.
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal", "--",
             "src/princess_graphology", "src/princess_app/application/intake.py",
             "evaluation/segmentation", "tools/verify_ci_lock.py", "requirements"],
            cwd=ROOT, text=True, capture_output=True, check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("source checkout cleanliness cannot be verified") from exc
    if dirty.stdout.strip():
        raise ValueError("source checkout contains unreviewed evaluation changes")
    commit = run.stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("invalid source revision")
    from . import benchmark
    verifier_file = ROOT / "tools" / "verify_ci_lock.py"
    if verifier_file.is_symlink() or not verifier_file.is_file():
        raise ValueError("unreviewed lock verifier source")
    return {"source_commit_sha": commit,
            "analysis_config_sha256": analysis_config_sha256(grid_profile="qualified-v2"),
            "evaluator_sha256": hashlib.sha256(Path(benchmark.__file__).read_bytes()).hexdigest(),
            "qualification_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "lock_verifier_sha256": hashlib.sha256(verifier_file.read_bytes()).hexdigest(),
            "environment": _reviewed_runtime_identity()}


def _synthetic_manifest(path: Path, split: str):
    """Strict closed-shape fixture manifests. Human-data admission is absent."""
    from .benchmark import validate_record

    raw = path.read_bytes()
    data = strict_loads(raw)
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "annotation_frame", "split", "synthetic", "specimens"
    }:
        raise ValueError("invalid frozen fixture manifest shape")
    if data["schema_version"] != 2 or data["split"] != split or data["synthetic"] is not True:
        raise ValueError("real-data qualification not authorized")
    if data["annotation_frame"] != "original_image":
        raise ValueError("frozen fixture annotations require original_image coordinates")
    rows = data["specimens"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError("invalid frozen fixture specimen count")
    required = {"specimen_id", "writer_group", "capture_group",
                "source_specimen_group", "image_path", "sha256", "paper", "lines", "words"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("invalid frozen fixture record shape")
        validate_record(row, "synthetic")
        if any(not isinstance(row[key], str) or not row[key] or len(row[key]) > 256
               for key in ("source_specimen_group", "writer_group", "capture_group")):
            raise ValueError("invalid source/writer/capture identity")
        if not HASH_PATTERN.fullmatch(row["sha256"]):
            raise ValueError("invalid image digest")
    for field in ("specimen_id", "sha256"):
        if len({r[field] for r in rows}) != len(rows):
            raise ValueError("duplicate " + field)
    return data, hashlib.sha256(raw).hexdigest()


def _validate_thresholds(targets):
    if not isinstance(targets, dict) or set(targets) != THRESHOLD_KEYS:
        raise ValueError("incomplete frozen thresholds")
    for key in FRACTION_TARGETS:
        value = targets[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("invalid frozen fraction: " + key)
        if key in POSITIVE_COVERAGE_TARGETS:
            allowed = 0 < value <= 1
        else:
            allowed = 0 <= value <= 1
        if not allowed:
            raise ValueError("invalid frozen fraction: " + key)
    for key in INTEGER_TARGETS:
        value = targets[key]
        if type(value) is not int or value < (0 if key.startswith("max_") else 1):
            raise ValueError("invalid frozen count: " + key)


def predeclared_holdout_gate_v2(
    development: Path, validation: Path, holdout: Path, policy: Path,
    *, expected_policy_sha256: str,
) -> dict:
    """Require an externally approved policy digest BEFORE examining holdout data.

    The supplied digest must come from an independent, prior approval record.
    Comparing caller-provided hashes is an integrity check, not proof of when
    or by whom a policy was approved.
    """
    if not isinstance(expected_policy_sha256, str) or not HASH_PATTERN.fullmatch(
        expected_policy_sha256
    ):
        raise ValueError("independently approved policy digest required")
    raw_policy = policy.read_bytes()
    policy_digest = hashlib.sha256(raw_policy).hexdigest()
    if not hmac.compare_digest(policy_digest, expected_policy_sha256):
        raise ValueError("independently approved policy digest mismatch")
    documents = {}
    digests = {}
    for split, path in (
        ("development", development), ("validation", validation), ("holdout", holdout)
    ):
        documents[split], digests[split] = _synthetic_manifest(path, split)
    for i, left in enumerate(documents):
        for right in list(documents)[i + 1:]:
            for field in ("specimen_id", "writer_group", "capture_group",
                          "source_specimen_group", "sha256"):
                a = {r[field] for r in documents[left]["specimens"]}
                b = {r[field] for r in documents[right]["specimens"]}
                if a & b:
                    raise ValueError(f"{left}/{right} {field} leakage")

    approved = strict_loads(raw_policy)
    policy_fields = {"schema_version", "mode", "profile",
                     "development_manifest_sha256", "validation_manifest_sha256",
                     "holdout_manifest_sha256", "source_commit_sha",
                     "analysis_config_sha256", "evaluator_sha256",
                     "qualification_sha256", "lock_verifier_sha256", "environment", "thresholds"}
    if not isinstance(approved, dict) or set(approved) != policy_fields:
        raise ValueError("invalid frozen qualification policy shape")
    if approved["schema_version"] != 2 or approved["mode"] != "synthetic" or (
        approved["profile"] != "qualified-v2"
    ):
        raise ValueError("real qualification and profile promotion not authorized")
    for split in documents:
        if approved[split + "_manifest_sha256"] != digests[split]:
            raise ValueError("predeclared " + split + " digest mismatch")
    _validate_thresholds(approved["thresholds"])
    identity = current_local_identity()
    for key, expected in identity.items():
        if approved[key] != expected:
            raise ValueError("frozen processing/source/evaluator identity mismatch: " + key)
    return {"policy_digest": policy_digest,
            "profile": "qualified-v2", "mode": "synthetic", "identity": identity,
            "holdout_manifest_sha256": digests["holdout"],
            "holdout_writers": len({r["writer_group"] for r in documents["holdout"]["specimens"]}),
            "holdout_records": documents["holdout"]["specimens"],
            "thresholds": approved["thresholds"]}


def _checked_holdout_rows(result, frozen):
    """Fail on untrusted provenance, truncated results or altered identities."""
    from .benchmark import DATA_ORIGIN_SYNTHETIC

    expected = {r["specimen_id"]: r for r in frozen["holdout_records"]}
    if not isinstance(result, dict) or result.get("profile") != frozen["profile"] or (
        result.get("split") != "holdout"
    ) or result.get("manifest_sha256") != frozen["holdout_manifest_sha256"] or (
        result.get("data_origin") != DATA_ORIGIN_SYNTHETIC
    ):
        raise ValueError("wrong frozen benchmark identity")
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("frozen holdout coverage mismatch")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("specimen_id") not in expected:
            raise ValueError("unexpected frozen specimen")
        ident = row["specimen_id"]
        if ident in seen:
            raise ValueError("duplicate frozen benchmark result")
        seen.add(ident)
        original = expected[ident]
        if row.get("split") != "holdout" or row.get("paper") != original["paper"] or (
            row.get("data_origin") != DATA_ORIGIN_SYNTHETIC
        ):
            raise ValueError("frozen benchmark metadata mismatch")
        for family in ("line", "word"):
            number = row.get(family + "_reference_n")
            if number != len(original["lines" if family == "line" else "words"]):
                raise ValueError("frozen annotation count mismatch")
        status = row.get("status")
        if status not in ("MEASURED", "PARTIAL", "REJECTED"):
            raise ValueError("unknown benchmark outcome")
        metrics = {}
        for family in ("line", "word"):
            value = row.get("lines" if family == "line" else "words")
            metrics[family] = value
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError("invalid scored metric")
            reference = len(original["lines" if family == "line" else "words"])
            for key in ("reference_n", "detected_n", "tp", "fp", "fn", "count_mae"):
                if type(value.get(key)) is not int or value[key] < 0:
                    raise ValueError("invalid scored metric count")
            if (value["reference_n"] != reference
                    or value["tp"] + value["fn"] != reference
                    or value["tp"] + value["fp"] != value["detected_n"]
                    or value["count_mae"] != abs(reference - value["detected_n"])):
                raise ValueError("inconsistent scored metric counts")
            expected_p = (value["tp"] / value["detected_n"] if value["detected_n"]
                          else (1.0 if not reference else 0.0))
            expected_r = (value["tp"] / reference if reference
                          else (1.0 if not value["detected_n"] else 0.0))
            expected_f1 = (2 * expected_p * expected_r / (expected_p + expected_r)
                           if expected_p + expected_r else 0.0)
            for key, expected_score in (
                ("precision", expected_p), ("recall", expected_r), ("f1", expected_f1)
            ):
                score = value.get(key)
                if (type(score) not in (int, float) or not math.isfinite(score)
                        or abs(score - expected_score) > 1e-9):
                    raise ValueError("inconsistent scored metric values")
        if status == "REJECTED" and any(m is not None for m in metrics.values()):
            raise ValueError("rejected result cannot claim measured accuracy")
        if status == "MEASURED" and any(m is None for m in metrics.values()):
            raise ValueError("measured result lacks annotated accuracy")
        if status == "PARTIAL" and all(m is not None for m in metrics.values()):
            raise ValueError("partial result cannot claim full availability")
        if metrics["word"] is None:
            if row.get("false_zero_words") is not None:
                raise ValueError("withheld word group cannot assert a zero")
        elif row.get("false_zero_words") is not (
            bool(original["words"]) and metrics["word"]["detected_n"] == 0
        ):
            raise ValueError("false-zero words disagree with scored results")
    if seen != set(expected):
        raise ValueError("missing frozen benchmark result")
    return rows


def _engineering_gates(rows, frozen):
    from .benchmark import summarize

    overall = summarize(rows)["overall"]  # Never trust a caller-supplied summary.
    if overall["count"] != len(frozen["holdout_records"]):
        raise ValueError("incomplete holdout denominator")
    line, word = overall["lines"], overall["words"]
    targets = frozen["thresholds"]
    checks = {
        "minimum_holdout_n": overall["count"] >= targets["minimum_holdout_n"],
        "minimum_holdout_writers": frozen["holdout_writers"] >= targets["minimum_holdout_writers"],
        "minimum_nonempty_line_n": line["nonempty_eligible_n"] >= targets["minimum_nonempty_line_n"],
        "minimum_nonempty_word_n": word["nonempty_eligible_n"] >= targets["minimum_nonempty_word_n"],
        "min_line_nonempty_macro_f1":
            line["nonempty_macro_f1"] is not None and
            line["nonempty_macro_f1"] >= targets["min_line_nonempty_macro_f1"],
        "min_word_nonempty_macro_f1":
            word["nonempty_macro_f1"] is not None and
            word["nonempty_macro_f1"] >= targets["min_word_nonempty_macro_f1"],
        "min_line_coverage": line["coverage"] is not None and
                             line["coverage"] >= targets["min_line_coverage"],
        "min_word_coverage": word["coverage"] is not None and
                             word["coverage"] >= targets["min_word_coverage"],
        "min_nonempty_line_coverage": line["nonempty_coverage"] is not None and
                                     line["nonempty_coverage"] >= targets["min_nonempty_line_coverage"],
        "min_nonempty_word_coverage": word["nonempty_coverage"] is not None and
                                     word["nonempty_coverage"] >= targets["min_nonempty_word_coverage"],
        "minimum_empty_line_n":
            line["empty_eligible_n"] >= targets["minimum_empty_line_n"],
        "minimum_empty_word_n":
            word["empty_eligible_n"] >= targets["minimum_empty_word_n"],
        "minimum_available_empty_line_n":
            line["empty_available_n"] >= targets["minimum_available_empty_line_n"],
        "minimum_available_empty_word_n":
            word["empty_available_n"] >= targets["minimum_available_empty_word_n"],
        "min_empty_line_coverage":
            line["empty_coverage"] is not None
            and line["empty_coverage"] >= targets["min_empty_line_coverage"],
        "min_empty_word_coverage":
            word["empty_coverage"] is not None
            and word["empty_coverage"] >= targets["min_empty_word_coverage"],
        "max_empty_line_false_positive_pages":
            line["empty_false_positive_n"] <= targets["max_empty_line_false_positive_pages"],
        "max_empty_word_false_positive_pages":
            word["empty_false_positive_n"] <= targets["max_empty_word_false_positive_pages"],
        "max_false_zero_words": overall["false_zero_words"] <= targets["max_false_zero_words"],
    }
    return overall, checks


def run_frozen_synthetic_qualification(
    development: Path, validation: Path, holdout: Path, policy: Path, image_root: Path,
    *, expected_policy_sha256: str,
) -> dict:
    """Run a pinned synthetic holdout directly; never accept a supplied aggregate.

    The return is NOT a scientific or legal authorization. Human pilots are
    blocked by T11, and real rights evaluation must be separately designed.
    """
    from .benchmark import run_manifest

    frozen = predeclared_holdout_gate_v2(
        development, validation, holdout, policy,
        expected_policy_sha256=expected_policy_sha256,
    )
    result = run_manifest(holdout, image_root, profile=frozen["profile"],
                          allow_real=False, synthetic_split=True)
    rows = _checked_holdout_rows(result, frozen)
    summary, gates = _engineering_gates(rows, frozen)
    return {"kind": "segmentation-qualification/2", "mode": "synthetic",
            "data_origin": "SYNTHETIC_FIXTURE",
            "public_qualification": "NOT_AUTHORIZED",
            "decision": "ENGINEERING_PASS" if all(gates.values()) else "ENGINEERING_FAIL",
            "engineering_gates": gates,
            "specimen_count": summary["count"],
            "writer_count": frozen["holdout_writers"],
            "line_coverage": summary["lines"]["coverage"],
            "word_coverage": summary["words"]["coverage"],
            "nonempty_line_f1": summary["lines"]["nonempty_macro_f1"],
            "nonempty_word_f1": summary["words"]["nonempty_macro_f1"],
            "policy_digest": frozen["policy_digest"],
            "manifest_digest": frozen["holdout_manifest_sha256"]}


def public_safe_receipt(receipt: dict) -> dict:
    """Allowlisted redacted output; no private paths, IDs, or manifest hashes."""
    if not isinstance(receipt, dict) or receipt.get("kind") != "segmentation-qualification/2" or (
        receipt.get("mode") != "synthetic" or receipt.get("data_origin") != "SYNTHETIC_FIXTURE"
        or receipt.get("public_qualification") != "NOT_AUTHORIZED"
    ) or receipt.get("decision") not in ("ENGINEERING_PASS", "ENGINEERING_FAIL"):
        raise ValueError("no publishable qualification receipt")
    # Counts/metrics are deliberately not released for tiny cells, even though
    # current mode is synthetic. Real-publication policy is separately gated.
    count = receipt.get("specimen_count")
    return {"kind": "segmentation-public-summary/1", "mode": "synthetic",
            "data_origin": "SYNTHETIC_FIXTURE",
            "public_qualification": "NOT_AUTHORIZED",
            "decision": receipt["decision"],
            "specimen_count": count if type(count) is int and count >= 5 else None,
            "metrics": "WITHHELD_SMALL_CELL_OR_UNREVIEWED"}
