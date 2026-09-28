"""T01 product contracts: one authoritative validation path, no raw-object bypass."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import princess_contracts.runtime as runtime
from princess_contracts import compile_document, parse_json, validate_premium_output, validate_projection

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "contracts" / "product" / "v1" / "fixtures"
INDEX = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))


def load(rel: str):
    return parse_json((FIXTURES / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", INDEX["valid"], ids=lambda c: c["schema"])
def test_valid_fixture_compiles_to_immutable_document(case):
    result = compile_document(case["schema"], load(case["path"]))
    assert result.ok and result.value is not None and result.issues == ()
    assert result.value.schema_name == case["schema"]
    assert len(result.value.digest) == 64
    with pytest.raises(TypeError):
        result.value.data["contract_version"] = "evil"


@pytest.mark.parametrize("case", INDEX["invalid"], ids=lambda c: c["expected_code"])
def test_invalid_fixture_fails_closed_with_expected_reason(case):
    result = compile_document(case["schema"], load(case["path"]))
    assert result.value is None
    assert case["expected_code"] in {issue.code for issue in result.issues}


@pytest.mark.parametrize("case", INDEX["raw_invalid"], ids=lambda c: c["path"])
def test_noncanonical_json_cannot_enter_contract_pipeline(case):
    with pytest.raises(ValueError, match=case["expected"]):
        parse_json((FIXTURES / case["path"]).read_text(encoding="utf-8"))


def test_unknown_root_schema_returns_no_value():
    result = compile_document("MadeUpThing", {})
    assert result.value is None and result.issues[0].code == "UNKNOWN_SCHEMA"


def test_canonical_digest_is_key_order_independent_but_array_order_sensitive():
    a = {"b": 1, "a": [1, 2]}
    b = {"a": [1, 2], "b": 1}
    c = {"a": [2, 1], "b": 1}
    assert runtime.canonical_digest(a) == runtime.canonical_digest(b)
    assert runtime.canonical_digest(a) != runtime.canonical_digest(c)


def test_bool_is_not_a_number_even_though_python_bool_is_int_subclass():
    doc = load("valid/report-document.json")
    doc["facts"][0]["value"] = True
    doc["document_digest"] = None
    result = compile_document("ReportDocument", doc)
    assert result.value is None and "FEATURE_VALUE_TYPE" in {i.code for i in result.issues}


def test_missing_is_not_zero_and_locked_content_cannot_hide_a_value():
    for state in ("MISSING", "NOT_IMPLEMENTED", "INELIGIBLE", "LOCKED", "PENDING", "FAILED", "REVOKED"):
        doc = load("valid/report-document.json")
        fact = doc["facts"][0]
        fact["availability"] = state
        fact["value"] = 0.0
        if state == "MISSING":
            fact["quality"] = {"state":"MISSING","missing_reason":"test","n_observations":0,"confidence":None,"confidence_kind":"UNCALIBRATED"}
        doc["document_digest"] = None
        result = compile_document("ReportDocument", doc)
        assert result.value is None and "UNAVAILABLE_HAS_VALUE" in {i.code for i in result.issues}


def test_fact_cannot_turn_ai_or_traditional_prose_into_canonical_measurement():
    for evidence_class in ("AI_SYNTHESIS", "TRADITIONAL_ASSOCIATION", "AUTHORED_CONTENT"):
        doc = load("valid/report-document.json")
        doc["facts"][0]["evidence_class"] = evidence_class
        doc["document_digest"] = None
        result = compile_document("ReportDocument", doc)
        assert result.value is None and "NONFACT_EVIDENCE_CLASS" in {i.code for i in result.issues}


def test_self_digest_binds_report_and_comparison_content():
    for schema, rel, field in (
        ("ReportDocument", "valid/report-document.json", "document_digest"),
        ("Comparison", "valid/comparison.json", "comparison_digest"),
    ):
        doc = load(rel)
        original = doc[field]
        assert compile_document(schema, doc).ok
        doc["created_at"] = "2026-09-26T21:00:00Z"
        assert doc[field] == original
        result = compile_document(schema, doc)
        assert result.value is None and "SELF_DIGEST_MISMATCH" in {i.code for i in result.issues}


def test_duplicate_canonical_ids_are_never_resolved_by_array_order():
    cases = [
        ("EvidenceBundle", "valid/evidence-bundle.json", "frames", "frame_id", "DUPLICATE_FRAME"),
        ("EvidenceBundle", "valid/evidence-bundle.json", "regions", "region_id", "DUPLICATE_REGION"),
        ("EvidenceBundle", "valid/evidence-bundle.json", "observations", "observation_id", "DUPLICATE_OBSERVATION"),
        ("ReportDocument", "valid/report-document.json", "facts", "fact_id", "DUPLICATE_FACT"),
        ("ReportDocument", "valid/report-document.json", "sections", "section_id", "DUPLICATE_SECTION"),
        ("ReportViewModel", "valid/report-view-model.json", "sections", "section_id", "DUPLICATE_SECTION"),
        ("ReportViewModel", "valid/report-view-model.json", "notices", "notice_id", "DUPLICATE_NOTICE"),
        ("PremiumPacket", "valid/premium-packet.json", "questions", "question_id", "DUPLICATE_QUESTION"),
        ("PremiumPacket", "valid/premium-packet.json", "candidates", "candidate_id", "DUPLICATE_CANDIDATE"),
    ]
    for schema, rel, collection, key, code in cases:
        doc = load(rel)
        duplicate = copy.deepcopy(doc[collection][0])
        doc[collection].append(duplicate)
        if schema == "ReportDocument":
            doc["document_digest"] = None
        result = compile_document(schema, doc)
        assert result.value is None and code in {i.code for i in result.issues}, (schema, collection, result.issues)
        doc[collection].reverse()
        result = compile_document(schema, doc)
        assert result.value is None and code in {i.code for i in result.issues}


def test_comparison_contract_rejects_derived_field_and_coverage_drift():
    base = load("valid/comparison.json")
    assert compile_document("Comparison", base).ok

    wrong_delta = copy.deepcopy(base)
    wrong_delta["differences"][0]["signed_delta"] += 1
    wrong_delta["comparison_digest"] = None
    wrong_delta["comparison_digest"] = runtime.canonical_digest(wrong_delta)
    result = compile_document("Comparison", wrong_delta)
    assert result.value is None and "SIGNED_DELTA_DRIFT" in {i.code for i in result.issues}

    wrong_direction = copy.deepcopy(base)
    wrong_direction["differences"][0]["direction"] = "EQUAL"
    wrong_direction["comparison_digest"] = None
    wrong_direction["comparison_digest"] = runtime.canonical_digest(wrong_direction)
    result = compile_document("Comparison", wrong_direction)
    assert result.value is None and "DIRECTION_DRIFT" in {i.code for i in result.issues}

    wrong_coverage = copy.deepcopy(base)
    wrong_coverage["coverage"]["common_n"] -= 1
    wrong_coverage["comparison_digest"] = None
    wrong_coverage["comparison_digest"] = runtime.canonical_digest(wrong_coverage)
    result = compile_document("Comparison", wrong_coverage)
    assert result.value is None and "COVERAGE_COMMON_COUNT" in {i.code for i in result.issues}

    wrong_input = copy.deepcopy(base)
    wrong_input["input_report_ids"].reverse()
    wrong_input["comparison_digest"] = None
    wrong_input["comparison_digest"] = runtime.canonical_digest(wrong_input)
    result = compile_document("Comparison", wrong_input)
    assert result.value is None and "COMPARISON_INPUT_ID_DRIFT" in {i.code for i in result.issues}


def test_evidence_coordinate_graph_rejects_cycles_missing_parents_and_bounds():
    base = load("valid/evidence-bundle.json")
    child = {"frame_id":"frame_child","width":60,"height":40,"unit":"px","parent_frame_id":"frame_original","transform_to_parent":[1,0,0,0,1,0,0,0,1]}
    base["frames"].append(child)
    assert compile_document("EvidenceBundle", base).ok

    cycle = copy.deepcopy(base)
    cycle["frames"][0]["parent_frame_id"] = "frame_child"
    cycle["frames"][0]["transform_to_parent"] = [1,0,0,0,1,0,0,0,1]
    result = compile_document("EvidenceBundle", cycle)
    assert result.value is None and "FRAME_CYCLE" in {i.code for i in result.issues}

    missing = copy.deepcopy(base)
    missing["frames"][1]["parent_frame_id"] = "missing"
    result = compile_document("EvidenceBundle", missing)
    assert result.value is None and "MISSING_FRAME_PARENT" in {i.code for i in result.issues}

    bounds = copy.deepcopy(base)
    bounds["regions"][0]["width"] = 121
    result = compile_document("EvidenceBundle", bounds)
    assert result.value is None and "REGION_OUT_OF_BOUNDS" in {i.code for i in result.issues}


def test_projection_is_exact_subset_not_second_report_engine():
    report = compile_document("ReportDocument", load("valid/report-document.json")).value
    view_data = load("valid/report-view-model.json")
    view = compile_document("ReportViewModel", view_data).value
    assert report is not None and view is not None and not validate_projection(report, view)

    mutated = copy.deepcopy(view_data)
    mutated["facts"][0]["value"] = 999.0
    compiled = compile_document("ReportViewModel", mutated)
    assert compiled.ok and compiled.value is not None  # structurally valid in isolation
    issues = validate_projection(report, compiled.value)
    assert "PROJECTION_FACT_MUTATION" in {i.code for i in issues}

    wrong_report = copy.deepcopy(view_data)
    wrong_report["source_report_id"] = "report_other"
    compiled = compile_document("ReportViewModel", wrong_report)
    assert compiled.ok and compiled.value is not None
    assert "PROJECTION_REPORT_MISMATCH" in {i.code for i in validate_projection(report, compiled.value)}


def test_free_projection_cannot_include_premium_section():
    report_data = load("valid/report-document.json")
    report_data["sections"][0]["premium_section_id"] = "premium_section_1"
    report_data["document_digest"] = None
    report_data["document_digest"] = runtime.canonical_digest(report_data)
    report = compile_document("ReportDocument", report_data).value
    view_data = load("valid/report-view-model.json")
    view_data["sections"][0]["premium_section_id"] = "premium_section_1"
    view_data["source_digest"] = report_data["document_digest"]
    view = compile_document("ReportViewModel", view_data).value
    assert report is not None and view is not None
    assert "FREE_PREMIUM_LEAK" in {i.code for i in validate_projection(report, view)}


def test_premium_packet_is_frozen_to_t26_pack_selector_and_fact_boundary():
    packet = load("valid/premium-packet.json")
    assert compile_document("PremiumPacket", packet).ok
    mutations = [
        (lambda p: p.update(interpretation_database_sha256="f"*64), "T26_DIGEST_DRIFT"),
        (lambda p: p.update(question_pack_id="UNKNOWN_PACK"), "UNKNOWN_QUESTION_PACK"),
        (lambda p: p["questions"][0].update(selection_domain="DYNAMIC"), "SELECTION_DOMAIN_DRIFT"),
        (lambda p: p["questions"][0]["support_fact_ids"].append("not_allowed"), "QUESTION_SUPPORT_OUTSIDE_FACTS"),
        (lambda p: p["candidates"][0]["support_fact_ids"].append("not_allowed"), "CANDIDATE_SUPPORT_OUTSIDE_FACTS"),
        (lambda p: p["questions"][0]["candidate_ids"].append("not_frozen"), "UNKNOWN_QUESTION_CANDIDATE"),
    ]
    for mutate, code in mutations:
        changed = copy.deepcopy(packet)
        mutate(changed)
        result = compile_document("PremiumPacket", changed)
        assert result.value is None and code in {i.code for i in result.issues}, (code, result.issues)


def test_premium_output_cannot_escape_packet_question_candidate_or_support_sets():
    packet = compile_document("PremiumPacket", load("valid/premium-packet.json")).value
    good_data = load("valid/premium-output.json")
    good = compile_document("PremiumOutput", good_data).value
    assert packet is not None and good is not None and not validate_premium_output(packet, good)

    mutations = [
        (lambda o: o.update(packet_id="packet_other"), "OUTPUT_PACKET_MISMATCH"),
        (lambda o: o["answers"][0].update(question_id="Q_GLOBAL_FORM_MOVEMENT"), "UNKNOWN_OUTPUT_QUESTION"),
        (lambda o: o["answers"][0]["selected_candidate_ids"].append("candidate_escape"), "OUTPUT_CANDIDATE_ESCAPE"),
        (lambda o: o["answers"][0]["support_fact_ids"].append("fact_escape"), "OUTPUT_SUPPORT_ESCAPE"),
        (lambda o: o["answers"][0].update(answer_state="NOT_ASSESSABLE"), "NONANSWERED_SELECTION"),
    ]
    for mutate, code in mutations:
        changed = copy.deepcopy(good_data)
        mutate(changed)
        compiled = compile_document("PremiumOutput", changed)
        assert compiled.ok and compiled.value is not None, compiled.issues
        issues = validate_premium_output(packet, compiled.value)
        assert code in {i.code for i in issues}, (code, issues)


def test_single_cardinality_is_enforced_at_output_not_reinvented_by_client():
    packet_data = load("valid/premium-packet.json")
    second = copy.deepcopy(packet_data["candidates"][0])
    second["candidate_id"] = "candidate_task_free"
    packet_data["candidates"].append(second)
    packet_data["questions"][0]["candidate_ids"].append("candidate_task_free")
    packet = compile_document("PremiumPacket", packet_data).value
    output_data = load("valid/premium-output.json")
    output_data["answers"][0]["selected_candidate_ids"] = ["candidate_task_copy", "candidate_task_free"]
    output = compile_document("PremiumOutput", output_data).value
    assert packet is not None and output is not None
    assert "OUTPUT_CARDINALITY" in {i.code for i in validate_premium_output(packet, output)}


def test_grant_snapshots_reference_t03_purpose_versions_and_cannot_backdate():
    good = load("valid/grant-snapshot.json")
    assert compile_document("GrantSnapshot", good).ok
    bad = copy.deepcopy(good)
    bad["purpose_id"] = "made_up_permission"
    result = compile_document("GrantSnapshot", bad)
    assert result.value is None and "UNKNOWN_PURPOSE_VERSION" in {i.code for i in result.issues}
    bad = copy.deepcopy(good)
    bad["effective_at"] = "2026-09-26T19:58:59Z"
    result = compile_document("GrantSnapshot", bad)
    assert result.value is None and "GRANT_BACKDATING" in {i.code for i in result.issues}



def test_product_fact_quality_preserves_measurement_count_and_confidence_semantics():
    base = load("valid/report-document.json")

    no_observations = copy.deepcopy(base)
    no_observations["facts"][0]["quality"]["n_observations"] = 0
    no_observations["document_digest"] = None
    result = compile_document("ReportDocument", no_observations)
    assert result.value is None and "PRESENT_WITHOUT_OBSERVATIONS" in {i.code for i in result.issues}

    uncalibrated_number = copy.deepcopy(base)
    uncalibrated_number["facts"][0]["quality"]["confidence_kind"] = "UNCALIBRATED"
    uncalibrated_number["document_digest"] = None
    result = compile_document("ReportDocument", uncalibrated_number)
    assert result.value is None and "CONFIDENCE_KIND_MISMATCH" in {i.code for i in result.issues}

    calibrated_null = copy.deepcopy(base)
    calibrated_null["facts"][0]["quality"]["confidence"] = None
    calibrated_null["document_digest"] = None
    result = compile_document("ReportDocument", calibrated_null)
    assert result.value is None and "CONFIDENCE_KIND_MISMATCH" in {i.code for i in result.issues}


def test_region_hierarchy_is_same_frame_and_spatially_contained():
    base = load("valid/evidence-bundle.json")
    child = copy.deepcopy(base["regions"][0])
    child.update(region_id="word_0", scope="WORD", x=10, y=10, width=20, height=10, parent_region_id="page_0")
    base["regions"].append(child)
    assert compile_document("EvidenceBundle", base).ok

    outside = copy.deepcopy(base)
    outside["regions"][1].update(x=119, width=2)
    result = compile_document("EvidenceBundle", outside)
    assert result.value is None and "REGION_OUTSIDE_PARENT" in {i.code for i in result.issues}

    cross_frame = copy.deepcopy(base)
    cross_frame["frames"].append({
        "frame_id":"frame_child", "width":120, "height":80, "unit":"px",
        "parent_frame_id":"frame_original", "transform_to_parent":[1,0,0,0,1,0,0,0,1],
    })
    cross_frame["regions"][1]["frame_id"] = "frame_child"
    result = compile_document("EvidenceBundle", cross_frame)
    assert result.value is None and "REGION_PARENT_FRAME_MISMATCH" in {i.code for i in result.issues}


def test_reference_claims_bind_one_available_fact_and_the_analysis_release():
    base = load("valid/report-document.json")
    base["analysis"]["versions"]["benchmark_release"] = "benchmark_001"
    claim = {
        "feature_id":"IMG_WIDTH_PX", "cohort_id":"cohort_001", "benchmark_release_id":"benchmark_001",
        "writer_n":100, "percentile":42.0, "uncertainty":None, "methodology_key":"reference.ecdf.v1",
    }
    base["reference_claims"] = [claim]
    base["document_digest"] = None
    assert compile_document("ReportDocument", base).ok

    duplicate = copy.deepcopy(base)
    duplicate["reference_claims"].append(copy.deepcopy(claim))
    result = compile_document("ReportDocument", duplicate)
    assert result.value is None and "DUPLICATE_REFERENCE_CLAIM" in {i.code for i in result.issues}

    wrong_release = copy.deepcopy(base)
    wrong_release["reference_claims"][0]["benchmark_release_id"] = "benchmark_other"
    result = compile_document("ReportDocument", wrong_release)
    assert result.value is None and "REFERENCE_RELEASE_MISMATCH" in {i.code for i in result.issues}

    unavailable = copy.deepcopy(base)
    unavailable["facts"][0].update(availability="MISSING", value=None)
    unavailable["facts"][0]["quality"] = {
        "state":"MISSING", "missing_reason":"not measured", "n_observations":0,
        "confidence":None, "confidence_kind":"UNCALIBRATED",
    }
    result = compile_document("ReportDocument", unavailable)
    assert result.value is None and "REFERENCE_FACT_UNAVAILABLE" in {i.code for i in result.issues}


def test_view_model_identity_sets_and_action_state_fail_closed():
    view = load("valid/report-view-model.json")
    duplicate_section = copy.deepcopy(view)
    duplicate_section["sections"].append(copy.deepcopy(view["sections"][0]))
    assert "DUPLICATE_SECTION" in {i.code for i in compile_document("ReportViewModel", duplicate_section).issues}

    duplicate_notice = copy.deepcopy(view)
    duplicate_notice["notices"].append(copy.deepcopy(view["notices"][0]))
    assert "DUPLICATE_NOTICE" in {i.code for i in compile_document("ReportViewModel", duplicate_notice).issues}

    enabled_reason = copy.deepcopy(view)
    enabled_reason["actions"][0]["reason"] = "should not be here"
    assert "ENABLED_ACTION_REASON" in {i.code for i in compile_document("ReportViewModel", enabled_reason).issues}

    disabled_no_reason = copy.deepcopy(view)
    disabled_no_reason["actions"][0].update(enabled=False, reason=None)
    assert "DISABLED_ACTION_WITHOUT_REASON" in {i.code for i in compile_document("ReportViewModel", disabled_no_reason).issues}


def test_premium_packet_freezes_soft_field_allowlist_from_selected_t26_pack():
    packet = load("valid/premium-packet.json")
    assert compile_document("PremiumPacket", packet).ok
    for changed_ids in ([], ["SOFT_GRAPHIC_PORTRAIT"], [*packet["soft_field_ids"], "SOFT_TRADITIONAL_SYNTHESIS"]):
        changed = copy.deepcopy(packet)
        changed["soft_field_ids"] = changed_ids
        result = compile_document("PremiumPacket", changed)
        assert result.value is None and "SOFT_FIELD_SET_DRIFT" in {i.code for i in result.issues}


def test_premium_output_is_complete_and_soft_fields_cannot_escape_packet_or_t26_bounds():
    packet = compile_document("PremiumPacket", load("valid/premium-packet.json")).value
    assert packet is not None

    missing_answer_data = load("valid/premium-output.json")
    missing_answer_data["answers"] = []
    missing_answer = compile_document("PremiumOutput", missing_answer_data).value
    assert missing_answer is not None
    assert "OUTPUT_QUESTION_SET_MISMATCH" in {i.code for i in validate_premium_output(packet, missing_answer)}

    escaped_data = load("valid/premium-output.json")
    escaped_data["soft_fields"] = [{
        "field_id":"SOFT_TRADITIONAL_SYNTHESIS", "text":"bounded text", "support_fact_ids":["fact_img_width"],
    }]
    escaped = compile_document("PremiumOutput", escaped_data).value
    assert escaped is not None
    assert "SOFT_FIELD_ESCAPE" in {i.code for i in validate_premium_output(packet, escaped)}

    long_data = load("valid/premium-output.json")
    long_data["soft_fields"] = [{
        "field_id":"SOFT_GRAPHIC_PORTRAIT", "text":"x" * 501, "support_fact_ids":["fact_img_width"],
    }]
    long_output = compile_document("PremiumOutput", long_data).value
    assert long_output is not None
    assert "SOFT_FIELD_TOO_LONG" in {i.code for i in validate_premium_output(packet, long_output)}


def test_negative_zero_is_canonicalized_so_digests_survive_storage_round_trips():
    from princess_contracts import canonical_digest, canonical_json

    assert canonical_json({"a": -0.0, "b": [-0.0, 1.5]}) == '{"a":0.0,"b":[0.0,1.5]}'
    assert canonical_digest({"v": -0.0}) == canonical_digest({"v": 0.0})
    assert canonical_json({"v": -1e-9}) == '{"v":-1e-09}'  # only exact zero is affected
