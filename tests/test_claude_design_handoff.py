"""T10 Claude Design handoff stays complete, curated and bound to explicit owner acceptance."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design"


def load(name: str):
    return json.loads((DESIGN / name).read_text(encoding="utf-8"))


V3_ARTIFACT = DESIGN / "artifacts" / "2026-10-04-v3" / "Inktrospect-mobile-design-v3.zip"
V3_SHA256 = "12253a30614b31b54d9585eec262956a49c06dad10a7070c1b71949d6f334f98"


def test_v3_implementation_reference_is_retained_byte_exact_and_inspectable():
    payload = V3_ARTIFACT.read_bytes()
    assert len(payload) == 377_913
    assert hashlib.sha256(payload).hexdigest() == V3_SHA256
    assert (V3_ARTIFACT.parent / "SHA256SUMS").read_text(encoding="utf-8") == (
        f"{V3_SHA256}  {V3_ARTIFACT.name}\n"
    )

    with zipfile.ZipFile(V3_ARTIFACT) as archive:
        names = archive.namelist()
        assert len(names) == 47
        assert {
            "Inktrospect App.dc.html",
            "Inktrospect Print and Share.dc.html",
            "README.md",
            "ios-frame.jsx",
            "android-frame.jsx",
            "_ds/inktrospect-design-system-60df8537-0b1f-478f-ab79-43e44e9176c6/"
            "_ds_manifest.json",
        } <= set(names)
        for name in names:
            path = Path(name)
            assert not path.is_absolute()
            assert ".." not in path.parts


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
    assert "content/presentation/" in excluded
    assert "contracts/product/v1/presentation-content.v1.json" in excluded
    assert not any(path.startswith("migrations/") for path in listed)
    assert not any(path.startswith("research/") for path in listed)
    assert "contracts/product/v1/presentation-content.v1.json" not in listed
    assert not any(path.startswith("content/presentation/") for path in listed)


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
    assert {"legacy_v1_without_highlight", "server_owned_highlight_available", "no_eligible_highlight", "source_image_not_retained"} == screens["first_reveal"]
    assert matrix["planned_owners"]["first_reveal"] == ["T17"]
    assert {
        "comparison_pair_available", "comparison_history_available", "insufficient_common_coverage",
        "planned_invitation_sent", "planned_invitation_accepted",
        "planned_invitation_declined", "planned_invitation_revoked",
    } == screens["pair_invitation_comparison"]
    assert matrix["planned_owners"]["pair_invitation_comparison"] == ["T22"]

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


def test_t18_comparison_handoff_uses_real_fixtures_but_keeps_t22_invitation_planned():
    manifest = load("claude-design-import.json")
    matrix = load("claude-design-state-matrix.json")
    fixtures = set(manifest["synthetic_fixtures"])
    assert {
        "fixtures/comparisons/pair-ab.json",
        "fixtures/comparisons/history.json",
        "fixtures/comparisons/no-overlap.json",
    } <= fixtures
    mapping = matrix["required_fixture_mapping"]
    assert mapping["comparison_pair"] == "fixtures/comparisons/pair-ab.json"
    assert mapping["comparison_history"] == "fixtures/comparisons/history.json"
    assert mapping["comparison_no_overlap"] == "fixtures/comparisons/no-overlap.json"
    assert matrix["planned_owners"]["pair_invitation_comparison"] == ["T22"]


def test_handoff_baseline_is_consistent_and_client_presentation_surface_stays_stripped():
    manifest = load("claude-design-import.json")
    acceptance = (DESIGN / "CLAUDE_DESIGN_ACCEPTANCE.md").read_text(encoding="utf-8")
    baseline = manifest["source_baseline_sha"]
    assert len(baseline) == 40 and all(char in "0123456789abcdef" for char in baseline)
    assert f"`{baseline}`" in acceptance
    assert baseline == "53bcb9743eeb7fa96fc9affb68fc949c30fd25c0"

    client_surface = (ROOT / "packages/report-core/src/presentation.generated.ts").read_text(encoding="utf-8")
    assert "content.highlight.v1.slant.right.almost_all" in client_surface
    assert "GEOMETRIC_CANVAS" in client_surface
    for server_only in ("candidate_id", '"clauses"', '"strength"', '"family_order"'):
        assert server_only not in client_surface


def test_handoff_records_explicit_owner_acceptance_and_accepted_tokens():
    tokens = json.loads((ROOT / "packages/design-tokens/tokens.json").read_text(encoding="utf-8"))
    acceptance = (DESIGN / "CLAUDE_DESIGN_ACCEPTANCE.md").read_text(encoding="utf-8")
    accepted = (DESIGN / "ACCEPTED_DOSSIER_REFERENCE.md").read_text(encoding="utf-8")
    handoff = (DESIGN / "CLAUDE_DESIGN_HANDOFF.md").read_text(encoding="utf-8")

    assert tokens["status"] == "ACCEPTED"
    assert tokens["version"] == "design-tokens/1.0"
    assert "**Status: ACCEPTED_WITH_CHANGES**" in acceptance
    assert "Decision: **ACCEPTED_WITH_CHANGES**" in acceptance
    assert "Inktrospect mobile app design (2).zip" in acceptance
    assert "89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5" in acceptance
    assert "89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5" in accepted
    assert "Direction A — The Dossier" in handoff
    assert "owner accepted with changes" in handoff
    assert "Synthetic data only" in handoff
