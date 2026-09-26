"""Regression tests for the T03 consent, retention, source-rights and collection drafts."""

import copy
import itertools
import json
import shutil

import pytest

import validate_consent_protocol as vcp

SCENARIOS = sorted((vcp.CONSENT_DIR / "fixtures" / "scenarios").glob("*.json"))
COLLECTIONS = sorted((vcp.CONSENT_DIR / "fixtures" / "collection").glob("*.json"))


def load(name):
    return vcp.load_json(vcp.CONSENT_DIR / name)


def purposes_by_key(registry):
    return {vcp.purpose_key(p): p for p in registry["purposes"]}


def codes(issues):
    return sorted({issue.code for issue in issues})


@pytest.fixture
def registry():
    return load("purposes.json")


@pytest.fixture
def retention_ids():
    return {c["class_id"] for c in load("retention.json")["classes"]}


@pytest.fixture
def protocol():
    return vcp.load_json(vcp.COLLECTION_DIR / "manifest.json")


# ------------------------------------------------------------------ repository


def test_repository_drafts_validate():
    report = vcp.validate_repository()
    assert report.issues == []
    assert all(line.startswith("PASS ") for line in report.lines)
    assert vcp.main([]) == 0


def test_repository_records_no_fabricated_approval(registry):
    # Changing any of these requires a recorded human decision in the same change.
    assert registry["registry_status"] == "DRAFT_PENDING_OWNER_REVIEW"
    assert {p["status"] for p in registry["purposes"]} <= {"DRAFT", "NOT_OFFERED"}
    assert all(n["status"] == "DRAFT" for n in load("notices.json")["notices"])
    assert all(c["max_retention"]["value"] is None for c in load("retention.json")["classes"])
    assert all(s["review_status"] == "PENDING_REVIEW" for s in load("source_rights.json")["sources"])
    assert load("pilot_gate.json")["status"] == "PENDING"


def test_distinct_purposes_required_by_the_handoff_exist(registry):
    ids = {p["purpose_id"] for p in registry["purposes"]}
    assert set(vcp.REQUIRED_DISTINCT_PURPOSES) <= ids
    assert "partner_comparison" in ids and "ordinary_sharing" in ids


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_consent_scenario(path, registry):
    scenario = vcp.load_json(path)
    schemas = vcp.SchemaSet()
    assert schemas.validate(scenario, "consent-scenario.schema.json") == []
    assert vcp.run_scenario(registry, scenario) == []


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_expectations_are_not_vacuous(path, registry):
    scenario = vcp.load_json(path)
    for index, check in enumerate(scenario["checks"]):
        mutated = copy.deepcopy(scenario)
        mutated["checks"] = [mutated["checks"][index]]
        mutated["checks"][0]["expect"] = ["NOT_A_REAL_CODE"] if isinstance(check["expect"], list) else "NOT_A_REAL_STATE"
        assert codes(vcp.run_scenario(registry, mutated)) == ["SCENARIO_EXPECTATION"], (path.stem, index)


@pytest.mark.parametrize("path", COLLECTIONS, ids=lambda p: p.stem)
def test_collection_fixture(path, protocol):
    fixture = vcp.load_json(path)
    assert fixture["manifest"]["synthetic"] is True
    assert vcp.SchemaSet().validate(fixture["manifest"], "collection-manifest.schema.json") == []
    issues, _summary = vcp.check_collection_manifest(fixture["manifest"], protocol)
    assert codes(issues) == sorted(fixture["expected_errors"])


def expected_codes_in(paths):
    found = set()
    for path in paths:
        data = vcp.load_json(path)
        for check in data.get("checks", []):
            found.update(check["expect"] if isinstance(check["expect"], list) else [check["expect"]])
        found.update(data.get("expected_errors", []))
    return found


@pytest.mark.parametrize(
    "required",
    [
        "PAYMENT_IS_NOT_CONSENT",  # payment mistaken for AI consent
        "NO_AUTHOR_AUTHORITY",  # uploader lacks author permission
        "BLOCKED_AT_PUBLICATION",  # withdrawal during use
        "OBSOLETE_NOTICE",  # reused obsolete notice
        "DUPLICATE_COUNTED_AS_WRITER",  # duplicate specimen counted as a writer
        "PRECHECKED_GRANT",
        "DENIED",
        "WITHDRAWN",
        "NOT_ASKED",
        "INELIGIBLE",
    ],
)
def test_t03_negative_cases_have_fixtures(required):
    assert required in expected_codes_in(SCENARIOS + COLLECTIONS)


def test_collection_summary_counts_writers_not_pages(protocol):
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    issues, summary = vcp.check_collection_manifest(fixture["manifest"], protocol)
    assert issues == []
    assert (summary.writers, summary.specimens, summary.captures) == (3, 6, 7)
    # Copied and free writing, and each language, stay separate cohorts.
    assert set(summary.by_task) == {"copy_sv", "free_sv", "copy_en", "free_en"}
    assert summary.by_task["copy_sv"] == {"writers": 1, "specimens": 2}


# ---------------------------------------------------------------- evaluation


def test_free_report_never_depends_on_optional_choices(registry):
    optional = [
        ("image_retention", {"kind": "SUBJECT_WIDE", "id": "wrt_0001"}),
        ("reference_contribution", {"kind": "SUBJECT_WIDE", "id": "wrt_0001"}),
        ("third_party_ai_processing", {"kind": "REPORT", "id": "rpt_0001"}),
        ("ordinary_sharing", {"kind": "SHARE_GRANT", "id": "shr_0001"}),
        ("support_human_review", {"kind": "SUPPORT_CASE", "id": "sup_0001"}),
    ]
    base = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    service = base["events"][0]
    at = vcp.parse_timestamp("2026-02-05T00:00:00Z")
    specimen = {"kind": "SPECIMEN", "id": "spc_0001"}
    outcomes = set()
    for choices in itertools.product(("GRANT", "DENY", None), repeat=len(optional)):
        events = [service]
        for index, ((purpose_id, scope), choice) in enumerate(zip(optional, choices)):
            if choice:
                event = copy.deepcopy(service)
                event.update(event_id=f"evt_9{index}00", event_type=choice, scope=scope,
                             purpose={"purpose_id": purpose_id, "purpose_version": 1})
                events.append(event)
        scenario = dict(base, events=events)
        context = vcp.build_context(registry, scenario)
        assert all(not found for found in context.event_issues.values())
        outcomes.add(vcp.evaluate_free_report(context, "wrt_0001", specimen, at))
    assert outcomes == {"AVAILABLE"}


def test_invalid_events_never_change_state(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "payment_is_not_ai_consent.json")
    context = vcp.build_context(registry, scenario)
    valid_ids = {event["event_id"] for _index, event in context.valid}
    assert "evt_0302" not in valid_ids and "evt_0303" not in valid_ids


def test_duplicate_event_ids_invalidate_both(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    scenario["events"].append(copy.deepcopy(scenario["events"][0]))
    context = vcp.build_context(registry, scenario)
    assert "DUPLICATE_EVENT_ID" in context.event_issues["evt_0101"]
    assert all(event["event_id"] != "evt_0101" for _index, event in context.valid)


# ------------------------------------------------------------ registry rules


def mutate_purpose(registry, purpose_id, **changes):
    mutated = copy.deepcopy(registry)
    for purpose in mutated["purposes"]:
        if purpose["purpose_id"] == purpose_id:
            purpose.update(changes)
    return mutated


@pytest.mark.parametrize(
    ("purpose_id", "changes", "code"),
    [
        ("reference_contribution", {"presented_default": "SELECTED"}, "PRECHECKED_DEFAULT"),
        ("ordinary_sharing", {"presented_default": "SELECTED"}, "PRECHECKED_DEFAULT"),
        ("reference_contribution", {"affects_free_report": True}, "OPTIONAL_PURPOSE_AFFECTS_FREE"),
        ("image_retention", {"required_for_service": True}, "MULTIPLE_REQUIRED_PURPOSES"),
        ("third_party_ai_processing", {"status": "APPROVED"}, "APPROVAL_WITHOUT_EVIDENCE"),
        ("third_party_ai_processing", {"legal_basis": "DECIDED"}, "LEGAL_BASIS_WITHOUT_APPROVAL"),
        ("third_party_ai_processing", {"not_implied_by": ["entitlement"]}, "PAYMENT_NOT_EXCLUDED"),
        ("partner_comparison", {"withdrawal": {"available": False, "effect": "PROSPECTIVE", "propagation": []}}, "WITHDRAWAL_UNAVAILABLE"),
        ("reference_contribution", {"requires_author_authority": False}, "AUTHOR_AUTHORITY_REQUIRED"),
        ("reference_contribution", {"related_gates": ["invented_gate"]}, "UNKNOWN_GATE"),
        ("image_retention", {"retention_classes": ["forever"]}, "UNKNOWN_RETENTION_CLASS"),
        ("model_training", {"grant_scopes": ["SUBJECT_WIDE"]}, "INACTIVE_PURPOSE_HAS_USE"),
        ("support_human_review", {"grant_scopes": []}, "OFFERED_WITHOUT_SCOPE"),
    ],
)
def test_purpose_registry_rules(registry, retention_ids, purpose_id, changes, code):
    assert vcp.check_purposes(registry, retention_ids, vcp.known_gates()) == []
    mutated = mutate_purpose(registry, purpose_id, **changes)
    assert code in codes(vcp.check_purposes(mutated, retention_ids, vcp.known_gates()))


def test_partner_comparison_cannot_be_folded_into_sharing(registry, retention_ids):
    mutated = copy.deepcopy(registry)
    mutated["purposes"] = [p for p in mutated["purposes"] if p["purpose_id"] != "partner_comparison"]
    issues = vcp.check_purposes(mutated, retention_ids, vcp.known_gates())
    assert [(i.code, i.where) for i in issues] == [("MISSING_DISTINCT_PURPOSE", "partner_comparison")]


def test_notice_rules(registry):
    notices = load("notices.json")
    purposes = purposes_by_key(registry)
    assert vcp.check_notices(notices, purposes) == []

    missing_sv = copy.deepcopy(notices)
    missing_sv["notices"][0]["copy"] = [c for c in missing_sv["notices"][0]["copy"]
                                        if not (c["purpose_id"] == "partner_comparison" and c["locale"] == "sv")]
    assert codes(vcp.check_notices(missing_sv, purposes)) == ["MISSING_COPY"]

    active_without_decision = copy.deepcopy(notices)
    active_without_decision["notices"][0].update(status="ACTIVE", effective_from="2026-10-01T00:00:00Z")
    assert codes(vcp.check_notices(active_without_decision, purposes)) == ["NOTICE_ACTIVE_WITHOUT_DECISION"]

    offers_inactive = copy.deepcopy(notices)
    offers_inactive["notices"][0]["purposes"].append({"purpose_id": "model_training", "purpose_version": 1})
    assert "NOTICE_OFFERS_INACTIVE_PURPOSE" in codes(vcp.check_notices(offers_inactive, purposes))


# ----------------------------------------------------------- retention/lineage


def test_retention_is_configuration_not_legal_claim():
    retention = load("retention.json")
    assert vcp.check_retention(retention) == []

    decided_without_record = copy.deepcopy(retention)
    decided_without_record["classes"][0]["max_retention"] = {"value": 30, "unit": "DAYS"}
    assert codes(vcp.check_retention(decided_without_record)) == ["RETENTION_WITHOUT_DECISION"]

    unit_only = copy.deepcopy(retention)
    unit_only["classes"][0]["max_retention"] = {"value": None, "unit": "DAYS"}
    assert codes(vcp.check_retention(unit_only)) == ["RETENTION_UNIT_MISMATCH"]

    unsafe_restore = copy.deepcopy(retention)
    unsafe_restore["classes"][0]["backup_restore"] = "NOT_BACKED_UP"
    assert codes(vcp.check_retention(unsafe_restore)) == ["HANDWRITING_BACKUP_UNSAFE"]

    legal = copy.deepcopy(retention)
    legal["legal_claim"] = True
    assert codes(vcp.SchemaSet().validate(legal, "retention-policy.schema.json")) == ["SCHEMA"]


def test_deletion_lineage_rules():
    lineage = load("deletion_lineage.json")
    retention = {c["class_id"]: c for c in load("retention.json")["classes"]}
    assert vcp.check_lineage(lineage, retention) == []

    def with_node(kind, **changes):
        mutated = copy.deepcopy(lineage)
        next(n for n in mutated["nodes"] if n["artifact_kind"] == kind).update(changes)
        return mutated

    assert "LINEAGE_CYCLE" in codes(vcp.check_lineage(with_node(kind="normalized_image", parents=["report_revision"]), retention))
    undeclared_root = dict(copy.deepcopy(lineage), roots=["upload_original"])
    assert codes(vcp.check_lineage(undeclared_root, retention)) == ["LINEAGE_UNREACHABLE", "UNDECLARED_ROOT"]
    assert codes(vcp.check_lineage(with_node(kind="export_artifact", on_upstream_deletion="RETAIN_UNDER_SEPARATE_OBLIGATION"),
                                   retention)) == ["HANDWRITING_RETAINED"]
    assert codes(vcp.check_lineage(with_node(kind="crop_overlay_thumbnail", retention_class="analytics_events"),
                                   retention)) == ["RETENTION_CLASS_UNDERSTATES_HANDWRITING"]


# ------------------------------------------------------------- source rights


def test_code_data_and_weight_rights_are_distinct():
    rights = load("source_rights.json")
    assert vcp.check_source_rights(rights) == []

    nist = copy.deepcopy(rights)
    source = next(s for s in nist["sources"] if s["source_id"] == "nist_special_database_19")
    source["rights"]["code"]["status"] = "CLEARED"
    source["allowed_uses"]["benchmark_statistics"] = "CLEARED"
    source["review_status"] = "REVIEWED"
    source["review"] = {"decision_ref": "decision:nist-review", "reviewer_role": "data owner",
                        "reviewed_on": "2026-10-01T00:00:00Z", "archive_sha256": "0" * 64}
    assert codes(vcp.check_source_rights(nist)) == ["USE_CLEARED_WITHOUT_DATA_RIGHTS"]

    unreviewed = copy.deepcopy(rights)
    next(s for s in unreviewed["sources"] if s["source_id"] == "dhsd_v1")["allowed_uses"]["engineering_testing"] = "CLEARED"
    assert "CLEARED_WITHOUT_REVIEW" in codes(vcp.check_source_rights(unreviewed))

    iam = copy.deepcopy(rights)
    next(s for s in iam["sources"] if s["source_id"] == "iam_handwriting_database")["allowed_uses"]["display"] = "PENDING_REVIEW"
    assert codes(vcp.check_source_rights(iam)) == ["USE_OPEN_ON_UNCLEARED_DATA"]


# ---------------------------------------------------------------- pilot gate


def test_pilot_gate_blocks_activation_until_approved(registry, protocol):
    gate, notices = load("pilot_gate.json"), load("notices.json")
    purposes = purposes_by_key(registry)
    assert vcp.check_pilot_gate(gate, protocol, notices, purposes) == []

    approved = copy.deepcopy(gate)
    approved["status"] = "APPROVED"
    approved["approval"] = {"decision_ref": "decision:pilot-gate", "decided_by_role": "owner", "decided_on": "2026-10-01T00:00:00Z"}
    assert codes(vcp.check_pilot_gate(approved, protocol, notices, purposes)) == ["APPROVED_WITH_PENDING_DECISIONS"]

    active = copy.deepcopy(notices)
    active["notices"][1].update(status="ACTIVE", effective_from="2026-10-01T00:00:00Z", decision_ref="decision:pilot-notice")
    assert codes(vcp.check_pilot_gate(gate, protocol, active, purposes)) == ["GATE_BYPASSED"]

    product_contribution = copy.deepcopy(notices)
    product_contribution["notices"][0].update(status="ACTIVE", effective_from="2026-10-01T00:00:00Z", decision_ref="decision:product")
    assert codes(vcp.check_pilot_gate(gate, protocol, product_contribution, purposes)) == ["GATE_BYPASSED"]

    approved_protocol = dict(protocol, status="APPROVED")
    assert codes(vcp.check_pilot_gate(gate, approved_protocol, notices, purposes)) == ["GATE_BYPASSED"]


# ------------------------------------------------------- collection protocol


@pytest.fixture
def collection_copy(tmp_path):
    target = tmp_path / "collection"
    shutil.copytree(vcp.COLLECTION_DIR, target)
    return target


def test_prompt_edits_require_a_new_reviewed_hash(registry, protocol, collection_copy):
    purposes = purposes_by_key(registry)
    assert vcp.check_protocol(protocol, purposes, collection_copy) == []
    path = collection_copy / "prompts" / "copy-sv.v1.md"
    path.write_text(path.read_text(encoding="utf-8").replace("quiz", "korsord"), encoding="utf-8")
    assert codes(vcp.check_protocol(protocol, purposes, collection_copy)) == ["COPY_LETTER_COVERAGE", "PROMPT_HASH_MISMATCH"]


def test_free_writing_never_contains_a_copy_passage(registry, protocol, collection_copy):
    purposes = purposes_by_key(registry)
    path = collection_copy / "prompts" / "free-en.v1.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n```text\nCopy this sentence.\n```\n", encoding="utf-8")
    mutated = copy.deepcopy(protocol)
    task = next(t for t in mutated["tasks"] if t["task_id"] == "free_en")
    task["prompt_sha256"] = vcp.hashlib.sha256(path.read_bytes()).hexdigest()
    assert codes(vcp.check_protocol(mutated, purposes, collection_copy)) == ["FREE_TASK_HAS_PASSAGE"]


def test_every_language_has_one_copy_and_one_free_task(registry, protocol):
    mutated = copy.deepcopy(protocol)
    mutated["tasks"] = [t for t in mutated["tasks"] if t["task_id"] != "free_sv"]
    assert codes(vcp.check_protocol(mutated, purposes_by_key(registry))) == ["TASK_COVERAGE"]


def test_copy_passages_cover_letters_and_punctuation():
    for task_id, extra in (("copy-en", ""), ("copy-sv", "åäö")):
        text = (vcp.COLLECTION_DIR / "prompts" / f"{task_id}.v1.md").read_text(encoding="utf-8")
        passage = vcp.extract_passage(text)
        assert set("abcdefghijklmnopqrstuvwxyz" + extra) <= set(passage.lower())
        assert set(vcp.REQUIRED_PUNCTUATION) <= set(passage)


# ------------------------------------------------------------ schema subset


def test_schema_subset_rejects_unsupported_keywords(tmp_path):
    shutil.copytree(vcp.SCHEMA_DIR, tmp_path / "schemas")
    path = tmp_path / "schemas" / "common.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["$defs"]["text"]["maxLength"] = 10
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported keyword"):
        vcp.SchemaSet(tmp_path / "schemas")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda e: e.update(event_type="MAYBE"), "is not one of"),
        (lambda e: e["purpose"].update(purpose_version=True), "expected integer"),
        (lambda e: e.update(recorded_at="2026-02-02T09:00:00+01:00"), "not a UTC RFC 3339 timestamp"),
        (lambda e: e.update(recorded_at="2026-13-02T09:00:00Z"), "month must be in 1..12"),
        (lambda e: e.update(extra_field=1), "unexpected property"),
        (lambda e: e["subject"].update(id="alice@example.com"), "does not match"),
        (lambda e: e.pop("evidence"), "missing required property"),
    ],
)
def test_consent_event_schema_is_strict(mutate, message):
    scenario = vcp.load_json(SCENARIOS[0])
    event = copy.deepcopy(scenario["events"][0])
    schemas = vcp.SchemaSet()
    assert schemas.validate(event, "consent-event.schema.json") == []
    mutate(event)
    issues = schemas.validate(event, "consent-event.schema.json")
    assert issues and any(message in issue.message for issue in issues)


@pytest.mark.parametrize("text", ['{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'])
def test_strict_json_loading(tmp_path, text):
    path = tmp_path / "doc.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        vcp.load_json(path)
