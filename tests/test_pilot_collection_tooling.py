"""T11 gated pilot metadata/split tooling."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evaluation.collection import pilot_tool as pilot

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "collection" / "fixtures"


def source():
    return pilot.load_json(FIXTURES / "source.synthetic.json")


def consent():
    return pilot.load_json(FIXTURES / "consent.synthetic.json")


def built():
    return pilot.build_manifest(
        source(), capture_root=FIXTURES, mode="synthetic", consent_log=consent(),
    )


def test_current_repository_gate_refuses_human_collection_and_has_no_force_path():
    issues = pilot.human_readiness_issues()
    assert "PILOT_GATE_NOT_APPROVED" in issues
    assert "PILOT_PROTOCOL_NOT_APPROVED" in issues
    with pytest.raises(pilot.PilotToolError, match="human pilot is disabled"):
        pilot.require_mode("human", synthetic=False)

    docs = pilot.load_policy_documents()
    docs["gate"]["status"] = "APPROVED"
    docs["gate"]["approval"] = {
        "decision_ref": "decision:not-enough",
        "decided_by_role": "owner",
        "decided_on": "2026-09-27T00:00:00Z",
        "content_sha256": "0" * 64,
    }
    # A cosmetic status flip does not decide the eleven rows or approve the protocol.
    mutated = pilot.human_readiness_issues(docs)
    assert "PILOT_GATE_NOT_READY" in mutated
    with pytest.raises(pilot.PilotToolError):
        pilot.require_mode("human", synthetic=False, documents=docs)


def test_manifest_builder_hashes_local_bytes_and_emits_no_paths_or_pii():
    manifest, eligible = built()
    assert eligible is not None
    assert (len(eligible.writer_ids), len(eligible.specimen_ids), len(eligible.capture_ids)) == (3, 4, 4)
    encoded = json.dumps(manifest, sort_keys=True)
    assert "source_path" not in encoded
    assert str(FIXTURES) not in encoded
    for forbidden in ("email", "full_name", "birth_date", "signed_agreement"):
        assert forbidden not in encoded.lower()

    source_by_capture = {row["capture_id"]: row for row in source()["captures"]}
    for capture in manifest["captures"]:
        path = FIXTURES / source_by_capture[capture["capture_id"]]["source_path"]
        assert capture["content_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_builder_rejects_unknown_personal_fields_path_escape_and_human_data_in_synthetic_mode(tmp_path):
    bad = source()
    bad["writers"][0]["email"] = "not-allowed@example.invalid"
    with pytest.raises(pilot.PilotToolError, match="forbidden"):
        pilot.build_manifest(bad, capture_root=FIXTURES, mode="synthetic", consent_log=consent())

    escaped = source()
    escaped["captures"][0]["source_path"] = "../outside.txt"
    with pytest.raises(pilot.PilotToolError, match="beneath capture_root"):
        pilot.build_manifest(escaped, capture_root=FIXTURES, mode="synthetic", consent_log=consent())

    human = source()
    human["synthetic"] = False
    with pytest.raises(pilot.PilotToolError, match="synthetic mode refuses"):
        pilot.build_manifest(human, capture_root=FIXTURES, mode="synthetic", consent_log=consent())

    if hasattr(Path, "symlink_to"):
        root = tmp_path / "captures"
        root.mkdir()
        target = tmp_path / "target.txt"
        target.write_text("synthetic", encoding="utf-8")
        link = root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            return
        symlinked = source()
        symlinked["captures"][0]["source_path"] = "link.txt"
        with pytest.raises(pilot.PilotToolError, match="symlinks"):
            pilot.build_manifest(symlinked, capture_root=root, mode="synthetic", consent_log=consent())


def test_opaque_ids_take_no_participant_attributes_and_determinism_is_fixture_only():
    a = pilot.new_opaque_id("writer", synthetic=True, seed="fixture-1")
    b = pilot.new_opaque_id("writer", synthetic=True, seed="fixture-1")
    assert a == b and a.startswith("wrt_") and "fixture-1" not in a
    assert pilot.new_opaque_id("writer") != pilot.new_opaque_id("writer")
    with pytest.raises(pilot.PilotToolError, match="synthetic-fixture-only"):
        pilot.new_opaque_id("writer", seed="person@example.invalid")


def test_writer_disjoint_split_keeps_every_specimen_and_capture_with_its_writer():
    manifest, eligible = built()
    plan = pilot.plan_writer_disjoint(manifest, eligible)
    assert pilot.validate_split_plan(plan, manifest, eligible) == ()
    assignments = {row["writer_id"]: row["split"] for row in plan["writers"]}
    assert set(assignments.values()) == {"development", "validation", "holdout"}

    for row in plan["specimens"]:
        assert row["split"] == assignments[row["writer_id"]]
    for row in plan["captures"]:
        assert row["split"] == assignments[row["writer_id"]]

    leaked = copy.deepcopy(plan)
    leaked["specimens"][0]["split"] = next(
        value for value in assignments.values()
        if value != leaked["specimens"][0]["split"]
    )
    assert "SPECIMEN_SPLIT_LEAKAGE" in pilot.validate_split_plan(leaked, manifest, eligible)


def test_annotation_worklist_and_summary_are_metadata_only_and_deterministic():
    manifest, eligible = built()
    first = pilot.plan_writer_disjoint(manifest, eligible)
    second = pilot.plan_writer_disjoint(manifest, eligible)
    assert first == second

    worklist = pilot.annotation_worklist(manifest, first, eligible)
    worklist_text = json.dumps(worklist, sort_keys=True)
    assert len(worklist["items"]) == 4
    assert "source_path" not in worklist_text
    assert "content_sha256" not in worklist_text
    assert all(item["asset_ref"].startswith("synthetic:cap_") for item in worklist["items"])
    assert all(item["status"] == "PENDING" for item in worklist["items"])

    summary = pilot.recruitment_summary(manifest, eligible)
    assert summary["writers"] == 3
    assert summary["writer_languages"] == {"en": 2, "sv": 1}
    assert summary["session_2_writers"] == 1
    assert summary["session_2_return_rate"] == pytest.approx(1 / 3)
    assert any("not population representativeness" in note for note in summary["limitations"])


def test_existing_synthetic_semantics_remain_authoritative():
    manifest, _eligible = built()
    duplicate = copy.deepcopy(manifest)
    duplicate["captures"][1]["content_sha256"] = duplicate["captures"][0]["content_sha256"]
    duplicate["claimed_counts"]["writers"] = 2
    duplicate["claimed_counts"]["specimens"] = 2
    duplicate["claimed_counts"]["captures"] = 2
    with pytest.raises(pilot.PilotToolError, match="DUPLICATE"):
        pilot.validate_synthetic_manifest(duplicate, consent())
