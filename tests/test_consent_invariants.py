"""Adversarial tests of the actual public boundaries, not just isolated validators.

All approvals, attestations and participants below are test inventions. None is
written into production registry files or claimed as real deletion evidence.
"""
import copy
import hashlib
import itertools
import random
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

import test_consent_protocol as f
import validate_consent_protocol as v
from consent_primitives import ValidationResult, rooted_nodes, unique_index


def bundle():
    return {
        "registry": f.pilot_ledger(f.load("purposes.json")), "notices": f.active_pilot_notices(),
        "protocol": f.approved_protocol(v.load_json(v.COLLECTION_DIR / "manifest.json")),
        "retention": f.approved_retention(), "lineage": f.approved_lineage(), "gate": f.approved_gate(),
        "sources": dict(f.load("source_rights.json"), sources=list(f.cleared_sources("engineering_testing").values())),
    }


def rebind_all(documents):
    """Model new TEST decisions after mutations; semantic invalidity must still fail.

    This is deliberately never used by the production compiler or the old
    regression adapter. A matching hash does not make invalid policy valid.
    """
    for p in documents["registry"]["purposes"]:
        if p.get("approval"):
            f.bind(p)
    for n in documents["notices"]["notices"]:
        if n["status"] != "DRAFT":
            f.bind_notice(n)
    for s in documents["sources"]["sources"]:
        if "review" in s:
            f.bind_review(s)
    for name in ("registry", "protocol", "retention", "lineage", "gate"):
        if documents[name].get("approval"):
            f.bind(documents[name])


def ready(documents=None, *, collection_dir=v.COLLECTION_DIR, manifest=None):
    documents = bundle() if documents is None else documents
    compiled = v.compile_release_policy(**documents, collection_dir=collection_dir)
    assert compiled.issues == (), compiled.issues
    fixture = f.valid_lineage()
    manifest = dict(copy.deepcopy(fixture["manifest"]), synthetic=False) if manifest is None else manifest
    context = v.collection_consent_context(compiled.value, manifest, fixture["consent_log"])
    evidence = f.publication_evidence(compiled.value, manifest, context, f.CUTOFF)
    return compiled.value, manifest, context, evidence


def release(policy, manifest, context, evidence, **kwargs):
    return v.check_collection_manifest(manifest, policy, context, publish_at=kwargs.pop("publish_at", f.CUTOFF),
                                       release_evidence=evidence, **kwargs)


def test_complete_control_has_exact_membership_and_no_failures():
    p, m, c, e = ready()
    result = release(p, m, c, e)
    assert not result.issues and result.value is not None
    assert f.counts_of(result.value) == (3, 6, 7)
    assert len(result.value.writer_ids) == 3 and len(result.value.specimen_ids) == 6 and len(result.value.capture_ids) == 7
    assert result.value.manifest_sha256 == v.digest(m)
    assert result.value.policy_sha256 == p.fingerprint
    assert result.value.evidence_sha256 == v.digest(e)
    with pytest.raises((FrozenInstanceError, TypeError)):
        result.value.captures = 999
    with pytest.raises(TypeError):
        result.value.by_task["copy_en"]["writers"] = 999


@pytest.mark.parametrize("key", list(bundle()))
def test_every_policy_dependency_is_required(key):
    docs = bundle()
    del docs[key]
    result = v.compile_release_policy(**docs)
    assert result.value is None and "MISSING_POLICY_DOCUMENT" in f.codes(result.issues)


@pytest.mark.parametrize("name", ["registry", "protocol", "retention", "lineage", "gate"])
def test_every_configuration_approval_is_required(name):
    docs = bundle()
    docs[name].pop("approval")
    result = v.compile_release_policy(**docs)
    assert result.value is None and "APPROVAL_WITHOUT_EVIDENCE" in f.codes(result.issues)


DUPLICATE_ROWS = [
    ("registry", "purposes", "DUPLICATE_PURPOSE"),
    ("notices", "notices", "DUPLICATE_NOTICE"),
    ("retention", "classes", "DUPLICATE_RETENTION_CLASS"),
    ("lineage", "nodes", "DUPLICATE_ARTIFACT_KIND"),
    ("sources", "sources", "DUPLICATE_SOURCE"),
    ("gate", "decisions", "DUPLICATE_DECISION"),
    ("protocol", "tasks", "DUPLICATE_TASK"),
    ("protocol", "session_plan", "SESSION_PLAN_ORDER"),
    ("protocol", "guidance", "DUPLICATE_GUIDANCE"),
]


@pytest.mark.parametrize("name,rows,code", DUPLICATE_ROWS)
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_canonical_keys_are_fatal_before_indexing(name, rows, code, reverse):
    docs = bundle()
    original = docs[name][rows][0]
    # Both byte-identical duplicates and conflicting definitions are ambiguous identities.
    duplicate = copy.deepcopy(original)
    for field in ("summary", "notes", "name"):
        if field in duplicate and isinstance(duplicate[field], str):
            duplicate[field] += " conflicting definition"
            break
    docs[name][rows].append(duplicate)
    if reverse:
        docs[name][rows].reverse()
    rebind_all(docs)
    result = v.compile_release_policy(**docs)
    assert result.value is None and code in f.codes(result.issues)


@pytest.mark.parametrize("name,rows,_code", DUPLICATE_ROWS)
def test_array_permutation_with_fresh_test_decisions_preserves_results(name, rows, _code):
    docs = bundle()
    docs[name][rows].reverse()
    rebind_all(docs)
    p, m, c, e = ready(docs)
    assert f.counts_of(release(p, m, c, e).value) == (3, 6, 7)


@pytest.mark.parametrize("field", ["decision_ref", "decided_on", "decided_by_role"])
@pytest.mark.parametrize("name", ["registry", "protocol", "retention", "lineage", "gate"])
def test_mutating_decision_metadata_without_new_binding_fails(name, field):
    docs = bundle()
    docs[name]["approval"][field] = {
        "decision_ref": "decision:different-owner-decision", "decided_on": "2025-10-01T00:00:00Z",
        "decided_by_role": "another-role",
    }[field]
    result = v.compile_release_policy(**docs)
    assert result.value is None and "APPROVAL_CONTENT_MISMATCH" in f.codes(result.issues)


@pytest.mark.parametrize("field", ["decided_on", "decided_by_role"])
def test_notice_activation_needs_complete_bound_metadata(field):
    docs = bundle()
    notice = next(n for n in docs["notices"]["notices"] if n["status"] == "ACTIVE")
    notice[field] = None
    notice["content_sha256"] = v.notice_digest(notice)
    result = v.compile_release_policy(**docs)
    assert result.value is None and "NOTICE_ACTIVE_WITHOUT_DECISION" in f.codes(result.issues)


def test_even_rebound_activation_cannot_predate_its_decision():
    docs = bundle()
    notice = next(n for n in docs["notices"]["notices"] if n["status"] == "ACTIVE")
    notice["decided_on"] = "2026-02-01T00:00:00Z"
    notice["content_sha256"] = v.notice_digest(notice)
    assert not v.notice_decision_bound(notice)
    result = v.compile_release_policy(**docs)
    assert result.value is None and "NOTICE_ACTIVATION_BACKDATED" in f.codes(result.issues)


@pytest.mark.parametrize("mutation,code", [
    (lambda d: d["retention"]["classes"][0].update(max_retention={"value": None, "unit": "EVENT_BOUND"}, ends_when=[]), "SCHEMA"),
    (lambda d: d["retention"]["classes"][0].update(max_retention={"value": None, "unit": "DAYS"}), "RETENTION_UNIT_MISMATCH"),
    (lambda d: d["registry"]["purposes"][0]["retention_classes"].append("unknown_class"), "UNKNOWN_RETENTION_CLASS"),
    (lambda d: d["lineage"]["nodes"][0].update(on_upstream_deletion="RETAIN_UNDER_SEPARATE_OBLIGATION"), "DELETION_ACTION_MISMATCH"),
    (lambda d: d["lineage"]["nodes"][0].update(contains_handwriting=False), "HANDWRITING_ROOT_REQUIRED"),
    (lambda d: d["protocol"].update(gate="wrong_gate"), "SCHEMA"),
    (lambda d: d["protocol"]["tasks"][0]["rights"].update(decision_status="PENDING_OWNER_DECISION", decision_ref=None), "PROTOCOL_APPROVED_WITH_PENDING_RIGHTS"),
    (lambda d: d["gate"]["decisions"][0].update(status="PENDING_OWNER_DECISION", decision_ref=None), "APPROVED_WITH_PENDING_DECISIONS"),
])
def test_a_matching_digest_never_replaces_semantic_validation(mutation, code):
    docs = bundle()
    mutation(docs)
    rebind_all(docs)
    result = v.compile_release_policy(**docs)
    assert result.value is None and code in f.codes(result.issues)


def test_retention_must_precede_the_purposes_it_governs():
    docs = bundle()
    docs["retention"]["approval"]["decided_on"] = "2026-01-05T00:00:00Z"
    rebind_all(docs)
    result = v.compile_release_policy(**docs)
    assert result.value is None and "PURPOSE_RETENTION_UNDECIDED" in f.codes(result.issues)


@pytest.mark.parametrize("field", ["registry", "protocol", "retention", "lineage", "gate", "notices", "sources"])
@pytest.mark.parametrize("bad", [None, [], True, "APPROVED", 42])
def test_malformed_policy_shapes_fail_without_traceback(field, bad):
    docs = bundle()
    docs[field] = bad
    result = v.compile_release_policy(**docs)
    assert result.value is None and result.issues


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf"), b"bytes", {1: "numeric key"}])
def test_non_json_policy_values_fail_without_traceback(bad):
    docs = bundle()
    docs["protocol"]["exclusions"].append(bad)
    result = v.compile_release_policy(**docs)
    assert result.value is None and "NON_JSON_INPUT" in f.codes(result.issues)


def test_cyclic_python_input_is_not_a_json_contract():
    docs = bundle()
    docs["protocol"]["exclusions"].append(docs["protocol"])
    result = v.compile_release_policy(**docs)
    assert result.value is None and "NON_JSON_INPUT" in f.codes(result.issues)


@pytest.mark.parametrize("kind", ["prompt", "guidance"])
def test_assets_are_checked_before_compilation_and_again_at_release(tmp_path, kind):
    import shutil
    root = tmp_path / "collection"
    shutil.copytree(v.COLLECTION_DIR, root)
    docs = bundle()
    p, m, c, e = ready(docs, collection_dir=root)
    relative = docs["protocol"]["tasks"][0]["prompt_file"] if kind == "prompt" else docs["protocol"]["guidance"][0]["file"]
    (root / relative).write_bytes((root / relative).read_bytes() + b"\nChanged after review.\n")
    compiled = v.compile_release_policy(**docs, collection_dir=root)
    assert compiled.value is None and ("PROMPT_HASH_MISMATCH" if kind == "prompt" else "GUIDANCE_HASH_MISMATCH") in f.codes(compiled.issues)
    result = release(p, m, c, e)
    assert result.value is None and "PROTOCOL_ASSET_MISMATCH" in f.codes(result.issues)


@pytest.mark.parametrize("relative", ["../outside.md", "/etc/passwd", "prompts/../../outside.md"])
def test_asset_paths_cannot_escape_the_collection_root(relative):
    docs = bundle()
    docs["protocol"]["tasks"][0]["prompt_file"] = relative
    rebind_all(docs)
    result = v.compile_release_policy(**docs)
    assert result.value is None and (set(f.codes(result.issues)) & {"MISSING_PROMPT", "SCHEMA"})


def test_asset_symlinks_cannot_substitute_other_files(tmp_path):
    import shutil
    root = tmp_path / "collection"
    shutil.copytree(v.COLLECTION_DIR, root)
    docs = bundle()
    target = root / docs["protocol"]["tasks"][0]["prompt_file"]
    external = tmp_path / "identical-but-outside.md"
    external.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(external)
    result = v.compile_release_policy(**docs, collection_dir=root)
    assert result.value is None and "MISSING_PROMPT" in f.codes(result.issues)


def test_compiled_snapshots_cannot_be_changed_through_the_original_dicts():
    docs = bundle()
    p, m, c, e = ready(docs)
    original = p.fingerprint
    docs["protocol"]["status"] = "DRAFT_PENDING_OWNER_REVIEW"
    assert p.fingerprint == original and p.documents["protocol"]["status"] == "APPROVED"
    assert release(p, m, c, e).value is not None
    with pytest.raises(TypeError):
        p.documents["protocol"]["status"] = "DRAFT_PENDING_OWNER_REVIEW"
    with pytest.raises(TypeError):
        p.documents["purposes"]["purposes"].append({})
    with pytest.raises(TypeError):
        c.valid.clear()
    with pytest.raises((FrozenInstanceError, TypeError)):
        c.policy_sha256 = "0" * 64
    with pytest.raises(TypeError):
        v.ReleasePolicy()
    with pytest.raises(TypeError):
        v.AuthoritativeConsentContext()
    with pytest.raises(TypeError):
        v.ApprovedCollection()
    from dataclasses import replace
    with pytest.raises(TypeError):
        replace(c, valid=[])


def test_no_uncompiled_or_cross_manifest_context_can_release():
    p, m, c, e = ready()
    raw = v.check_collection_manifest(m, p.documents, c, publish_at=f.CUTOFF, release_evidence=e)
    assert raw.value is None and "UNCOMPILED_POLICY" in f.codes(raw.issues)
    fixture = f.valid_lineage()
    raw_context = v.collection_consent_context(f.pilot_ledger(f.load("purposes.json")), m, fixture["consent_log"], notices=f.active_pilot_notices())
    result = release(p, m, raw_context, e)
    assert result.value is None and "CONSENT_CONTEXT_MISMATCH" in f.codes(result.issues)
    m["specimens"][0]["instrument"] = "PENCIL"
    result = release(p, m, c, e)
    assert result.value is None and "CONSENT_CONTEXT_MISMATCH" in f.codes(result.issues)


@pytest.mark.parametrize("field", ["policy_sha256", "manifest_sha256", "consent_events_sha256", "checked_at"])
def test_rebound_attestation_for_other_inputs_or_time_is_not_release_evidence(field):
    p, m, c, e = ready()
    e[field] = "2026-02-01T00:00:00Z" if field == "checked_at" else "0" * 64
    f.bind(e)
    result = release(p, m, c, e)
    assert result.value is None and (set(f.codes(result.issues)) & {"PUBLICATION_EVIDENCE_MISMATCH", "STALE_PUBLICATION_EVIDENCE"})


@pytest.mark.parametrize("check", v.PUBLICATION_CHECKS)
@pytest.mark.parametrize("state", ["PENDING", "FAIL"])
def test_deletion_and_withdrawal_evidence_checks_are_all_mandatory(check, state):
    p, m, c, e = ready()
    e["checks"][check]["status"] = state
    f.bind(e)
    result = release(p, m, c, e)
    assert result.value is None and "PUBLICATION_CHECK_FAILED" in f.codes(result.issues)


def test_no_deletion_attestation_means_no_release():
    p, m, c, _e = ready()
    result = release(p, m, c, None)
    assert result.value is None and "PUBLICATION_EVIDENCE_REQUIRED" in f.codes(result.issues)


@pytest.mark.parametrize("bad", [None, {}, [], 1, "manifest"])
def test_malformed_manifest_is_a_rejection_not_an_exception(bad):
    p, _m, c, e = ready()
    result = release(p, bad, c, e)
    assert result.value is None and result.issues


@pytest.mark.parametrize("rows,key", [("writers", "writer_id"), ("writers", "enrollment_id"), ("specimens", "specimen_id"), ("captures", "capture_id")])
def test_ambiguous_manifest_identity_cannot_return_an_approved_value(rows, key):
    p, m, _c, _e = ready()
    m[rows][1][key] = m[rows][0][key]
    c = v.collection_consent_context(p, m, f.valid_lineage()["consent_log"])
    e = f.publication_evidence(p, m, c, f.CUTOFF)
    result = release(p, m, c, e)
    assert result.value is None and "DUPLICATE_ID" in f.codes(result.issues)


def test_manifest_and_event_permutations_preserve_membership():
    p, m, _c, _e = ready()
    fixture = f.valid_lineage()
    expected = None
    for seed in range(12):
        rng = random.Random(seed)
        mm, log = copy.deepcopy(m), copy.deepcopy(fixture["consent_log"])
        for rows in ("writers", "specimens", "captures"):
            rng.shuffle(mm[rows])
        rng.shuffle(log["events"])
        ctx = v.collection_consent_context(p, mm, log)
        ev = f.publication_evidence(p, mm, ctx, f.CUTOFF)
        result = release(p, mm, ctx, ev)
        assert not result.issues
        actual = (result.value.writer_ids, result.value.specimen_ids, result.value.capture_ids)
        expected = actual if expected is None else expected
        assert actual == expected


def test_overlapping_links_block_the_writer_in_the_reference_evaluator_too():
    scenario = v.load_json(v.CONSENT_DIR / "fixtures/scenarios/relink_keeps_earlier_withdrawal.json")
    registry = f.load("purposes.json")
    scenario["writers"][0]["previous_account_links"][0]["unlinked_at"] = "2099-01-01T00:00:00Z"
    context = v.build_context(registry, scenario, fixture_mode=True)
    event = scenario["events"][0]
    assert not v.has_authority(event, context)
    assert v.evaluate_permission(context, event["subject"], event["purpose"], event["scope"], f.CUTOFF) == "INVALID_AUTHORITY"
    assert "ACCOUNT_LINK_INCONSISTENT" in f.codes(v.run_scenario(registry, scenario))


def test_authorized_but_malformed_withdrawal_does_not_revive_an_old_grant():
    fixture = f.valid_lineage()
    log = copy.deepcopy(fixture["consent_log"])
    withdrawal = copy.deepcopy(log["events"][0])
    withdrawal.update(event_type="WITHDRAW", event_id="evt_badwithdraw", capture_method="WITHDRAWAL_CONTROL",
                      recorded_at="2026-02-15T00:00:00Z", effective_at="2026-02-15T00:00:00Z")
    withdrawal["notice"]["notice_id"] = "notice.unknown"
    log["events"].append(withdrawal)
    p, m, _c, _e = ready()
    context = v.collection_consent_context(p, m, log)
    assert "AMBIGUOUS_RESTRICTION" in f.codes(context.issues)
    evidence = f.publication_evidence(p, m, context, f.CUTOFF)
    assert release(p, m, context, evidence).value is None


@pytest.mark.parametrize("cycle", [False, True])
def test_iterative_ancestry_propagates_all_invalidity_at_large_depth(cycle):
    parents = {str(i): None if i == 0 else str(i - 1) for i in range(10000)}
    if cycle:
        parents["0"] = "9999"
        assert rooted_nodes(parents, set()) == set()
    else:
        assert rooted_nodes(parents, set()) == set(parents)
        assert rooted_nodes(parents, {"12"}) == {str(i) for i in range(12)}
    assert rooted_nodes({"child": "absent"}, set()) == set()


def test_ten_thousand_repeat_captures_through_the_whole_public_release():
    fixture = f.valid_lineage()
    m = dict(copy.deepcopy(fixture["manifest"]), synthetic=False)
    root = copy.deepcopy(m["captures"][0])
    sid = root["specimen_id"]
    m["captures"] = [c for c in m["captures"] if c["specimen_id"] != sid]
    for i in range(1, 10001):
        m["captures"].append(dict(root, capture_id=f"cap_deep{i:05}", capture_index=i,
                                  content_sha256=hashlib.sha256(f"deep-{i}".encode()).hexdigest(),
                                  repeat_of_capture_id=None if i == 1 else f"cap_deep{i-1:05}"))
    m["claimed_counts"]["captures"] = len(m["captures"]) - 1  # one deliberately unsupported context
    p, m, c, e = ready(manifest=m)
    result = release(p, m, c, e)
    assert not result.issues and result.value.captures == len(m["captures"]) - 1
    assert len(result.value.capture_ids) == result.value.captures


def test_small_state_model_covers_scheduled_grants_and_later_restrictions():
    fixture = f.valid_lineage()
    template = fixture["consent_log"]["events"][0]
    origin = v.parse_timestamp("2026-02-01T00:00:00Z")
    state = {"GRANT": "PERMITTED", "DENY": "DENIED", "WITHDRAW": "WITHDRAWN"}
    for kinds in itertools.product(state, repeat=3):
        for delay in (0, 4):
            events = []
            for i, kind in enumerate(kinds, 1):
                event = copy.deepcopy(template)
                recorded = origin + timedelta(days=i)
                effective = recorded + timedelta(days=delay if kind == "GRANT" else 0)
                event.update(event_id=f"evt_model{i:04}", event_type=kind,
                             recorded_at=recorded.isoformat().replace("+00:00", "Z"),
                             effective_at=effective.isoformat().replace("+00:00", "Z"))
                events.append(event)
            # Independent finite-state oracle, compared for both ledger orders.
            for ordered in (events, list(reversed(events))):
                log = dict(fixture["consent_log"], events=ordered)
                ctx = v.collection_consent_context(f.load("purposes.json"), fixture["manifest"], log, fixture_mode=True)
                assert not ctx.issues and not any(ctx.event_issues.values())
                for day in (0, 1, 2, 3, 5, 8):
                    active = [i for i, kind in enumerate(kinds, 1) if i + (delay if kind == "GRANT" else 0) <= day]
                    expected = state[kinds[max(active)-1]] if active else "NOT_ASKED"
                    got = v.evaluate_permission(ctx, template["subject"], template["purpose"], template["scope"], origin + timedelta(days=day))
                    assert got == expected, (kinds, delay, day, got, expected)


def test_validation_results_cannot_hold_both_failure_and_value():
    with pytest.raises(ValueError):
        ValidationResult({}, (v.Issue("BAD", "test", "failure"),))
    with pytest.raises(ValueError):
        ValidationResult(None)
    result = unique_index([{"id": 1}, {"id": 1}], lambda row: row["id"], code="DUPLICATE", where="test")
    assert result.value is None and result.issues


@pytest.mark.parametrize("field", ["manifest", "ledger", "registry"])
@pytest.mark.parametrize("bad", [None, [], {}, True, "not a contract"])
def test_collection_context_rejects_malformed_raw_inputs(field, bad):
    docs = bundle()
    fixture = f.valid_lineage()
    registry, manifest, ledger = docs["registry"], fixture["manifest"], fixture["consent_log"]
    if field == "registry":
        registry = bad
    elif field == "manifest":
        manifest = bad
    else:
        ledger = bad
    context = v.collection_consent_context(registry, manifest, ledger)
    assert context.issues and not isinstance(context, v.AuthoritativeConsentContext)


@pytest.mark.parametrize("extras", [None, True, "bad", [{}], [{"purpose_id": "missing_version"}]])
def test_extra_purposes_cannot_bypass_context_schema_validation(extras):
    scenario = f.load("fixtures/scenarios/grant_deny_withdraw_basics.json")
    scenario["extra_purposes"] = extras
    context = v.build_context(f.load("purposes.json"), scenario, fixture_mode=True)
    assert context.issues and not context.valid


@pytest.mark.parametrize("actor", ["SYSTEM", "SUPPORT_STAFF"])
def test_malformed_authorized_system_or_support_withdrawal_blocks_prior_grant(actor):
    scenario = f.load("fixtures/scenarios/grant_deny_withdraw_basics.json")
    withdrawal = next(e for e in scenario["events"] if e["actor"]["kind"] == "SYSTEM")
    if actor == "SUPPORT_STAFF":
        withdrawal["actor"] = {"kind": actor, "id": "staff_0001"}
        withdrawal["capture_method"] = "VERIFIED_REQUEST"
        withdrawal["derived_from"] = {"kind": "SUPPORT_REQUEST", "id": "req_0001"}
    withdrawal["notice"]["notice_id"] = "notice.unknown"
    context = v.build_context(f.load("purposes.json"), scenario, fixture_mode=True)
    assert "AMBIGUOUS_RESTRICTION" in f.codes(context.issues)
    assert v.evaluate_permission(context, scenario["events"][0]["subject"], scenario["events"][0]["purpose"],
                                 scenario["events"][0]["scope"], f.CUTOFF) != "PERMITTED"
