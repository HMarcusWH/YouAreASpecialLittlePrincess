"""T10 Claude Design handoff stays complete, curated and non-self-approving."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design"


def load(name: str):
    return json.loads((DESIGN / name).read_text(encoding="utf-8"))


def test_claude_design_import_paths_exist_and_exclude_irrelevant_private_surfaces():
    manifest = load("claude-design-import.json")
    assert manifest["contract_version"] == "claude-design-import/v1"
    path_groups = (
        "read_first", "product_and_security_context", "framework_context", "design_system",
        "semantic_contracts", "synthetic_fixtures", "existing_web_implementation",
        "rendering_context", "native_design_context",
    )
    listed = []
    for group in path_groups:
        for relative in manifest[group]:
            listed.append(relative)
            assert (ROOT / relative.rstrip("/")).exists(), f"missing Claude Design input: {relative}"

    assert len(listed) == len(set(listed)) or set(manifest["read_first"]) <= set(listed)
    excluded = set(manifest["do_not_import_by_default"])
    assert "migrations/" in excluded
    assert "research/" in excluded
    assert "src/princess_app/adapters/openai/" in excluded
    assert not any(path.startswith("migrations/") for path in listed)
    assert not any(path.startswith("research/") for path in listed)


def test_state_matrix_covers_t10_required_design_acceptance_surface():
    matrix = load("claude-design-state-matrix.json")
    screens = {row["id"]: set(row["states"]) for row in matrix["screens"]}
    required_screens = {
        "landing", "permission_upload", "crop_orientation_preview", "processing", "first_reveal", "free_report",
        "premium_offer_consent", "purchase", "premium_generation", "premium_report",
        "pair_invitation_comparison", "history", "share_preview_revocation", "export_preview", "settings",
    }
    assert set(screens) == required_screens

    assert {"pending", "ask_to_buy", "cancelled", "failed", "restored", "account_mismatch"} <= screens["purchase"]
    assert {"refused", "failed_credit_released", "not_applicable_no_authorized_image"} <= screens["premium_generation"]
    assert {"partial_missing", "uncalibrated", "reference_unavailable", "image_revoked"} <= screens["free_report"]
    assert {"prototype_illustrative_selection", "server_owned_highlight_available", "no_eligible_highlight", "source_image_not_retained"} == screens["first_reveal"]
    assert matrix["planned_owners"]["first_reveal"] == ["T17"]

    assert set(matrix["availability_states"]) == {
        "READY", "UNCALIBRATED", "MISSING", "NOT_IMPLEMENTED", "INELIGIBLE",
        "LOCKED", "PENDING", "FAILED", "REVOKED",
    }
    assert set(matrix["evidence_classes"]) == {
        "MEASURED", "COMPUTATIONAL_PROXY", "REFERENCE_STATISTIC",
        "AUTHORED_CONTENT", "TRADITIONAL_ASSOCIATION", "AI_SYNTHESIS",
    }
    assert {"web_320", "ios_phone", "ipad", "android_phone", "android_tablet", "print_a4", "print_letter"} <= set(matrix["platforms"])
    assert matrix["review_controls"]["narrow_width_px"] == 320
    assert 200 in matrix["review_controls"]["text_scale_percent"]
    assert "Bokstavsavståndsvariation" in matrix["overflow_torture_strings"]
    assert "Tredjepartsbehandling av bilden" in matrix["overflow_torture_strings"]


def test_every_required_fixture_mapping_points_to_checked_in_synthetic_fixture():
    matrix = load("claude-design-state-matrix.json")
    for relative in matrix["required_fixture_mapping"].values():
        path = ROOT / relative
        assert path.exists()
        if path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(value, dict)


def test_handoff_does_not_self_approve_design_or_tokens():
    tokens = json.loads((ROOT / "packages/design-tokens/tokens.json").read_text(encoding="utf-8"))
    acceptance = (DESIGN / "CLAUDE_DESIGN_ACCEPTANCE.md").read_text(encoding="utf-8")
    handoff = (DESIGN / "CLAUDE_DESIGN_HANDOFF.md").read_text(encoding="utf-8")

    assert tokens["status"] == "DRAFT_PENDING_DESIGN_ACCEPTANCE"
    assert tokens["version"] == "design-tokens/0.1-draft"
    assert "**Status: PENDING_OWNER_REVIEW**" in acceptance
    assert "Decision: **PENDING**" in acceptance
    assert "Direction A — The Dossier" in handoff
    assert "Do **not** restart visual-direction exploration" in handoff
    assert "Design direction selected: **A — The Dossier**" in acceptance
    assert "Synthetic data only" in handoff
    assert "Only after explicit owner acceptance" in handoff
