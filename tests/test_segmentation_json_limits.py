"""Synthetic-only JSON byte admission and finite-number trust boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.segmentation import benchmark, qualification, run_qualification, strict_json
from tools import qualification_bootstrap


def _write_json(path: Path, data):
    path.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return path


def _policy(tmp_path, payload=b"{}"):
    policy = tmp_path / "frozen-policy.json"
    digest = tmp_path / "approved-policy.sha256"
    policy.write_bytes(payload)
    digest.write_text(hashlib.sha256(payload).hexdigest(), encoding="ascii")
    return policy, digest


def _v2_splits(tmp_path):
    files = {}
    for kind in ("development", "validation", "holdout"):
        record = {
            "specimen_id": kind + "-sample-1",
            "writer_group": kind + "-writer-1",
            "capture_group": kind + "-capture-1",
            "source_specimen_group": kind + "-source-1",
            "image_path": kind + ".png",
            "sha256": hashlib.sha256(kind.encode()).hexdigest(),
            "paper": "blank", "lines": [], "words": [],
        }
        document = {
            "schema_version": 2, "split": kind, "synthetic": True,
            "annotation_frame": "original_image", "specimens": [record],
        }
        files[kind] = _write_json(tmp_path / (kind + ".json"), document)
    return files


def _v1_splits(tmp_path):
    files = {}
    for kind in ("development", "holdout"):
        record = {
            "specimen_id": kind + "-sample", "writer_group": kind + "-writer",
            "capture_group": kind + "-capture",
            "sha256": hashlib.sha256(kind.encode()).hexdigest(),
            "rights_decision_id": "synthetic-" + kind,
        }
        files[kind] = _write_json(tmp_path / ("v1-" + kind + ".json"), {
            "schema_version": 2, "annotation_frame": "original_image",
            "split": kind, "specimens": [record],
        })
    return files


def test_single_descriptor_bounded_reader_preserves_bytes_and_exact_limit(tmp_path):
    raw = b'{"safe":true} \n'
    path = tmp_path / "source.json"
    path.write_bytes(raw)
    assert strict_json.read_bounded_json_bytes(path, len(raw)) == raw
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        strict_json.read_bounded_json_bytes(path, len(raw) - 1)
    assert hashlib.sha256(strict_json.read_bounded_json_bytes(path, len(raw))).digest() == (
        hashlib.sha256(raw).digest()
    )


def test_sparse_64mib_manifest_refused_before_json_parser(tmp_path, monkeypatch):
    manifest = tmp_path / "sparse-manifest.json"
    with manifest.open("wb") as stream:
        stream.truncate(strict_json.MAX_MANIFEST_JSON_BYTES + 1)
    def parse_forbidden(_raw):
        pytest.fail("JSON parser called on oversized input")
    monkeypatch.setattr(benchmark, "strict_loads", parse_forbidden)
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        benchmark.run_manifest(manifest, tmp_path, profile="legacy")


def test_file_growth_or_stale_fstat_cannot_bypass_read_limit(tmp_path, monkeypatch):
    path = tmp_path / "growing.json"
    path.write_bytes(b"a" * 15)
    original = strict_json.os.fstat
    def underestimated_size(fd):
        actual = original(fd)
        return SimpleNamespace(st_mode=actual.st_mode, st_size=14)
    monkeypatch.setattr(strict_json.os, "fstat", underestimated_size)
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        strict_json.read_bounded_json_bytes(path, 14)


def test_nonregular_stream_refused_and_error_never_includes_path(tmp_path):
    with pytest.raises(ValueError) as caught:
        strict_json.read_bounded_json_bytes(tmp_path, 16)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("bad", (0.5, -1, None, True))
def test_noninteger_budget_refused_before_io(bad, tmp_path):
    with pytest.raises(ValueError, match="invalid frozen JSON byte budget"):
        strict_json.read_bounded_json_bytes(tmp_path / "not-read.json", bad)


@pytest.mark.parametrize("file_index", ("development", "holdout"))
def test_v1_manifest_cap_applies_before_json_parse(tmp_path, monkeypatch, file_index):
    documents = _v1_splits(tmp_path)
    policy, _ = _policy(tmp_path)
    longest = max(len(f.read_bytes()) for f in documents.values())
    monkeypatch.setattr(qualification, "MAX_MANIFEST_JSON_BYTES", longest + 2)
    # Always exceed the shared budget, even when this partition is shorter.
    documents[file_index].write_bytes(
        documents[file_index].read_bytes() + b" " * (longest + 10)
    )
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        qualification.predeclared_holdout_gate(
            documents["development"], documents["holdout"], policy,
        )


def test_v1_policy_cap_applies_after_valid_manifests(tmp_path, monkeypatch):
    documents = _v1_splits(tmp_path)
    policy, _ = _policy(tmp_path, b"{}" + b" " * 40)
    monkeypatch.setattr(qualification, "MAX_POLICY_JSON_BYTES", 16)
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        qualification.predeclared_holdout_gate(
            documents["development"], documents["holdout"], policy,
        )


def test_v2_policy_cap_enforced_before_reading_any_manifest(tmp_path, monkeypatch):
    files = _v2_splits(tmp_path)
    policy, digest = _policy(tmp_path, b"{}" + b" " * 60)
    monkeypatch.setattr(qualification, "MAX_POLICY_JSON_BYTES", 16)
    monkeypatch.setattr(qualification, "_synthetic_manifest",
                        lambda *_args, **_kwargs: pytest.fail("manifest opened before policy admission"))
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        qualification.predeclared_holdout_gate_v2(
            files["development"], files["validation"], files["holdout"],
            policy, expected_policy_sha256=digest.read_text(),
        )


@pytest.mark.parametrize("bad_split", ("development", "validation", "holdout"))
def test_v2_each_split_cap_is_enforced_before_scoring(tmp_path, monkeypatch, bad_split):
    files = _v2_splits(tmp_path)
    policy, digest = _policy(tmp_path)
    original_lengths = [len(file.read_bytes()) for file in files.values()]
    individual = max(original_lengths) + 5
    monkeypatch.setattr(qualification, "MAX_MANIFEST_JSON_BYTES", individual)
    files[bad_split].write_bytes(files[bad_split].read_bytes() + b" " * 40)
    monkeypatch.setattr(benchmark.cv2, "imdecode",
                        lambda *_a, **_k: pytest.fail("decoded before bounded manifest admission"))
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        qualification.run_frozen_synthetic_qualification(
            files["development"], files["validation"], files["holdout"],
            policy, tmp_path, expected_policy_sha256=digest.read_text(),
        )


def test_three_split_cumulative_limit_refuses_before_last_parse(tmp_path, monkeypatch):
    files = _v2_splits(tmp_path)
    policy, digest = _policy(tmp_path)
    sizes = [len(file.read_bytes()) for file in files.values()]
    monkeypatch.setattr(qualification, "MAX_MANIFEST_JSON_BYTES", max(sizes) + 1)
    monkeypatch.setattr(qualification, "MAX_THREE_SPLIT_JSON_BYTES",
                        sum(sizes) - 1)
    original = qualification.strict_loads
    parsed = []
    def count_parser(raw):
        parsed.append(raw)
        return original(raw)
    monkeypatch.setattr(qualification, "strict_loads", count_parser)
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        qualification.predeclared_holdout_gate_v2(
            files["development"], files["validation"], files["holdout"],
            policy, expected_policy_sha256=digest.read_text(),
        )
    assert parsed == [files["development"].read_bytes(), files["validation"].read_bytes()]


def test_zero_aggregate_remainder_fails_before_next_split_is_opened(tmp_path, monkeypatch):
    files = _v2_splits(tmp_path)
    policy, digest = _policy(tmp_path)
    first_size = len(files["development"].read_bytes())
    monkeypatch.setattr(qualification, "MAX_THREE_SPLIT_JSON_BYTES", first_size)
    monkeypatch.setattr(qualification, "MAX_MANIFEST_JSON_BYTES", first_size + 20)
    before = qualification.read_bounded_json_bytes
    seen = []
    def count_reads(path, maximum):
        seen.append(Path(path).name)
        return before(path, maximum)
    monkeypatch.setattr(qualification, "read_bounded_json_bytes", count_reads)
    with pytest.raises(ValueError, match="aggregate byte budget"):
        qualification.predeclared_holdout_gate_v2(
            files["development"], files["validation"], files["holdout"],
            policy, expected_policy_sha256=digest.read_text(),
        )
    assert seen == [policy.name, files["development"].name]


@pytest.mark.parametrize("supplied", (False, True))
def test_benchmark_caps_both_manifest_entrypoints_before_parsing(tmp_path, monkeypatch, supplied):
    raw = b'{"schema_version":1,"split":"synthetic","specimens":[]}'
    manifest = tmp_path / "direct.json"
    manifest.write_bytes(raw)
    monkeypatch.setattr(benchmark, "MAX_MANIFEST_JSON_BYTES", len(raw) - 1)
    monkeypatch.setattr(benchmark, "strict_loads",
                        lambda *_a: pytest.fail("parser called before byte limit"))
    with pytest.raises(ValueError, match="frozen JSON exceeds byte budget"):
        benchmark.run_manifest(
            manifest, tmp_path, manifest_bytes=raw if supplied else None,
        )


def test_benchmark_rejects_nonbytes_supplied_snapshot_before_json_parser(tmp_path):
    with pytest.raises(ValueError, match="encoded bytes"):
        benchmark.run_manifest(tmp_path / "unused", tmp_path, manifest_bytes="{}")


@pytest.mark.parametrize("number", ("1e309", "-1e9999", "1e999999", "NaN", "Infinity", "-Infinity"))
def test_shared_parser_rejects_overflow_and_nonstandard_constants_anywhere(number):
    for raw in ('{"n":' + number + "}",
                '{"x":{"y":[1,{"hidden":' + number + "}]}}"):
        with pytest.raises(ValueError, match="nonfinite JSON"):
            strict_json.strict_loads(raw)


def test_shared_parser_keeps_finite_number_and_annotation_semantics():
    obj = strict_json.strict_loads(
        '{"n":1e308,"neg":-0.25,"tiny":1.25e-3,"i":0,'
        '"unknown":null,"explicit_empty":[],"word":"safely text"}',
    )
    assert math.isfinite(obj["n"]) and obj["n"] == 1e308
    assert obj["neg"] == -0.25 and obj["tiny"] == .00125
    assert obj["i"] == 0 and type(obj["i"]) is int
    assert obj["unknown"] is None and obj["explicit_empty"] == []


def test_strict_json_still_rejects_duplicate_nested_keys_and_deep_nesting():
    with pytest.raises(ValueError, match="duplicate JSON"):
        strict_json.strict_loads(b'{"top":{"a":1,"a":2}}')
    # CPython's JSON C decoder tolerates deeper arrays on 3.12 than on
    # 3.10/3.11. Exercise actual depth refusal on every supported runtime.
    deep = b"[" * 20_000 + b"0" + b"]" * 20_000
    with pytest.raises(ValueError, match="invalid frozen JSON"):
        strict_json.strict_loads(deep)


def test_numeric_overflow_cannot_hide_in_extra_manifest_fields(tmp_path):
    files = _v2_splits(tmp_path)
    policy, digest = _policy(tmp_path)
    corrupted = files["development"]
    original = corrupted.read_text()
    corrupted.write_text(original[:-1] + ',"uninspected":[{"n":1e309}]}')
    with pytest.raises(ValueError, match="nonfinite JSON"):
        qualification.predeclared_holdout_gate_v2(
            files["development"], files["validation"], files["holdout"],
            policy, expected_policy_sha256=digest.read_text(),
        )


def test_legacy_v1_policy_overflow_rejected_before_thresholds(tmp_path):
    files = _v1_splits(tmp_path)
    policy, _ = _policy(tmp_path, b'{"additional_unused_policy_value":1e309}')
    with pytest.raises(ValueError, match="nonfinite JSON"):
        qualification.predeclared_holdout_gate(
            files["development"], files["holdout"], policy,
        )


@pytest.mark.parametrize("literal", ("1e309", "-1e9999", "NaN"))
def test_external_bootstrap_and_worker_reject_approved_overflow_policy(tmp_path, literal):
    policy_bytes = (
        '{"schema_version":2,"mode":"synthetic","profile":"qualified-v2",'
        '"source_commit_sha":"' + "a" * 40 + '","unused":' + literal + "}"
    ).encode("ascii")
    policy, digest = _policy(tmp_path, policy_bytes)
    args = argparse.Namespace(policy=policy, approved_digest_file=digest)
    with pytest.raises(qualification_bootstrap._Rejected) as recorded:
        qualification_bootstrap._validated_policy_sha(args)
    assert recorded.value.code == "Q_POLICY"
    with pytest.raises(ValueError, match="nonfinite frozen policy"):
        run_qualification._verified_policy_revision(args)


def test_bootstrap_receipt_parser_rejects_nonfinite_numbers():
    for raw in ('{"unused":1e309}', '{"a":1,"a":2}', '{"x":NaN}'):
        with pytest.raises(ValueError):
            json.loads(
                raw, object_pairs_hook=qualification_bootstrap._unique_receipt_pairs,
                parse_constant=qualification_bootstrap._reject_receipt_constant,
                parse_float=qualification_bootstrap._finite_receipt_float,
            )


@pytest.mark.skipif(not hasattr(os, "memfd_create") or not hasattr(os, "MFD_ALLOW_SEALING"),
                    reason="Linux sealed memfd required")
def test_bounded_reader_accepts_sealed_linux_policy_fd():
    raw = b'{"schema_version":2,"finite":1.25e-3}'
    fd = qualification_bootstrap._sealed_snapshot(raw, "json-cap-test")
    try:
        admitted = strict_json.read_bounded_json_bytes(
            Path("/proc/self/fd") / str(fd), len(raw),
        )
        assert admitted == raw
        assert strict_json.strict_loads(admitted)["finite"] == 0.00125
        with pytest.raises(ValueError, match="byte budget"):
            strict_json.read_bounded_json_bytes(
                Path("/proc/self/fd") / str(fd), len(raw) - 1,
            )
    finally:
        os.close(fd)


def test_oversize_error_does_not_leak_private_specimen_file_paths(tmp_path):
    sensitive = tmp_path / "PRIVATE_WITNESS_ID.json"
    sensitive.write_bytes(b'{"secret":123456}' + b" " * 32)
    with pytest.raises(ValueError) as reported:
        strict_json.read_bounded_json_bytes(sensitive, 8)
    assert "PRIVATE_WITNESS_ID" not in str(reported.value)
    assert str(tmp_path) not in str(reported.value)
