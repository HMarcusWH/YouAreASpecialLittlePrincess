"""Regression tests for the T03 consent, retention, source-rights and collection drafts."""

import copy
import hashlib
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
                           sources=None, notices=None, publish_at=None, gate=None):
    """Run check_collection_manifest with the fixture's own consent ledger."""
    manifest = fixture["manifest"] if manifest is None else manifest
    registry = load("purposes.json") if registry is None else registry
    consent = vcp.collection_consent_context(registry, manifest, fixture["consent_log"], fixture_mode=fixture_mode,
                                             notices=notices)
    return vcp.check_collection_manifest(manifest, protocol, consent, human_release=human_release, sources=sources,
                                         publish_at=publish_at, gate=gate)


def bind(document):
    """Stamp the document's approval with a digest of its current content (tests only)."""
    document["approval"]["content_sha256"] = vcp.content_sha256(document)
    return document


def approve(purpose, decided_on="2025-12-01T00:00:00Z"):
    """An in-memory approval for tests, with a decision for every related gate; the repository records none."""
    approval = {"decision_ref": "decision:test-approval", "decided_by_role": "owner", "decided_on": decided_on,
                "gate_decisions": [{"gate": gate, "decision_ref": "decision:test-gate"} for gate in purpose["related_gates"]]}
    return bind(dict(copy.deepcopy(purpose), status="APPROVED", legal_basis="DECIDED", approval=approval))


def approved_protocol(protocol, decided_on="2026-01-10T00:00:00Z", *, decide_rights=True):
    """The protocol approved in memory, with every prompt's rights decided unless told otherwise (tests only)."""
    approval = {"decision_ref": "decision:test-protocol", "decided_by_role": "owner", "decided_on": decided_on}
    approved = dict(copy.deepcopy(protocol), status="APPROVED", approval=approval)
    if decide_rights:
        for task in approved["tasks"]:
            task["rights"].update(decision_status="DECIDED", decision_ref="decision:prompt-rights")
    return bind(approved)


def approved_gate(decided_on="2026-01-05T00:00:00Z"):
    """pilot_gate.json approved with every decision recorded (tests only)."""
    gate = copy.deepcopy(load("pilot_gate.json"))
    gate.update(status="APPROVED", approval={"decision_ref": "decision:test-gate", "decided_by_role": "owner",
                                             "decided_on": decided_on})
    for decision in gate["decisions"]:
        decision.update(status="DECIDED", decision_ref="decision:test-gate-item")
    return bind(gate)


def active_pilot_notices(effective_from="2026-01-01T00:00:00Z"):
    """notices.json with the pilot notice put in effect (tests only)."""
    notices = copy.deepcopy(load("notices.json"))
    pilot = next(n for n in notices["notices"] if n["notice_id"] == "notice.pilot-collection")
    pilot.update(status="ACTIVE", effective_from=effective_from, decision_ref="decision:test-notice")
    return notices


CUTOFF = vcp.parse_timestamp("2026-03-01T00:00:00Z")


def approve_in(registry, purpose_id, decided_on="2025-12-01T00:00:00Z"):
    mutated = copy.deepcopy(registry)
    mutated["purposes"] = [approve(p, decided_on) if p["purpose_id"] == purpose_id else p for p in mutated["purposes"]]
    return mutated


def cleared_sources(*uses):
    """The source register with the owned pilot collection reviewed and the given uses cleared (tests only)."""
    sources = {s["source_id"]: copy.deepcopy(s) for s in load("source_rights.json")["sources"]}
    owned = sources["owned_pilot_collection_v1"]
    owned.update(review_status="REVIEWED", review={"decision_ref": "decision:test-review", "reviewer_role": "owner",
                                                   "reviewed_on": "2025-12-01T00:00:00Z", "expires_on": None,
                                                   "archive_sha256": None})
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


@pytest.mark.parametrize("purpose_id", ["image_retention", "public_example"])
def test_storage_retention_and_public_disclosure_stay_distinct(registry, retention_ids, purpose_id):
    # Codex review of #12: both could be deleted without any validator issue.
    reduced = copy.deepcopy(registry)
    reduced["purposes"] = [p for p in reduced["purposes"] if p["purpose_id"] != purpose_id]
    issues = vcp.check_purposes(reduced, retention_ids, vcp.known_gates())
    assert [(i.code, i.where) for i in issues] == [("MISSING_DISTINCT_PURPOSE", purpose_id)]


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
    publish_at = vcp.parse_timestamp(fixture["publish_at"]) if "publish_at" in fixture else None
    issues, summary = check_fixture_manifest(fixture, protocol, publish_at=publish_at)
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
        "EVIDENCE_MISMATCH",
        "COLLECTED_AFTER_CUTOFF",
        "REPEAT_NOT_EARLIER",
        "NO_COLLECTION_PERMISSION",
        "REPEAT_OF_INVALID_CAPTURE",
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
    issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), human_release=True, fixture_mode=False,
                                             registry=approve_in(load("purposes.json"), "engineering_evaluation"),
                                             sources=cleared_sources("engineering_testing"), publish_at=CUTOFF,
                                             notices=active_pilot_notices(), gate=approved_gate())
    # Codex review of #12: the diagnostic was raised but the synthetic cohort was still counted.
    assert codes(issues) == ["COUNT_MISMATCH", "SYNTHETIC_IN_HUMAN_RELEASE"]
    assert summary.synthetic is True and (summary.writers, summary.specimens, summary.captures) == (0, 0, 0)


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
    issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), manifest, human_release=True,
                                             fixture_mode=False, sources=cleared_sources("engineering_testing"),
                                             notices=active_pilot_notices(), publish_at=CUTOFF, gate=approved_gate())
    # Draft purposes permit nothing, so no page was even collected with permission.
    assert set(codes(issues)) == {"NO_COLLECTION_PERMISSION", "COUNT_MISMATCH"}
    assert (summary.writers, summary.specimens, summary.captures) == (0, 0, 0)

    empty_ledger = dict(fixture, consent_log={"notices": fixture["consent_log"]["notices"], "events": []})
    issues, summary = check_fixture_manifest(empty_ledger, protocol)
    assert "NO_COLLECTION_PERMISSION" in codes(issues) and summary.writers == 0


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
    approved = approved_protocol(protocol)

    def run(protocol_doc, sources):
        issues, summary = check_fixture_manifest(fixture, protocol_doc, manifest, human_release=True, fixture_mode=False,
                                                 registry=ledger, sources=sources, notices=active_pilot_notices(),
                                                 publish_at=CUTOFF, gate=approved_gate())
        return codes(issues), (summary.writers, summary.specimens, summary.captures)

    assert run(approved, cleared_sources("engineering_testing")) == ([], (3, 6, 7))
    assert run(protocol, cleared_sources("engineering_testing")) == (["COUNT_MISMATCH", "PROTOCOL_NOT_APPROVED"], (0, 0, 0))
    # Codex review of #12: APPROVED without a recorded approval passed.
    unrecorded = dict(protocol, status="APPROVED")
    assert run(unrecorded, cleared_sources("engineering_testing")) == (["COUNT_MISMATCH", "PROTOCOL_NOT_APPROVED"], (0, 0, 0))
    assert "APPROVAL_WITHOUT_EVIDENCE" in codes(vcp.check_protocol(unrecorded, purposes_by_key(registry)))
    pending = {s["source_id"]: s for s in load("source_rights.json")["sources"]}
    assert run(approved, pending) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))
    assert run(approved, None) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))
    assert run(approved, cleared_sources("benchmark_statistics")) == (["COUNT_MISMATCH", "SOURCE_NOT_CLEARED"], (0, 0, 0))


def test_release_source_use_follows_the_release_purpose(protocol):
    sources = cleared_sources("engineering_testing")
    engineering = {"purpose_id": "engineering_evaluation", "purpose_version": 1}
    reference = {"purpose_id": "reference_contribution", "purpose_version": 1}
    assert vcp.source_clearance_issues(protocol, engineering, sources, CUTOFF) == []
    assert codes(vcp.source_clearance_issues(protocol, reference, sources, CUTOFF)) == ["SOURCE_NOT_CLEARED"]
    assert vcp.source_clearance_issues(protocol, reference, cleared_sources("benchmark_statistics"), CUTOFF) == []
    analytics = {"purpose_id": "product_analytics", "purpose_version": 1}
    assert codes(vcp.source_clearance_issues(protocol, analytics, sources, CUTOFF)) == ["SOURCE_NOT_CLEARED"]

    # Codex review of #12: a review dated after the cutoff cleared the release retroactively.
    sources["owned_pilot_collection_v1"]["review"]["reviewed_on"] = "2099-01-01T00:00:00Z"
    late = vcp.source_clearance_issues(protocol, engineering, sources, CUTOFF)
    assert codes(late) == ["SOURCE_NOT_CLEARED"] and "after the release cutoff" in late[0].message


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


def test_protocol_approval_is_never_retroactive(registry, protocol):
    # Codex review of #12: pages written while the protocol was unapproved
    # were counted once the current document said APPROVED.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    issues, summary = check_fixture_manifest(
        fixture, approved_protocol(protocol, decided_on="2026-02-10T00:00:00Z"), manifest, human_release=True,
        fixture_mode=False, registry=approve_in(registry, "engineering_evaluation"),
        sources=cleared_sources("engineering_testing"), notices=active_pilot_notices(), publish_at=CUTOFF,
        gate=approved_gate())
    assert codes(issues) == ["COLLECTED_BEFORE_PROTOCOL_APPROVAL", "COUNT_MISMATCH", "SESSION_WITHOUT_BASELINE"]
    assert (summary.writers, summary.specimens, summary.captures) == (0, 0, 0)


def test_human_release_rechecks_permission_at_publication(registry, protocol):
    # Codex review of #12: a withdrawal after the cutoff but before publication was ignored.
    fixture = copy.deepcopy(vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json"))
    manifest = dict(fixture["manifest"], synthetic=False)
    withdraw = dict(copy.deepcopy(fixture["consent_log"]["events"][0]), event_id="evt_9004", event_type="WITHDRAW",
                    capture_method="WITHDRAWAL_CONTROL", presented_default="NOT_PRESENTED",
                    scope={"kind": "SPECIMEN", "id": "spc_0102"},
                    recorded_at="2026-03-02T00:00:00Z", effective_at="2026-03-02T00:00:00Z")
    fixture["consent_log"]["events"].append(withdraw)
    common = dict(human_release=True, fixture_mode=False, registry=approve_in(registry, "engineering_evaluation"),
                  sources=cleared_sources("engineering_testing"), notices=active_pilot_notices(), gate=approved_gate())

    issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), manifest,
                                             publish_at=vcp.parse_timestamp("2026-03-05T00:00:00Z"), **common)
    assert [(i.code, i.where) for i in issues if i.code != "COUNT_MISMATCH"] == [("NO_RELEASE_PERMISSION", "spc_0102")]
    assert "at publication" in issues[0].message and summary.specimens == 5

    issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), manifest, publish_at=None, **common)
    assert "PUBLICATION_NOT_RECHECKED" in codes(issues) and summary.specimens == 0
    early = vcp.parse_timestamp("2026-02-20T00:00:00Z")
    issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), manifest, publish_at=early, **common)
    assert "PUBLICATION_BEFORE_CUTOFF" in codes(issues) and summary.specimens == 0


def test_collection_notices_come_from_the_registry(registry, protocol):
    # Codex review of #12: a ledger could describe its own notice window, so a
    # fabricated notice made grants release-authorizing.
    fixture = copy.deepcopy(vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json"))
    fixture["consent_log"]["notices"][0]["notice_id"] = "notice.fabricated"
    for event in fixture["consent_log"]["events"]:
        event["notice"]["notice_id"] = "notice.fabricated"
    manifest = dict(fixture["manifest"], synthetic=False)
    issues, summary = check_fixture_manifest(
        fixture, approved_protocol(protocol), manifest, human_release=True, fixture_mode=False,
        registry=approve_in(registry, "engineering_evaluation"), sources=cleared_sources("engineering_testing"),
        notices=active_pilot_notices(), publish_at=CUTOFF, gate=approved_gate())
    assert codes(issues) == ["COUNT_MISMATCH", "NO_COLLECTION_PERMISSION"] and summary.writers == 0
    context = vcp.collection_consent_context(approve_in(registry, "engineering_evaluation"), manifest,
                                             fixture["consent_log"], notices=active_pilot_notices())
    assert all(found == ["UNKNOWN_NOTICE"] for found in context.event_issues.values())
    assert vcp.registry_notice_windows(load("notices.json")) == []


def test_human_release_needs_the_pilot_gate_before_the_protocol(registry, protocol):
    # Codex review of #12: a gate approved in 2099 did not stop a protocol approved in 2026.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    common = dict(human_release=True, fixture_mode=False, registry=approve_in(registry, "engineering_evaluation"),
                  sources=cleared_sources("engineering_testing"), notices=active_pilot_notices(), publish_at=CUTOFF)
    for gate in (None, load("pilot_gate.json"), approved_gate("2099-01-01T00:00:00Z")):
        issues, summary = check_fixture_manifest(fixture, approved_protocol(protocol), manifest, gate=gate, **common)
        assert codes(issues) == ["COUNT_MISMATCH", "PILOT_GATE_NOT_APPROVED"] and summary.specimens == 0

    decided = approved_protocol(protocol)
    for task in decided["tasks"]:
        task["rights"].update(decision_status="DECIDED", decision_ref="decision:prompt-rights")
    purposes = purposes_by_key(registry)
    late = vcp.check_pilot_gate(approved_gate("2099-01-01T00:00:00Z"), decided, load("notices.json"), purposes)
    assert codes(late) == ["GATE_APPROVED_AFTER_PROTOCOL"]
    assert vcp.check_pilot_gate(approved_gate(), decided, load("notices.json"), purposes) == []


def test_fixture_mode_never_authorizes_human_data(registry, protocol):
    # Codex review of #12: fixture mode made draft purposes and self-described
    # notices usable for a non-synthetic manifest.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    with pytest.raises(ValueError, match="only for synthetic manifests"):
        vcp.collection_consent_context(registry, manifest, fixture["consent_log"], fixture_mode=True)
    consent = vcp.collection_consent_context(registry, fixture["manifest"], fixture["consent_log"], fixture_mode=True)
    issues, summary = vcp.check_collection_manifest(
        manifest, approved_protocol(protocol), consent, human_release=True,
        sources=cleared_sources("engineering_testing"), publish_at=CUTOFF, gate=approved_gate())
    assert "FIXTURE_CONSENT_IN_HUMAN_RELEASE" in codes(issues) and summary.specimens == 0


def test_every_later_capture_names_its_original(protocol):
    # Codex review of #12: capture 2 without repeat_of_capture_id had no provenance link.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = copy.deepcopy(fixture["manifest"])
    manifest["captures"][1]["repeat_of_capture_id"] = None
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    # Codex review of #12: the unlinked capture was reported but still counted.
    assert [(i.code, i.where) for i in issues if i.code != "COUNT_MISMATCH"] == [("REPEAT_WITHOUT_ORIGINAL", "cap_0102")]
    assert (summary.specimens, summary.captures) == (6, 6)


def test_gate_with_pending_decisions_blocks_human_release(registry, protocol):
    # Codex review of #12: an APPROVED gate with every decision still pending passed the release path.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    gate = approved_gate()
    gate["decisions"][0].update(status="PENDING_OWNER_DECISION", decision_ref=None)
    issues, summary = check_fixture_manifest(
        fixture, approved_protocol(protocol), manifest, human_release=True, fixture_mode=False,
        registry=approve_in(registry, "engineering_evaluation"), sources=cleared_sources("engineering_testing"),
        notices=active_pilot_notices(), publish_at=CUTOFF, gate=gate)
    assert codes(issues) == ["COUNT_MISMATCH", "PILOT_GATE_NOT_APPROVED"] and summary.specimens == 0


def test_protocol_mismatch_counts_nothing(protocol):
    # Codex review of #12: a manifest from protocol version 999 was still counted 3/6/7.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = copy.deepcopy(fixture["manifest"])
    manifest["protocol"]["version"] = 999
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    assert codes(issues) == ["COUNT_MISMATCH", "PROTOCOL_MISMATCH"]
    assert (summary.writers, summary.specimens, summary.captures) == (0, 0, 0)


def test_source_clearance_expires(protocol):
    # Codex review of #12: a review had no expiry, so time-limited terms stayed cleared forever.
    engineering = {"purpose_id": "engineering_evaluation", "purpose_version": 1}
    sources = cleared_sources("engineering_testing")
    review = sources["owned_pilot_collection_v1"]["review"]
    review["expires_on"] = "2026-06-01T00:00:00Z"
    assert vcp.source_clearance_issues(protocol, engineering, sources, CUTOFF, CUTOFF) == []
    late = vcp.parse_timestamp("2026-06-02T00:00:00Z")
    expired = vcp.source_clearance_issues(protocol, engineering, sources, CUTOFF, late)
    assert codes(expired) == ["SOURCE_NOT_CLEARED"] and "expired" in expired[0].message
    review["expires_on"] = "2025-11-01T00:00:00Z"
    register = {"contract_version": "source-rights/v1", "sources": list(sources.values())}
    assert "REVIEW_WINDOW_INVALID" in codes(vcp.check_source_rights(register))
    assert vcp.SchemaSet().validate(register, "source-rights.schema.json") == []


def test_human_release_needs_decided_prompt_rights(registry, protocol):
    # Codex review of #12: an APPROVED protocol with pending prompt rights still released the cohort.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    issues, summary = check_fixture_manifest(
        fixture, approved_protocol(protocol, decide_rights=False), manifest, human_release=True, fixture_mode=False,
        registry=approve_in(registry, "engineering_evaluation"), sources=cleared_sources("engineering_testing"),
        notices=active_pilot_notices(), publish_at=CUTOFF, gate=approved_gate())
    assert codes(issues) == ["COUNT_MISMATCH", "PROTOCOL_NOT_APPROVED"] and summary.specimens == 0


def test_shared_enrollment_makes_both_writers_uncountable(protocol):
    # Codex review of #12: two writer rows sharing an enrollment were both counted.
    fixture = copy.deepcopy(vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json"))
    writers = fixture["manifest"]["writers"]
    writers[1]["enrollment_id"] = writers[0]["enrollment_id"]
    fixture["consent_log"]["events"][1]["scope"]["id"] = writers[0]["enrollment_id"]
    issues, summary = check_fixture_manifest(fixture, protocol)
    assert codes(issues) == ["COUNT_MISMATCH", "DUPLICATE_ID"]
    assert (summary.writers, summary.specimens, summary.captures) == (1, 1, 1)  # only writer 3 remains


def test_repeat_chain_through_an_invalid_capture_is_not_counted(protocol):
    # Codex review of #12: capture 3 repeating an invalid capture 2 was still counted.
    fixture = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")
    manifest = copy.deepcopy(fixture["manifest"])
    manifest["captures"][1]["repeat_of_capture_id"] = None
    manifest["captures"].append({"capture_id": "cap_0105", "specimen_id": "spc_0101", "capture_index": 3,
                                 "content_sha256": "f" * 64, "repeat_of_capture_id": "cap_0102"})
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    assert [(i.code, i.where) for i in issues if i.code != "COUNT_MISMATCH"] == [
        ("REPEAT_WITHOUT_ORIGINAL", "cap_0102"), ("REPEAT_OF_INVALID_CAPTURE", "cap_0105")]
    assert summary.captures == 6


def valid_lineage():
    return vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "collection" / "valid_pilot_lineage.json")


def human_release(fixture, protocol, manifest, registry):
    """A human release of `manifest` with everything but the thing under test approved and cleared."""
    return check_fixture_manifest(fixture, protocol, manifest, human_release=True, fixture_mode=False, registry=registry,
                                  sources=cleared_sources("engineering_testing"), notices=active_pilot_notices(),
                                  publish_at=CUTOFF, gate=approved_gate())


def counts_of(summary):
    return summary.writers, summary.specimens, summary.captures


def test_purpose_grants_need_every_related_gate_decided(registry, protocol):
    # Codex review of #12: approved_by checked only status and decided_on, so an approved purpose
    # without its gate decisions released the whole cohort.
    fixture = valid_lineage()
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    ledger = approve_in(registry, "engineering_evaluation")
    issues, summary = human_release(fixture, approved_protocol(protocol), manifest, ledger)
    assert issues == [] and counts_of(summary) == (3, 6, 7)

    purpose = next(p for p in ledger["purposes"] if p["purpose_id"] == "engineering_evaluation")
    purpose["approval"]["gate_decisions"] = purpose["approval"]["gate_decisions"][:1]
    assert not vcp.approved_by(purpose, "2026-02-01T00:00:00Z")
    issues, summary = human_release(fixture, approved_protocol(protocol), manifest, ledger)
    assert "NO_COLLECTION_PERMISSION" in codes(issues) and counts_of(summary) == (0, 0, 0)
    consent = vcp.collection_consent_context(ledger, manifest, fixture["consent_log"], notices=active_pilot_notices())
    assert set(itertools.chain.from_iterable(consent.event_issues.values())) == {"PURPOSE_NOT_APPROVED"}
    subject, scope = {"kind": "WRITER", "id": "wrt_0001"}, {"kind": "SPECIMEN", "id": "spc_0101"}
    assert vcp.evaluate_permission(consent, subject, manifest["release_purpose"], scope, CUTOFF) == "NOT_APPROVED"


def test_approvals_bind_the_content_they_approved(registry, retention_ids, protocol, tmp_path):
    # Codex review of #12: a prompt and its hash changed together kept the protocol's old approval.
    base = tmp_path / "collection"
    shutil.copytree(vcp.COLLECTION_DIR, base)
    purposes = purposes_by_key(registry)
    approved = approved_protocol(protocol)
    assert vcp.check_protocol(approved, purposes, base) == []
    task = approved["tasks"][0]
    prompt = base / task["prompt_file"]
    prompt.write_bytes(prompt.read_bytes() + b"\nAn instruction nobody reviewed.\n")
    task["prompt_sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
    assert codes(vcp.check_protocol(approved, purposes, base)) == ["APPROVAL_CONTENT_MISMATCH"]
    fixture = valid_lineage()
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    issues, summary = human_release(fixture, approved, manifest, approve_in(registry, "engineering_evaluation"))
    assert "PROTOCOL_NOT_APPROVED" in codes(issues) and counts_of(summary) == (0, 0, 0)
    assert vcp.check_protocol(bind(approved), purposes, base) == []  # a new approval of the new wording

    # Purposes and the gate alike: only a status change, such as RETIRED, keeps an approval.
    ledger = approve_in(registry, "product_analytics")
    purpose = next(p for p in ledger["purposes"] if p["purpose_id"] == "product_analytics")
    purpose["status"] = "RETIRED"
    assert vcp.approved_by(purpose, "2026-01-01T00:00:00Z")
    purpose["status"] = "APPROVED"
    purpose["data_categories"].append("page_images")
    assert codes(vcp.check_purposes(ledger, retention_ids, vcp.known_gates())) == ["APPROVAL_CONTENT_MISMATCH"]
    assert not vcp.approved_by(purpose, "2026-01-01T00:00:00Z")
    gate = approved_gate()
    assert vcp.gate_approved_by(gate, "2026-01-10T00:00:00Z")
    gate["decisions"][0]["decision_ref"] = "decision:other-controller"
    assert not vcp.gate_approved_by(gate, "2026-01-10T00:00:00Z")
    assert codes(vcp.check_pilot_gate(gate, approved, load("notices.json"), purposes)) == [
        "APPROVAL_CONTENT_MISMATCH", "GATE_APPROVED_AFTER_PROTOCOL"]


def test_sessions_without_repeat_captures_reject_repeats(protocol):
    # Codex review of #12: session 2 declares repeat_captures NONE, yet its repeats were counted.
    fixture = valid_lineage()
    manifest = copy.deepcopy(fixture["manifest"])
    manifest["captures"].append({"capture_id": "cap_0105", "specimen_id": "spc_0103", "capture_index": 2,
                                 "content_sha256": "e" * 64, "repeat_of_capture_id": "cap_0104"})
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    assert [(i.code, i.where) for i in issues] == [("REPEAT_NOT_IN_SESSION_PLAN", "cap_0105")]
    assert counts_of(summary) == (3, 6, 7)


def test_each_writer_stays_in_one_language_cohort(protocol):
    # Codex review of #12: a writer with an English copy page and a Swedish free page entered both cohorts.
    fixture = valid_lineage()
    manifest = copy.deepcopy(fixture["manifest"])
    next(s for s in manifest["specimens"] if s["specimen_id"] == "spc_0202").update(task_id="free_sv", declared_language="sv")
    manifest["claimed_counts"] = {"writers": 2, "specimens": 4, "captures": 5}
    issues, summary = check_fixture_manifest(fixture, protocol, manifest)
    assert [(i.code, i.where) for i in issues] == [("WRITER_LANGUAGE_CONFLICT", "spc_0201"), ("WRITER_LANGUAGE_CONFLICT", "spc_0202")]
    assert "free_sv" in summary.by_task and summary.by_task["free_sv"]["writers"] == 1  # only writer 1's page
    # An honestly recorded unsupported page (writer 3's Finnish page) is not a second cohort.
    assert check_fixture_manifest(fixture, protocol)[0] == []


def test_every_capture_sharing_an_index_is_excluded_in_any_order(protocol):
    # Codex review of #12: only the later of two index-1 captures was rejected, so array order chose the original.
    fixture = valid_lineage()
    results = []
    for position in (None, 0):
        manifest = copy.deepcopy(fixture["manifest"])
        extra = {"capture_id": "cap_0109", "specimen_id": "spc_0102", "capture_index": 1, "content_sha256": "d" * 64,
                 "repeat_of_capture_id": None}
        manifest["captures"].insert(len(manifest["captures"]) if position is None else position, extra)
        manifest["claimed_counts"] = {"writers": 3, "specimens": 5, "captures": 6}
        issues, summary = check_fixture_manifest(fixture, protocol, manifest)
        results.append((sorted((i.code, i.where) for i in issues), counts_of(summary)))
    assert results[0] == results[1] == (
        [("CAPTURE_INDEX_CONFLICT", "cap_0103"), ("CAPTURE_INDEX_CONFLICT", "cap_0109")], (3, 5, 6))


def test_captures_behind_rejected_bytes_are_not_counted(protocol):
    # Codex review of #12: a repeat of a byte-duplicate capture still counted, since only link errors broke chains.
    fixture = valid_lineage()
    chain = copy.deepcopy(fixture["manifest"])
    chain["captures"][1]["content_sha256"] = chain["captures"][0]["content_sha256"]
    chain["captures"].append({"capture_id": "cap_0105", "specimen_id": "spc_0101", "capture_index": 3,
                              "content_sha256": "c" * 64, "repeat_of_capture_id": "cap_0102"})
    chain["claimed_counts"]["captures"] = 6
    issues, summary = check_fixture_manifest(fixture, protocol, chain)
    assert sorted((i.code, i.where) for i in issues) == [
        ("DUPLICATE_CAPTURE_BYTES", "cap_0102"), ("REPEAT_OF_INVALID_CAPTURE", "cap_0105")]
    assert counts_of(summary) == (3, 6, 6)

    # Bytes shared across writers cannot show whose page they are: neither counts, in any order.
    results = []
    for reverse in (False, True):
        shared = copy.deepcopy(fixture["manifest"])
        shared["captures"][4]["content_sha256"] = shared["captures"][0]["content_sha256"]  # cap_0201 = cap_0101
        if reverse:
            shared["captures"].reverse()
        issues, summary = check_fixture_manifest(fixture, protocol, shared)
        results.append((sorted((i.code, i.where) for i in issues if i.code.startswith("DUPLICATE")), counts_of(summary)))
    assert results[0] == results[1]
    assert results[0][0] == [("DUPLICATE_COUNTED_AS_WRITER", "cap_0101"), ("DUPLICATE_COUNTED_AS_WRITER", "cap_0201")]


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


def test_grant_evidence_must_match_its_capture_method(registry):
    # Codex review of #12: a grant labelled SIGNED_PILOT_AGREEMENT with UI evidence was accepted.
    scenario = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "pilot_participant_signed_agreement.json")
    signed = scenario["events"][0]
    assert vcp.build_context(registry, scenario, fixture_mode=True).event_issues[signed["event_id"]] == []
    for change in ({"evidence": dict(signed["evidence"], kind="UI_INTERACTION")}, {"surface": "WEB"}):
        mutated = dict(scenario, events=[dict(copy.deepcopy(signed), **change)])
        assert vcp.build_context(registry, mutated, fixture_mode=True).event_issues[signed["event_id"]] == ["EVIDENCE_MISMATCH"]

    basics = vcp.load_json(vcp.CONSENT_DIR / "fixtures" / "scenarios" / "grant_deny_withdraw_basics.json")
    explicit = basics["events"][0]
    mutated = dict(basics, events=[dict(copy.deepcopy(explicit), evidence=dict(explicit["evidence"], kind="SIGNED_AGREEMENT"))])
    assert vcp.build_context(registry, mutated, fixture_mode=True).event_issues[explicit["event_id"]] == ["EVIDENCE_MISMATCH"]


def test_approved_purposes_need_every_related_gate_decided(registry, retention_ids):
    # Codex review of #12: only the gate names were checked, so third-party AI
    # processing could be approved with its API, model and processor gates open.
    ledger = approve_in(registry, "third_party_ai_processing")
    assert vcp.check_purposes(ledger, retention_ids, vcp.known_gates()) == []
    purpose = next(p for p in ledger["purposes"] if p["purpose_id"] == "third_party_ai_processing")
    purpose["approval"]["gate_decisions"] = purpose["approval"]["gate_decisions"][1:]
    found = vcp.check_purposes(ledger, retention_ids, vcp.known_gates())
    assert [(i.code, i.message.split()[0]) for i in found] == [("GATE_NOT_APPROVED", purpose["related_gates"][0])]
    del purpose["approval"]["gate_decisions"]
    assert len(vcp.check_purposes(ledger, retention_ids, vcp.known_gates())) == len(purpose["related_gates"])


def test_retired_purposes_keep_their_definition(registry, retention_ids):
    # Codex review of #12: retiring a purpose required wiping its scopes, recipients and retention.
    retired = approve_in(registry, "product_analytics")
    next(p for p in retired["purposes"] if p["purpose_id"] == "product_analytics")["status"] = "RETIRED"
    assert vcp.check_purposes(retired, retention_ids, vcp.known_gates()) == []
    not_offered = copy.deepcopy(registry)
    next(p for p in not_offered["purposes"] if p["purpose_id"] == "product_analytics")["status"] = "NOT_OFFERED"
    assert "INACTIVE_PURPOSE_HAS_USE" in codes(vcp.check_purposes(not_offered, retention_ids, vcp.known_gates()))

    purposes = purposes_by_key(retired)
    notices = copy.deepcopy(load("notices.json"))
    notice = notices["notices"][0]
    notice.update(purposes=[{"purpose_id": "product_analytics", "purpose_version": 1}],
                  copy=[c for c in notice["copy"] if c["purpose_id"] == "product_analytics"],
                  status="SUPERSEDED", effective_from="2026-01-01T00:00:00Z", effective_until="2026-06-01T00:00:00Z",
                  decision_ref="decision:n-1234")
    assert vcp.check_notices(notices, purposes) == []
    notice.update(status="ACTIVE", effective_until=None)
    assert codes(vcp.check_notices(notices, purposes)) == ["NOTICE_OFFERS_INACTIVE_PURPOSE"]


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
    decided.update(status="APPROVED", approval={"decision_ref": "decision:ret-policy", "decided_by_role": "owner",
                                                "decided_on": "2025-11-01T00:00:00Z"})
    for c in decided["classes"]:
        c.update(decision_status="DECIDED", decision_ref="decision:ret-1234", max_retention={"value": 30, "unit": "DAYS"})
    bind(decided)
    assert vcp.check_purpose_retention(ledger, decided) == [] and vcp.check_retention(decided) == []

    # Codex review of #12: a bare status edit approved the policy with no record, and
    # a policy approved after the purpose could not have governed its approval.
    unrecorded = dict(copy.deepcopy(decided), approval=None)
    del unrecorded["approval"]
    assert codes(vcp.check_retention(unrecorded)) == ["APPROVAL_WITHOUT_EVIDENCE"]
    assert codes(vcp.check_purpose_retention(ledger, unrecorded)) == ["PURPOSE_RETENTION_UNDECIDED"]
    late = copy.deepcopy(decided)
    late["approval"]["decided_on"] = "2026-06-01T00:00:00Z"
    assert codes(vcp.check_purpose_retention(ledger, late)) == ["PURPOSE_RETENTION_UNDECIDED"]
    decided["classes"][0].update(decision_status="PENDING_OWNER_DECISION", decision_ref=None,
                                 max_retention={"value": None, "unit": None})
    # Codex review of #12: an edit after approval keeps nothing of the old approval.
    assert codes(vcp.check_retention(decided)) == ["APPROVAL_CONTENT_MISMATCH", "APPROVED_WITH_PENDING_DECISIONS"]
    bind(decided)
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
    assert codes(vcp.check_lineage(undeclared_root, retention)) == [
        "HANDWRITING_ROOT_REQUIRED", "LINEAGE_UNREACHABLE", "UNDECLARED_ROOT"]
    # Codex review of #12: a handwriting root could be declassified or dropped.
    declassified = with_node(kind="upload_original", contains_handwriting=False, retention_class="analytics_events")
    assert codes(vcp.check_lineage(declassified, retention)) == ["HANDWRITING_ARTIFACT_DECLASSIFIED", "HANDWRITING_ROOT_REQUIRED"]
    dropped = copy.deepcopy(lineage)
    dropped["roots"], doomed, changed = ["upload_original"], {"pilot_capture"}, True
    while changed:  # remove pilot_capture and everything derived only from it
        changed = False
        for node in dropped["nodes"]:
            kept = [parent for parent in node["parents"] if parent not in doomed]
            if node["parents"] and not kept and node["artifact_kind"] not in doomed:
                doomed.add(node["artifact_kind"])
                changed = True
            node["parents"] = kept or node["parents"]
    dropped["nodes"] = [n for n in dropped["nodes"] if n["artifact_kind"] not in doomed]
    assert codes(vcp.check_lineage(dropped, retention)) == ["HANDWRITING_ARTIFACT_MISSING", "HANDWRITING_ROOT_REQUIRED"]
    # Codex review of #12: a derived handwriting kind could still be declassified and retained.
    for kind in ("provider_copy", "normalized_image", "premium_payload", "export_artifact"):
        declassified = with_node(kind=kind, contains_handwriting=False, retention_class="accounting_records",
                                 on_upstream_deletion="RETAIN_UNDER_SEPARATE_OBLIGATION")
        assert codes(vcp.check_lineage(declassified, retention)) == ["DELETION_ACTION_MISMATCH", "HANDWRITING_ARTIFACT_DECLASSIFIED"], kind
    assert codes(vcp.check_lineage(with_node(kind="export_artifact", on_upstream_deletion="RETAIN_UNDER_SEPARATE_OBLIGATION"),
                                   retention)) == ["DELETION_ACTION_MISMATCH", "HANDWRITING_RETAINED"]
    assert codes(vcp.check_lineage(with_node(kind="crop_overlay_thumbnail", retention_class="analytics_events"),
                                   retention)) == ["RETENTION_CLASS_UNDERSTATES_HANDWRITING"]


@pytest.mark.parametrize(
    ("kind", "changes", "expected"),
    [
        # Codex review of #12: only handwriting retention was checked, so revocation and processor deletion could be dropped.
        ("share_route", {"on_upstream_deletion": "DELETE"}, [("DELETION_ACTION_MISMATCH", "share_route")]),
        ("provider_copy", {"on_upstream_deletion": "DELETE"}, [("DELETION_ACTION_MISMATCH", "provider_copy")]),
        ("analysis_run", {"on_upstream_deletion": "RETAIN_UNDER_SEPARATE_OBLIGATION"}, [("DELETION_ACTION_MISMATCH", "analysis_run")]),
        ("share_route", {"parents": ["report_revision"]}, [("LINEAGE_EDGE_MISSING", "share_route")]),
        ("comparison_report", {"parents": ["report_revision", "export_artifact"]}, []),  # adding an edge only widens deletion
    ],
)
def test_deletion_lineage_pins_actions_and_edges(kind, changes, expected):
    lineage = copy.deepcopy(load("deletion_lineage.json"))
    retention = {c["class_id"]: c for c in load("retention.json")["classes"]}
    next(n for n in lineage["nodes"] if n["artifact_kind"] == kind).update(changes)
    assert [(i.code, i.where) for i in vcp.check_lineage(lineage, retention)] == expected


def test_deletion_lineage_kinds_and_approval_are_reviewed():
    lineage = load("deletion_lineage.json")
    retention = {c["class_id"]: c for c in load("retention.json")["classes"]}
    assert set(vcp.LINEAGE_PLAN) == {n["artifact_kind"] for n in lineage["nodes"]}
    extra = copy.deepcopy(lineage)
    extra["nodes"].append({"artifact_kind": "ocr_text", "parents": ["normalized_image"], "retention_class": "derived_assets",
                           "contains_handwriting": False, "on_upstream_deletion": "DELETE", "notes": "Unreviewed."})
    assert [(i.code, i.where) for i in vcp.check_lineage(extra, retention)] == [("UNREVIEWED_ARTIFACT_KIND", "ocr_text")]
    dropped = dict(copy.deepcopy(lineage), nodes=[n for n in lineage["nodes"] if n["artifact_kind"] != "share_route"])
    assert [(i.code, i.where) for i in vcp.check_lineage(dropped, retention)] == [("LINEAGE_ARTIFACT_MISSING", "share_route")]

    # Codex review of #12: a bare status edit approved the deletion plan with no record.
    approved = dict(copy.deepcopy(lineage), status="APPROVED")
    assert vcp.SchemaSet().validate(approved, "deletion-lineage.schema.json") == []
    assert codes(vcp.check_lineage(approved, retention)) == ["APPROVAL_WITHOUT_EVIDENCE"]
    approved["approval"] = {"decision_ref": "decision:lineage", "decided_by_role": "owner", "decided_on": "2026-10-01T00:00:00Z"}
    bind(approved)
    assert vcp.SchemaSet().validate(approved, "deletion-lineage.schema.json") == []
    assert vcp.check_lineage(approved, retention) == []
    approved["nodes"][0]["notes"] = "Edited after approval."
    assert codes(vcp.check_lineage(approved, retention)) == ["APPROVAL_CONTENT_MISMATCH"]


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
                        "reviewed_on": "2026-10-01T00:00:00Z", "expires_on": None, "archive_sha256": "0" * 64}
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
    assert codes(vcp.check_pilot_gate(approved, protocol, notices, purposes)) == [
        "APPROVAL_CONTENT_MISMATCH", "APPROVED_WITH_PENDING_DECISIONS"]
    bind(approved)
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
    found = vcp.check_pilot_gate(bind(stripped), protocol, notices, purposes)
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
    approved = approved_protocol(protocol, decide_rights=False)
    found = vcp.check_protocol(approved, purposes_by_key(registry))
    assert codes(found) == ["PROTOCOL_APPROVED_WITH_PENDING_RIGHTS"]
    assert len(found) == len(protocol["tasks"])
    for task in approved["tasks"]:
        task["rights"].update(decision_status="DECIDED", decision_ref="decision:prompt-rights")
    # Deciding the rights changes the protocol, so its approval must be recorded again.
    assert codes(vcp.check_protocol(approved, purposes_by_key(registry))) == ["APPROVAL_CONTENT_MISMATCH"]
    assert vcp.check_protocol(bind(approved), purposes_by_key(registry)) == []


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
