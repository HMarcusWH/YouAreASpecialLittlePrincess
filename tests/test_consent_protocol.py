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


def check_fixture_manifest(fixture, protocol, manifest=None, *, human_release=False, fixture_mode=True, registry=None,
                           sources=None):
    """Run check_collection_manifest with the fixture's own consent ledger."""
    manifest = fixture["manifest"] if manifest is None else manifest
    registry = load("purposes.json") if registry is None else registry
    consent = vcp.collection_consent_context(registry, manifest, fixture["consent_log"], fixture_mode=fixture_mode)
    return vcp.check_collection_manifest(manifest, protocol, consent, human_release=human_release, sources=sources)


def approve(purpose, decided_on="2025-12-01T00:00:00Z"):
    """An in-memory approval for tests; the repository records none."""
    approval = {"decision_ref": "decision:test-approval", "decided_by_role": "owner", "decided_on": decided_on}
    return dict(purpose, status="APPROVED", legal_basis="DECIDED", approval=approval)


def approve_in(registry, purpose_id, decided_on="2025-12-01T00:00:00Z"):
    mutated = copy.deepcopy(registry)
    mutated["purposes"] = [approve(p, decided_on) if p["purpose_id"] == purpose_id else p for p in mutated["purposes"]]
    return mutated


def cleared_sources(*uses):
    """The source register with the owned pilot collection reviewed and the given uses cleared (tests only)."""
    sources = {s["source_id"]: copy.deepcopy(s) for s in load("source_rights.json")["sources"]}
    owned = sources["owned_pilot_collection_v1"]
    owned.update(review_status="REVIEWED", review={"decision_ref": "decision:test-review", "reviewer_role": "owner",
                                                   "reviewed_on": "2025-12-01T00:00:00Z", "archive_sha256": None})
    owned["rights"]["data"]["status"] = "CLEARED"
    for use in uses:
        owned["allowed_uses"][use] = "CLEARED"
    return sources


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
    issues, summary = check_fixture_manifest(fixture, protocol)
    assert codes(issues) == sorted(fixture["expected_errors"])
    assert summary.synthetic is True


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
        "NO_RELEASE_PERMISSION",
        "SESSION_WITHOUT_BASELINE",
        "PRECHECKED_GRANT",
        "INELIGIBLE_AT_GRANT",
        "DENIED",
        "WITHDRAWN",
        "NOT_ASKED",
        "INELIGIBLE",
    ],
)
def test_t03_negative_cases_have_fixtures(required):
    assert required in expected_codes_in(SCENARIOS + COLLECTIONS)


def test_human_release_rejects_synthetic_manifests(protocol):
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    approved = dict(protocol, status="APPROVED")
    issues, summary = check_fixture_manifest(fixture, approved, human_release=True, sources=cleared_sources("engineering_testing"))
    assert codes(issues) == ["SYNTHETIC_IN_HUMAN_RELEASE"]
    assert summary.synthetic is True


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda m: m["writers"][1].update(enrollment_id=m["writers"][0]["enrollment_id"]), "DUPLICATE_ID"),
        (lambda m: m["specimens"][0].update(session_index=99), "UNKNOWN_SESSION"),
    ],
)
def test_collection_identity_and_session_rules(protocol, mutate, code):
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = copy.deepcopy(fixture["manifest"])
    mutate(manifest)
    issues, _summary = check_fixture_manifest(fixture, protocol, manifest)
    assert code in codes(issues)


def test_release_counts_nothing_without_approved_permission(protocol):
    # Codex re-review of #12: a non-synthetic manifest with no consent evidence
    # was counted. Outside fixture mode the draft purposes cannot permit anything.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    issues, summary = check_fixture_manifest(fixture, dict(protocol, status="APPROVED"), manifest, human_release=True,
                                             fixture_mode=False, sources=cleared_sources("engineering_testing"))
    assert set(codes(issues)) == {"NO_RELEASE_PERMISSION", "COUNT_MISMATCH"}
    assert (summary.writers, summary.specimens, summary.captures) == (0, 0, 0)
    assert all("NOT_APPROVED" in i.message for i in issues if i.code == "NO_RELEASE_PERMISSION")

    empty_ledger = dict(fixture, consent_log={"notices": fixture["consent_log"]["notices"], "events": []})
    issues, summary = check_fixture_manifest(empty_ledger, protocol)
    assert "NO_RELEASE_PERMISSION" in codes(issues) and summary.writers == 0


def test_release_purpose_must_belong_to_the_protocol(protocol):
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = copy.deepcopy(fixture["manifest"])
    manifest["release_purpose"] = {"purpose_id": "product_analytics", "purpose_version": 1}
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    assert "RELEASE_PURPOSE_NOT_IN_PROTOCOL" in codes(issues) and summary.writers == 0


def test_human_release_needs_an_approved_protocol_and_cleared_source(registry, protocol):
    # Codex re-review of #12: a non-synthetic manifest collected under the draft
    # protocol, with the collection's source rights still pending, was counted.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    ledger = approve_in(registry, "engineering_evaluation")
    approved = dict(protocol, status="APPROVED")

    def run(protocol_doc, sources):
        issues, summary = check_fixture_manifest(fixture, protocol_doc, manifest, human_release=True, fixture_mode=False,
                                                 registry=ledger, sources=sources)
        return codes(issues), (summary.writers, summary.specimens, summary.captures)

    assert run(approved, cleared_sources("engineering_testing")) == ([], (3, 6, 7))
    assert run(protocol, cleared_sources("engineering_testing")) == (["COUNT_MISMATCH", "PROTOCOL_NOT_APPROVED"], (0, 0, 0))
    pending = {s["source_id"]: s for s in load("source_rights.json")["sources"]}
    assert run(approved, pending) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))
    assert run(approved, None) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))
    assert run(approved, cleared_sources("benchmark_statistics")) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))


def test_release_source_use_follows_the_release_purpose(protocol):
    sources = cleared_sources("engineering_testing")
    engineering = {"purpose_id": "engineering_evaluation", "purpose_version": 1}
    reference = {"purpose_id": "reference_contribution", "purpose_version": 1}
    assert vcp.source_clearance_issues(protocol, engineering, sources) == []
    assert codes(vcp.source_clearance_issues(protocol, reference, sources)) == ["SOURCE_NOT_CLEARED"]
    assert vcp.source_clearance_issues(protocol, reference, cleared_sources("benchmark_statistics")) == []
    analytics = {"purpose_id": "product_analytics", "purpose_version": 1}
    assert codes(vcp.source_clearance_issues(protocol, analytics, sources)) == ["SOURCE_NOT_CLEARED"]


def test_protocol_names_an_owned_source(registry, protocol):
    sources = {s["source_id"]: s for s in load("source_rights.json")["sources"]}
    purposes = purposes_by_key(registry)
    assert vcp.check_protocol(protocol, purposes, sources=sources) == []
    for source_id in ("iam_handwriting_database", "unknown_collection"):
        mutated = dict(protocol, source_id=source_id)
        assert codes(vcp.check_protocol(mutated, purposes, sources=sources)) == ["UNKNOWN_SOURCE"]


def test_specimen_task_must_be_scheduled_in_its_session(protocol):
    # Codex re-review of #12: only the session index was checked, so a COPY
    # specimen counted in a session that schedules only FREE writing.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    plan = copy.deepcopy(protocol)
    plan["session_plan"][1]["tasks_per_language"] = ["FREE"]
    issues, summary = check_fixture_manifest(fixture, plan)
    assert [(i.code, i.where) for i in issues if i.code != "COUNT_MISMATCH"] == [("TASK_NOT_IN_SESSION", "spc_0103")]
    assert summary.specimens == 5


def test_collection_summary_counts_writers_not_pages(protocol):
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    issues, summary = check_fixture_manifest(fixture, protocol)
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
        context = vcp.build_context(registry, scenario, fixture_mode=True)
        assert all(not found for found in context.event_issues.values())
        outcomes.add(vcp.evaluate_free_report(context, "wrt_0001", specimen, at))
    assert outcomes == {"AVAILABLE"}


def test_invalid_events_never_change_state(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "payment_is_not_ai_consent.json")
    context = vcp.build_context(registry, scenario, fixture_mode=True)
    valid_ids = {event["event_id"] for _index, event in context.valid}
    assert "evt_0302" not in valid_ids and "evt_0303" not in valid_ids


def test_duplicate_event_ids_invalidate_both(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    scenario["events"].append(copy.deepcopy(scenario["events"][0]))
    context = vcp.build_context(registry, scenario, fixture_mode=True)
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
        ("image_retention", {"required_for_service": True}, "SERVICE_REQUIREMENT_MISMATCH"),
        ("third_party_ai_processing", {"status": "APPROVED"}, "APPROVAL_WITHOUT_EVIDENCE"),
        ("product_analytics", {"status": "APPROVED", "approval": {"decision_ref": "decision:pa-1234", "decided_by_role": "owner",
                                                                  "decided_on": "2026-10-01T00:00:00Z"}},
         "APPROVED_WITHOUT_LEGAL_BASIS"),
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


def test_free_cannot_be_tied_to_an_optional_purpose(registry, retention_ids):
    # Codex review of #12: moving required_for_service to contribution passed validation.
    mutated = mutate_purpose(registry, "service_processing", required_for_service=False, affects_free_report=False)
    mutated = mutate_purpose(mutated, "reference_contribution", required_for_service=True)
    issues = vcp.check_purposes(mutated, retention_ids, vcp.known_gates())
    assert sorted((i.code, i.where) for i in issues) == [
        ("SERVICE_REQUIREMENT_MISMATCH", "reference_contribution@1"),
        ("SERVICE_REQUIREMENT_MISMATCH", "service_processing@1"),
    ]


def test_draft_purposes_never_permit_outside_fixtures(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    subject, specimen = {"kind": "WRITER", "id": "wrt_0001"}, {"kind": "SPECIMEN", "id": "spc_0001"}
    at = vcp.parse_timestamp("2026-02-03T00:00:00Z")
    service = {"purpose_id": "service_processing", "purpose_version": 1}

    production = vcp.build_context(registry, scenario)
    assert production.event_issues["evt_0101"] == ["PURPOSE_NOT_APPROVED"]
    assert vcp.evaluate_permission(production, subject, service, specimen, at) == "NOT_APPROVED"
    assert vcp.evaluate_free_report(production, "wrt_0001", specimen, at) == "UNAVAILABLE"

    fixture = vcp.build_context(registry, scenario, fixture_mode=True)
    assert vcp.evaluate_permission(fixture, subject, service, specimen, at) == "PERMITTED"


def test_approval_is_never_retroactive(registry):
    # Codex re-review of #12: a grant recorded under a notice backdated before
    # the purpose's approval became valid once the purpose was approved.
    ledger = approve_in(registry, "reference_contribution", decided_on="2026-10-01T00:00:00Z")
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    scenario["notices"] = [dict(scenario["notices"][0], version=9, effective_from="2026-09-01T00:00:00Z",
                                purposes=[{"purpose_id": "reference_contribution", "purpose_version": 1}])]
    early = dict(copy.deepcopy(scenario["events"][1]), event_id="evt_9001", event_type="GRANT",
                 notice={"notice_id": "notice.consent-choices", "version": 9},
                 recorded_at="2026-09-15T00:00:00Z", effective_at="2026-09-15T00:00:00Z")
    late = dict(copy.deepcopy(early), event_id="evt_9002", recorded_at="2026-10-02T00:00:00Z",
                effective_at="2026-10-02T00:00:00Z", scope={"kind": "SPECIMEN", "id": "spc_0002"})
    scenario["events"] = [early, late]
    context = vcp.build_context(ledger, scenario)
    assert context.event_issues == {"evt_9001": ["GRANTED_BEFORE_APPROVAL"], "evt_9002": []}
    at = vcp.parse_timestamp("2026-10-03T00:00:00Z")
    subject, purpose = early["subject"], early["purpose"]
    assert vcp.evaluate_permission(context, subject, purpose, {"kind": "SPECIMEN", "id": "spc_0001"}, at) == "NOT_ASKED"
    assert vcp.evaluate_permission(context, subject, purpose, {"kind": "SPECIMEN", "id": "spc_0002"}, at) == "PERMITTED"

    notices = copy.deepcopy(load("notices.json"))
    notices["notices"] = [notices["notices"][0]]
    notices["notices"][0].update(status="ACTIVE", effective_from="2026-09-01T00:00:00Z", decision_ref="decision:n-1234",
                                 purposes=[{"purpose_id": "reference_contribution", "purpose_version": 1}])
    notices["notices"][0]["copy"] = [c for c in notices["notices"][0]["copy"] if c["purpose_id"] == "reference_contribution"]
    purposes = purposes_by_key(ledger)
    assert codes(vcp.check_notices(notices, purposes)) == ["NOTICE_PREDATES_APPROVAL"]
    notices["notices"][0]["effective_from"] = "2026-10-01T00:00:00Z"
    assert vcp.check_notices(notices, purposes) == []


def test_account_authority_is_judged_when_the_event_is_recorded(registry):
    # Codex re-review of #12: authority was recomputed from the writer's current
    # account link, so linking the uploader later revived their old grant.
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    grant = dict(copy.deepcopy(scenario["events"][0]), actor={"kind": "ACCOUNT", "id": "acc_0002"})
    scenario["events"] = [grant]
    writer = scenario["writers"][0]
    writer.update(self_account_id="acc_0002", self_account_linked_at="2026-02-05T00:00:00Z")
    assert vcp.build_context(registry, scenario, fixture_mode=True).event_issues[grant["event_id"]] == ["NO_AUTHOR_AUTHORITY"]
    writer["self_account_linked_at"] = "2026-02-01T00:00:00Z"
    assert vcp.build_context(registry, scenario, fixture_mode=True).event_issues[grant["event_id"]] == []

    writer["self_account_linked_at"] = None
    assert vcp.build_context(registry, scenario, fixture_mode=True).event_issues[grant["event_id"]] == ["NO_AUTHOR_AUTHORITY"]
    assert "ACCOUNT_LINK_INCONSISTENT" in codes(vcp.run_scenario(registry, scenario | {"checks": []}))


def test_free_uses_the_service_version_in_effect(registry):
    # Codex re-review of #12: with v1 and v2 of service_processing, Free required
    # grants for both, so a new writer granting only the current v2 was refused.
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "service_change_requires_current_grant.json")
    context = vcp.build_context(registry, scenario, fixture_mode=True)
    specimen = {"kind": "SPECIMEN", "id": "spc_0009"}
    assert vcp.evaluate_free_report(context, "wrt_0009", specimen, vcp.parse_timestamp("2026-03-05T00:00:00Z")) == "AVAILABLE"
    assert vcp.evaluate_free_report(context, "wrt_0009", specimen, vcp.parse_timestamp("2025-12-01T00:00:00Z")) == "UNAVAILABLE"

    ambiguous = copy.deepcopy(scenario)
    ambiguous["notices"].append({"notice_id": "notice.other", "version": 1, "effective_from": "2026-03-01T00:00:00Z",
                                 "effective_until": None,
                                 "purposes": [{"purpose_id": "service_processing", "purpose_version": 1}]})
    context = vcp.build_context(registry, ambiguous, fixture_mode=True)
    assert vcp.evaluate_free_report(context, "wrt_0009", specimen, vcp.parse_timestamp("2026-03-05T00:00:00Z")) == "UNAVAILABLE"


def test_notice_presents_one_version_of_each_purpose(registry):
    # Codex re-review of #12: choice copy is keyed by purpose_id, so v1 and v2 in
    # one notice shared the same wording.
    purposes = purposes_by_key(registry)
    purposes[("service_processing", 2)] = dict(purposes[("service_processing", 1)], purpose_version=2)
    notices = copy.deepcopy(load("notices.json"))
    notices["notices"][0]["purposes"].append({"purpose_id": "service_processing", "purpose_version": 2})
    assert codes(vcp.check_notices(notices, purposes)) == ["NOTICE_LISTS_PURPOSE_TWICE"]

    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    scenario["notices"][0]["purposes"].append({"purpose_id": "service_processing", "purpose_version": 2})
    assert "NOTICE_LISTS_PURPOSE_TWICE" in codes(vcp.run_scenario(registry, scenario))


def test_query_scope_must_be_grantable_for_the_purpose(registry):
    # Codex re-review of #12: a subject-wide image_retention grant permitted REPORT,
    # COMPARISON and SUPPORT_CASE queries that the purpose never offers.
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    context = vcp.build_context(registry, scenario, fixture_mode=True)
    subject, purpose = {"kind": "WRITER", "id": "wrt_0001"}, {"purpose_id": "image_retention", "purpose_version": 1}
    at = vcp.parse_timestamp("2026-02-05T00:00:00Z")
    for kind in ("REPORT", "COMPARISON", "SUPPORT_CASE", "SHARE_GRANT", "PILOT_ENROLLMENT"):
        assert vcp.evaluate_permission(context, subject, purpose, {"kind": kind, "id": "any_0001"}, at) == "SCOPE_NOT_GRANTABLE"
    assert vcp.evaluate_permission(context, subject, purpose, {"kind": "SPECIMEN", "id": "spc_0001"}, at) == "PERMITTED"


def test_approvals_need_a_non_null_decision_ref(registry, retention_ids):
    # Codex re-review of #12: approval.decision_ref accepted null.
    approval = {"decision_ref": None, "decided_by_role": "owner", "decided_on": "2026-10-01T00:00:00Z"}
    mutated = mutate_purpose(registry, "product_analytics", status="APPROVED", legal_basis="DECIDED", approval=approval)
    assert "SCHEMA" in codes(vcp.SchemaSet().validate(mutated, "purpose-registry.schema.json"))
    assert "APPROVAL_WITHOUT_EVIDENCE" in codes(vcp.check_purposes(mutated, retention_ids, vcp.known_gates()))

    gate = dict(load("pilot_gate.json"), status="APPROVED", approval=approval)
    assert "SCHEMA" in codes(vcp.SchemaSet().validate(gate, "pilot-gate.schema.json"))


def test_partner_comparison_cannot_be_folded_into_sharing(registry, retention_ids):
    mutated = copy.deepcopy(registry)
    mutated["purposes"] = [p for p in mutated["purposes"] if p["purpose_id"] != "partner_comparison"]
    issues = vcp.check_purposes(mutated, retention_ids, vcp.known_gates())
    assert [(i.code, i.where) for i in issues] == [("MISSING_DISTINCT_PURPOSE", "partner_comparison")]


def test_notice_rules(registry):
    notices = load("notices.json")
    purposes = purposes_by_key(registry)
    assert vcp.check_notices(notices, purposes) == []
    approved = {key: approve(purpose) for key, purpose in purposes.items()}

    missing_sv = copy.deepcopy(notices)
    missing_sv["notices"][0]["copy"] = [c for c in missing_sv["notices"][0]["copy"]
                                        if not (c["purpose_id"] == "partner_comparison" and c["locale"] == "sv")]
    assert codes(vcp.check_notices(missing_sv, purposes)) == ["MISSING_COPY"]

    active_without_decision = copy.deepcopy(notices)
    active_without_decision["notices"][0].update(status="ACTIVE", effective_from="2026-10-01T00:00:00Z")
    assert set(codes(vcp.check_notices(active_without_decision, purposes))) == {
        "NOTICE_ACTIVE_WITHOUT_DECISION", "NOTICE_ACTIVE_FOR_UNAPPROVED_PURPOSE"}

    # Codex re-review of #12: an ACTIVE notice over draft purposes passed although
    # every grant under it would be rejected as PURPOSE_NOT_APPROVED.
    active = copy.deepcopy(notices)
    active["notices"][0].update(status="ACTIVE", effective_from="2026-10-01T00:00:00Z", decision_ref="decision:n-1234")
    found = vcp.check_notices(active, purposes)
    assert codes(found) == ["NOTICE_ACTIVE_FOR_UNAPPROVED_PURPOSE"]
    assert len(found) == len(active["notices"][0]["purposes"])
    assert vcp.check_notices(active, approved) == []

    offers_inactive = copy.deepcopy(notices)
    offers_inactive["notices"][0]["purposes"].append({"purpose_id": "model_training", "purpose_version": 1})
    assert "NOTICE_OFFERS_INACTIVE_PURPOSE" in codes(vcp.check_notices(offers_inactive, purposes))

    # Codex review of #12: a superseded notice without an end stayed usable forever.
    superseded = copy.deepcopy(notices)
    superseded["notices"][0].update(status="SUPERSEDED", effective_from="2026-01-01T00:00:00Z", decision_ref="decision:n-1234")
    assert codes(vcp.check_notices(superseded, approved)) == ["NOTICE_WINDOW_INVALID"]

    overlapping = copy.deepcopy(notices)
    second = copy.deepcopy(overlapping["notices"][0])
    overlapping["notices"][0].update(status="SUPERSEDED", effective_from="2026-01-01T00:00:00Z",
                                     effective_until="2026-06-01T00:00:00Z", decision_ref="decision:n-0001")
    second.update(version=2, status="ACTIVE", effective_from="2026-05-01T00:00:00Z", decision_ref="decision:n-0002")
    overlapping["notices"].append(second)
    assert codes(vcp.check_notices(overlapping, approved)) == ["NOTICE_WINDOW_OVERLAP"]
    second["effective_from"] = "2026-06-01T00:00:00Z"
    assert vcp.check_notices(overlapping, approved) == []


def test_scenario_notice_windows_must_not_overlap(registry):
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "reused_obsolete_notice.json")
    scenario["notices"][1]["effective_from"] = "2026-02-01T00:00:00Z"
    assert "NOTICE_WINDOW_OVERLAP" in codes(vcp.run_scenario(registry, scenario))


# ----------------------------------------------------------- retention/lineage


def test_retention_is_configuration_not_legal_claim():
    retention = load("retention.json")
    assert vcp.check_retention(retention) == []

    decided_without_record = copy.deepcopy(retention)
    decided_without_record["classes"][0]["max_retention"] = {"value": 30, "unit": "DAYS"}
    assert codes(vcp.check_retention(decided_without_record)) == ["RETENTION_WITHOUT_DECISION"]

    unit_only = copy.deepcopy(retention)
    unit_only["classes"][0]["max_retention"] = {"value": None, "unit": "DAYS"}
    assert codes(vcp.check_retention(unit_only)) == ["RETENTION_UNIT_MISMATCH", "RETENTION_WITHOUT_DECISION"]

    # Codex review of #12: DECIDED with null period passed, so approval needed no periods.
    decided_without_period = copy.deepcopy(retention)
    decided_without_period["classes"][0].update(decision_status="DECIDED", decision_ref="decision:ret-1234")
    assert codes(vcp.check_retention(decided_without_period)) == ["RETENTION_DECIDED_WITHOUT_PERIOD"]

    event_bound = copy.deepcopy(retention)
    event_bound["classes"][0].update(decision_status="DECIDED", decision_ref="decision:ret-1234",
                                     max_retention={"value": None, "unit": "EVENT_BOUND"})
    assert vcp.check_retention(event_bound) == []
    assert vcp.SchemaSet().validate(event_bound, "retention-policy.schema.json") == []
    event_bound["classes"][0]["max_retention"]["value"] = 30
    assert codes(vcp.check_retention(event_bound)) == ["RETENTION_UNIT_MISMATCH"]

    # Codex re-review of #12: EVENT_BOUND with no ending events had neither a period nor a trigger.
    endless = copy.deepcopy(retention)
    endless["classes"][0].update(decision_status="DECIDED", decision_ref="decision:ret-1234",
                                 max_retention={"value": None, "unit": "EVENT_BOUND"}, ends_when=[])
    assert codes(vcp.SchemaSet().validate(endless, "retention-policy.schema.json")) == ["SCHEMA"]
    assert codes(vcp.check_retention(endless)) == ["RETENTION_EVENT_BOUND_WITHOUT_END"]

    unsafe_restore = copy.deepcopy(retention)
    unsafe_restore["classes"][0]["backup_restore"] = "NOT_BACKED_UP"
    assert codes(vcp.check_retention(unsafe_restore)) == ["HANDWRITING_BACKUP_UNSAFE"]

    legal = copy.deepcopy(retention)
    legal["legal_claim"] = True
    assert codes(vcp.SchemaSet().validate(legal, "retention-policy.schema.json")) == ["SCHEMA"]


def test_approved_purposes_need_decided_retention(registry):
    # Codex re-review of #12: an approved purpose could use draft retention classes with null periods.
    retention = load("retention.json")
    assert vcp.check_purpose_retention(registry, retention) == []
    ledger = approve_in(registry, "service_processing")
    found = vcp.check_purpose_retention(ledger, retention)
    assert codes(found) == ["PURPOSE_RETENTION_UNDECIDED"] and len(found) == 4

    decided = copy.deepcopy(retention)
    decided["status"] = "APPROVED"
    for c in decided["classes"]:
        c.update(decision_status="DECIDED", decision_ref="decision:ret-1234", max_retention={"value": 30, "unit": "DAYS"})
    assert vcp.check_purpose_retention(ledger, decided) == []
    decided["classes"][0].update(decision_status="PENDING_OWNER_DECISION", decision_ref=None,
                                 max_retention={"value": None, "unit": None})
    assert [i.message.split()[0] for i in vcp.check_purpose_retention(ledger, decided)] == [decided["classes"][0]["class_id"]]


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

    # Codex review of #12: deleting pending decisions let the gate approve with one decision.
    stripped = copy.deepcopy(approved)
    stripped["decisions"] = [dict(stripped["decisions"][0], status="DECIDED", decision_ref="decision:controller-1")]
    found = vcp.check_pilot_gate(stripped, protocol, notices, purposes)
    assert codes(found) == ["MISSING_GATE_DECISION"]
    assert sorted(i.where for i in found) == sorted(vcp.REQUIRED_PILOT_DECISIONS[1:])


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


def test_protocol_approval_requires_decided_prompt_rights(registry, protocol):
    approved = dict(copy.deepcopy(protocol), status="APPROVED")
    found = vcp.check_protocol(approved, purposes_by_key(registry))
    assert codes(found) == ["PROTOCOL_APPROVED_WITH_PENDING_RIGHTS"]
    assert len(found) == len(protocol["tasks"])
    for task in approved["tasks"]:
        task["rights"].update(decision_status="DECIDED", decision_ref="decision:prompt-rights")
    assert vcp.check_protocol(approved, purposes_by_key(registry)) == []


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
