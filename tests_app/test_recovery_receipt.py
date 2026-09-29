"""T24 recovery receipt and destructive-reset safety gates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "infra" / "recovery"))

import receipt  # noqa: E402
import run_restore_drill  # noqa: E402


def valid_receipt():
    return {
        "version": "recovery-receipt/1",
        "environment": "test",
        "synthetic_fixture": True,
        "production_claim": False,
        "database_backup_format": "postgres-custom",
        "backup_sha256": "a" * 64,
        "backup_size_bytes": 123,
        "alembic_revision_before": "0010_provider_attempt",
        "alembic_revision_after": "0010_provider_attempt",
        "restore_elapsed_ms": 1234,
        "recovery_elapsed_ms": 5678,
        "resurrection_observed": {"capture": True, "account": True, "permission": True},
        "tombstone_replay": {"reapplied": 3, "already": 0, "unknown": 0, "unreadable": 0},
        "second_replay": {"reapplied": 0, "already": 3, "unknown": 0, "unreadable": 0},
        "object_erasure_verified": True,
        "corrupt_backup_rejected": True,
        "rpo_target": None,
        "rto_target": None,
        "result": "PASS",
    }


def test_recovery_receipt_accepts_only_the_privacy_safe_pass_shape(tmp_path):
    data = valid_receipt()
    assert receipt.validate(data) == []
    path = tmp_path / "receipt.json"
    receipt.write(path, data)
    assert json.loads(path.read_text()) == data
    data["rto_target"] = "5m"
    assert "receipt_targets_are_owner_pending" in receipt.validate(data)
    data = valid_receipt()
    data["second_replay"]["reapplied"] = 1
    assert "receipt_second_replay" in receipt.validate(data)
    data = valid_receipt()
    data["backup_size_bytes"] = 0
    assert "receipt_backup_size_bytes" in receipt.validate(data)
    data = valid_receipt()
    data["alembic_revision_after"] = "different"
    assert "receipt_alembic_revision_changed" in receipt.validate(data)
    data = valid_receipt()
    data["recovery_elapsed_ms"] = data["restore_elapsed_ms"] - 1
    assert "receipt_elapsed_order" in receipt.validate(data)


def test_receipt_schema_and_runtime_validator_have_the_same_top_level_contract():
    schema = json.loads((ROOT / "infra/recovery/recovery-receipt.schema.json").read_text())
    assert set(schema["required"]) == receipt.TOP_LEVEL
    assert schema["additionalProperties"] is False


def test_destructive_restore_runner_refuses_missing_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("PRINCESS_RECOVERY_ALLOW_RESET", raising=False)
    monkeypatch.setenv("PRINCESS_BACKEND_IMAGE", "princess-backend:" + "a" * 40)
    monkeypatch.setenv("PRINCESS_RECOVERY_WORKDIR", str(tmp_path / "princess-recovery-test"))
    with pytest.raises(run_restore_drill.DrillFailure, match="ALLOW_RESET"):
        run_restore_drill.checked_settings()


def test_destructive_restore_runner_refuses_unqualified_image_and_workdir(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("PRINCESS_RECOVERY_ALLOW_RESET", "1")
    monkeypatch.setenv("PRINCESS_BACKEND_IMAGE", "princess-backend:latest")
    monkeypatch.setenv("PRINCESS_RECOVERY_WORKDIR", str(tmp_path / "princess-recovery-test"))
    with pytest.raises(run_restore_drill.DrillFailure, match="exact PR/main sha-tagged"):
        run_restore_drill.checked_settings()

    monkeypatch.setenv("PRINCESS_BACKEND_IMAGE", "princess-backend:" + "a" * 40)
    monkeypatch.setenv("PRINCESS_RECOVERY_WORKDIR", str(tmp_path / "wrong-name"))
    with pytest.raises(run_restore_drill.DrillFailure, match="dedicated princess-recovery"):
        run_restore_drill.checked_settings()


def test_ci_recovery_image_must_match_github_sha(monkeypatch, tmp_path):
    sha = "a" * 40
    monkeypatch.setenv("PRINCESS_RECOVERY_ALLOW_RESET", "1")
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("PRINCESS_BACKEND_IMAGE", "princess-backend:" + "b" * 40)
    monkeypatch.setenv("PRINCESS_RECOVERY_WORKDIR", str(tmp_path / "princess-recovery-ci"))
    with pytest.raises(run_restore_drill.DrillFailure, match="does not match GITHUB_SHA"):
        run_restore_drill.checked_settings()
