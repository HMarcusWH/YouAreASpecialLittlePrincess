from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build_runtime_release import build_manifest, load_json
from check_release_compatibility import CompatibilityError, compare_manifests, receipt

ROOT = Path(__file__).resolve().parents[1]
POLICY = load_json(ROOT / "infra" / "release" / "release-policy.json")


def current_manifest() -> dict:
    return build_manifest(ROOT, "0" * 40, POLICY)


def base_from(candidate: dict) -> dict:
    base = copy.deepcopy(candidate)
    base["source_sha"] = "1" * 40
    return base


def test_runtime_release_matches_current_repo_authorities():
    manifest = current_manifest()
    assert manifest["database"]["head_revision"] == "0011_operational_snapshot"
    assert manifest["product_contract"]["version"] == "1.0.0"
    assert manifest["engine"]["version"] == "0.1.0"
    assert manifest["measurement"]["feature_schema_version"] == "1.0.0-draft"
    assert manifest["interpretation"]["version"] == "premium-interpretation-db/1"
    assert manifest["reports"] == {
        "write_template":"individual-report/2",
        "read_templates":["individual-report/1","individual-report/2"],
        "presentation":"presentation/1",
        "highlight_policy":"highlight-policy/1",
        "render_template":"render-template/2",
    }
    routes = manifest["api"]["public_v1_routes"]
    assert "GET /v1/me" in routes and "DELETE /v1/me" in routes
    assert "GET /v1/reports/{report_id}/premium" in routes
    assert "POST /v1/reports/{report_id}/premium" in routes
    assert not any("/v1/dev/" in route or "/health/" in route for route in routes)


def test_current_manifest_is_self_compatible_and_static_receipt_is_honest():
    candidate = current_manifest()
    base = base_from(candidate)
    assert all(compare_manifests(base, candidate, POLICY).values())
    document = receipt(base, candidate, POLICY, event_kind="PREMERGE", candidate_head_sha="2" * 40)
    assert document["result"] == "STATIC_PASS"
    assert document["database_downgrade_performed"] is False
    assert document["queue_state_requirement"] == "DRAINED_OR_FENCED"


def test_incompatible_contract_major_is_rejected():
    candidate = current_manifest()
    base = base_from(candidate)
    candidate["product_contract"]["version"] = "2.0.0"
    with pytest.raises(CompatibilityError, match="product contract major changed"):
        compare_manifests(base, candidate, POLICY)


def test_removed_method_route_is_rejected():
    candidate = current_manifest()
    base = base_from(candidate)
    candidate["api"]["public_v1_routes"].remove("GET /v1/me")
    with pytest.raises(CompatibilityError, match=r"removed public method\+route"):
        compare_manifests(base, candidate, POLICY)


def test_candidate_must_read_base_report_writer():
    candidate = current_manifest()
    base = base_from(candidate)
    candidate["reports"]["read_templates"] = ["individual-report/1"]
    with pytest.raises(CompatibilityError, match="cannot read base report template"):
        compare_manifests(base, candidate, POLICY)


def test_base_must_read_candidate_report_writer():
    candidate = current_manifest()
    base = base_from(candidate)
    candidate["reports"]["write_template"] = "individual-report/3"
    candidate["reports"]["read_templates"].append("individual-report/3")
    with pytest.raises(CompatibilityError, match="rollback base cannot read candidate report template"):
        compare_manifests(base, candidate, POLICY)


def test_release_contract_json_is_well_formed_and_no_deployment_downgrade_path_exists():
    for path in (
        ROOT / "infra/release/runtime-release.schema.json",
        ROOT / "infra/release/release-policy.schema.json",
        ROOT / "infra/release/release-policy.json",
        ROOT / "infra/release/compatibility-witnesses.json",
        ROOT / "infra/release/rollout-qualification.schema.json",
    ):
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    assert POLICY["database_downgrade_on_application_rollback"] is False
    sources = [
        ROOT / "tools/build_runtime_release.py",
        ROOT / "tools/check_release_compatibility.py",
        ROOT / "infra/release/free_rollback_smoke.py",
        ROOT / ".github/workflows/release-compat.yml",
    ]
    assert all("alembic downgrade" not in path.read_text(encoding="utf-8").lower() for path in sources)
