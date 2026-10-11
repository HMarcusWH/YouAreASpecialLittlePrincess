"""T18 deterministic pair/history comparison invariants and application boundary."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import generate_comparison_fixtures as comparison_fixtures
from princess_app.adapters.fakes import FakeClock
from princess_app.application.comparison import ComparisonService
from princess_app.application.reports import InMemoryReportStore
from princess_app.domain.comparison import (
    COMPARISON_METHOD_VERSION,
    assess_feature,
    build_comparison,
    candidate_feature_ids,
    native_delta,
)
from princess_app.domain.content import PRESENTATION_VERSION, display_domain, presentation_registry
from princess_app.domain.reports.assembly import build_notices, build_sections
from princess_app.ports.base import NotFound
from princess_contracts import canonical_digest, compile_document

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _report(name: str, at: datetime, *, owner: str = "owner_fixture_1",
            shift: float = 0.0, missing_candidates: bool = False):
    data = json.loads((ROOT / "fixtures/reports/report-document.v2.json").read_text(encoding="utf-8"))
    data["report_id"] = f"report_{name}"
    data["revision"] = 1
    data["created_at"] = at.isoformat().replace("+00:00", "Z")
    data["evidence_bundle_id"] = None
    data["reference_claims"] = []
    data["premium_overlay_id"] = None
    analysis = data["analysis"]
    analysis.update(
        analysis_id=f"analysis_{name}", run_id=f"run_{name}", owner_id=owner,
        input_asset_id=f"asset_{name}",
        input_sha256=_sha(f"input-{name}"), processed_sha256=_sha(f"processed-{name}"),
        created_at=data["created_at"],
    )
    candidates = set(candidate_feature_ids())
    for fact in data["facts"]:
        if fact["feature_id"] not in candidates:
            continue
        if missing_candidates:
            fact["availability"] = "MISSING"
            fact["value"] = None
            fact["quality"] = {
                "state": "MISSING", "missing_reason": "test",
                "n_observations": 0, "confidence": None, "confidence_kind": "UNCALIBRATED",
            }
        elif shift and type(fact["value"]) in {int, float}:
            domain = display_domain(fact["feature_id"])
            low, high = float(domain["min"]), float(domain["max"])
            step = (high - low) * shift
            value = float(fact["value"])
            next_value = value + step if value + step <= high else value - abs(step)
            fact["value"] = min(high, max(low, next_value))
    data["sections"] = build_sections(
        data["facts"], reference_claims=(), premium_overlay_id=None,
        template_version=data["analysis"]["versions"]["template"],
    )
    data["notices"] = build_notices(data["facts"], has_reference=False, premium_overlay_id=None)
    data["document_digest"] = None
    data["document_digest"] = canonical_digest(data)
    compiled = compile_document("ReportDocument", data)
    assert compiled.ok, compiled.issues[:5]
    return compiled.value


def _pair_rows(document):
    return {row["feature_id"]: row for row in document.data["differences"]}


def test_generated_comparison_fixtures_are_current():
    outputs = comparison_fixtures.build()
    stale = [path for path, content in outputs.items()
             if not path.is_file() or path.read_text(encoding="utf-8") != content]
    assert stale == []


def test_candidate_set_is_exactly_t08a_fixed_domains_not_every_numeric_fact():
    expected = tuple(sorted(presentation_registry()["display_domains"]))
    assert candidate_feature_ids() == expected
    assert len(expected) == 18
    assert "IMG_WIDTH_PX" not in expected
    assert "PAGE_WORD_COUNT" not in expected
    assert "X_HEIGHT_PX" not in expected


def test_pair_swap_preserves_absolute_delta_and_reverses_direction():
    a = _report("a", T0)
    b = _report("b", T0 + timedelta(hours=1), shift=0.1)
    ab = build_comparison(comparison_id="comparison_ab", kind="PAIR", reports=[a, b],
                          created_at=T0 + timedelta(hours=2))
    ba = build_comparison(comparison_id="comparison_ba", kind="PAIR", reports=[b, a],
                          created_at=T0 + timedelta(hours=2))
    assert ab.ok and ba.ok
    left, right = ab.value.data, ba.value.data
    assert left["method_version"] == right["method_version"] == COMPARISON_METHOD_VERSION
    assert left["presentation_version"] == right["presentation_version"] == PRESENTATION_VERSION
    assert left["coverage"] == right["coverage"]
    assert left["common_feature_ids"] == right["common_feature_ids"]
    ab_rows, ba_rows = _pair_rows(ab.value), _pair_rows(ba.value)
    reverse = {"FROM_GREATER": "TO_GREATER", "TO_GREATER": "FROM_GREATER", "EQUAL": "EQUAL"}
    for feature_id in left["common_feature_ids"]:
        x, y = ab_rows[feature_id], ba_rows[feature_id]
        assert x["signed_delta"] == -y["signed_delta"]
        assert x["absolute_delta"] == y["absolute_delta"]
        assert reverse[x["direction"]] == y["direction"]
        domain = display_domain(feature_id)
        expected_domain = {**domain, "accepted_min": domain.get("accepted_min"), "accepted_max": domain.get("accepted_max")}
        assert x["display_domain"] == y["display_domain"] == expected_domain


def test_equal_values_have_zero_native_delta_without_similarity_score():
    assert native_delta(0.0, 0.0) == (0.0, 0.0, "EQUAL")
    assert native_delta(-0.0, 0.0) == (0.0, 0.0, "EQUAL")
    a = _report("same_a", T0)
    b = _report("same_b", T0 + timedelta(hours=1))
    outcome = build_comparison(comparison_id="comparison_equal", kind="PAIR", reports=[a, b],
                               created_at=T0 + timedelta(hours=2))
    assert outcome.ok
    assert outcome.value.data["facts"] == ()
    assert all(row["signed_delta"] == 0 and row["absolute_delta"] == 0 and row["direction"] == "EQUAL"
               for row in outcome.value.data["differences"])
    serialized = json.dumps(outcome.value.to_dict()).lower()
    assert "cosine" not in serialized and "mahalanobis" not in serialized and "percent_change" not in serialized


def test_history_is_ordered_by_report_creation_and_uses_adjacent_edges_only():
    a = _report("hist_a", T0)
    b = _report("hist_b", T0 + timedelta(hours=1), shift=0.05)
    c = _report("hist_c", T0 + timedelta(hours=2), shift=-0.05)
    outcome = build_comparison(comparison_id="comparison_history", kind="HISTORY",
                               reports=[c, a, b], created_at=T0 + timedelta(hours=3))
    assert outcome.ok
    data = outcome.value.data
    assert data["ordering_basis"] == "REPORT_CREATED_AT"
    assert data["input_report_ids"] == ("report_hist_a", "report_hist_b", "report_hist_c")
    assert {(row["from_position"], row["to_position"]) for row in data["differences"]} == {(0, 1), (1, 2)}
    assert len(data["differences"]) == data["coverage"]["common_n"] * 2


def test_missing_inputs_are_excluded_not_imputed_and_zero_denominator_never_creates_percent_change():
    a = _report("present", T0)
    missing = _report("missing", T0 + timedelta(hours=1), missing_candidates=True)
    outcome = build_comparison(comparison_id="comparison_missing", kind="PAIR", reports=[a, missing],
                               created_at=T0 + timedelta(hours=2))
    assert outcome.ok
    data = outcome.value.data
    assert data["coverage"]["common_n"] == 0
    assert data["coverage"]["common_fraction"] == 0
    assert data["differences"] == ()
    assert len(data["exclusions"]) == data["coverage"]["candidate_n"]
    assert {row["reason"] for row in data["exclusions"]} == {"UNAVAILABLE"}

    signed, absolute, direction = native_delta(0.0, 1e-12)
    assert signed == 1e-12 and absolute == 1e-12 and direction == "TO_GREATER"


def test_policy_fails_closed_on_method_unit_and_availability_drift():
    report = _report("policy", T0)
    source = {fact["feature_id"]: fact for fact in report.to_dict()["facts"]}
    feature_id = "SLANT_ANGLE_MEAN"
    left = copy.deepcopy(source[feature_id])
    right = copy.deepcopy(left)

    right["method_version"] = "999.0"
    result = assess_feature(feature_id, [{feature_id: left}, {feature_id: right}])
    assert not result.comparable and result.reason == "METHOD_VERSION_MISMATCH"

    right = copy.deepcopy(left)
    right["unit"] = "ratio"
    result = assess_feature(feature_id, [{feature_id: left}, {feature_id: right}])
    assert not result.comparable and result.reason == "UNIT_MISMATCH"

    right = copy.deepcopy(left)
    right["availability"] = "MISSING"
    right["value"] = None
    result = assess_feature(feature_id, [{feature_id: left}, {feature_id: right}])
    assert not result.comparable and result.reason == "UNAVAILABLE"

    result = assess_feature(feature_id, [{feature_id: left}, {}])
    assert not result.comparable and result.reason == "ABSENT"


class _PartnerAccess:
    def allowed(self, *, principal_id: str, owner_id: str, report_id: str) -> bool:
        return principal_id == "owner_a" and owner_id == "owner_b" and report_id == "report_partner"


def test_application_service_is_same_owner_by_default_and_exposes_only_a_t22_partner_seam():
    store = InMemoryReportStore()
    a = _report("owner_a_1", T0, owner="owner_a")
    b = _report("owner_a_2", T0 + timedelta(hours=1), owner="owner_a", shift=0.05)
    partner = _report("partner", T0 + timedelta(hours=2), owner="owner_b", shift=-0.05)
    store.append("owner_a", a)
    store.append("owner_a", b)
    store.append("owner_b", partner)
    clock = FakeClock(T0 + timedelta(hours=3))

    service = ComparisonService(store, clock)
    result = service.create(comparison_id="comparison_owner", principal_id="owner_a",
                            report_ids=["report_owner_a_1", "report_owner_a_2"], kind="PAIR")
    assert result.schema_name == "Comparison"

    with pytest.raises(NotFound):
        service.create(comparison_id="comparison_denied", principal_id="owner_a",
                       report_ids=["report_owner_a_1", "report_partner"], kind="PAIR")

    partner_service = ComparisonService(store, clock, partner_access=_PartnerAccess())
    allowed = partner_service.create(comparison_id="comparison_partner_contract", principal_id="owner_a",
                                     report_ids=["report_owner_a_1", "report_partner"], kind="PAIR")
    assert allowed.schema_name == "Comparison"


def test_processing_config_mismatch_is_excluded_even_if_feature_method_matches():
    """Previously equal method IDs masked grid/segmentation policy changes."""
    a = _report("old_config", T0)
    b = _report("new_config", T0 + timedelta(hours=1))
    modified = b.to_dict()
    modified["analysis"]["versions"]["analysis_config"] = _sha("incompatible-new-preprocessing")
    modified["document_digest"] = None
    modified["document_digest"] = canonical_digest(modified)
    compiled = compile_document("ReportDocument", modified)
    assert compiled.ok, compiled.issues[:3]
    outcome = build_comparison(comparison_id="comparison_cross_config", kind="PAIR",
                               reports=[a, compiled.value], created_at=T0 + timedelta(hours=2))
    assert outcome.ok, outcome.issues[:3]
    data = outcome.value.data
    assert data["coverage"]["common_n"] == 0
    assert all(e["reason"] == "PROCESSING_CONFIG_MISMATCH" for e in data["exclusions"])
    assert data["differences"] == ()


def test_processing_config_unknown_does_not_become_comparable():
    feature_id = "SLANT_ANGLE_MEAN"
    report = _report("config_policy", T0)
    facts = {f["feature_id"]: f for f in report.to_dict()["facts"]}
    mapped = [{feature_id: facts[feature_id]}, {feature_id: facts[feature_id]}]
    match = assess_feature(feature_id, mapped, analysis_versions=[
        {"analysis_config": "a" * 64}, {"analysis_config": "a" * 64}])
    assert match.comparable
    unknown = assess_feature(feature_id, mapped, analysis_versions=[
        {"analysis_config": "a" * 64}, {}])
    assert unknown.reason == "PROCESSING_CONFIG_UNKNOWN"
