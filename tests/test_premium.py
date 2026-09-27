"""T15: Premium packet/schema compiler, output validation and bounded attempts."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import generate_report_fixtures as fixtures
from princess_app.adapters.fakes import FakeClock, FakePremiumModel, SequentialIds
from princess_app.application.permissions import InMemoryPermissionStore, PermissionService
from princess_app.application.premium import (
    DEFAULT_CANDIDATE_PRODUCERS,
    GENERATOR_DISPOSITIONS,
    SUPPORTED,
    Candidate,
    InMemoryOverlayPublisher,
    InMemorySpendBudget,
    NotApplicable,
    Outcome,
    PremiumJob,
    PremiumRunner,
    answer_support,
    compile_packet,
    load_interpretation_database,
    output_schema,
    validate_output,
)
from princess_app.application.premium.database import DEFAULT_PATH
from princess_app.application.premium.service import (
    IMAGE_INPUT_TOKEN_BOUND,
    MAX_OUTPUT_TOKENS,
    billable_token_bound,
)
from princess_app.application.reports import InMemoryReportStore
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.permissions import Decision, Scope
from princess_app.domain.reports import assemble_report
from princess_app.ports import model as port
from princess_app.ports.base import (
    AmbiguousOutcome,
    CallContext,
    Environment,
    InvalidInput,
    PermanentFailure,
    RateLimited,
    Unsupported,
)
from princess_app.ports.storage import StoredObject

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
NOTICE = "notice.consent-choices:1"
DB = load_interpretation_database()
CASES = json.loads((ROOT / "evaluation" / "premium" / "adversarial_cases.json").read_text())["cases"]
IMAGE = StoredObject("asset_1", "v1", "a" * 64, 1000, "image/png")


def report():
    reference = fixtures.load("analysis-reference.synthetic.json")
    evidence = build_evidence_bundle(fixtures.load("evidence-payload.synthetic.json"), reference, "evidence_1").value
    return assemble_report(report_id="report_1", analysis=reference, result=fixtures.load("engine-result.synthetic.json"),
                           created_at=T0, locale="en", evidence=evidence).value


REPORT = report()
OWNER = REPORT.data["analysis"]["owner_id"]


def compilation(image="asset_1", **kwargs):
    kwargs.setdefault("allow_inactive", True)  # T26 is reviewed but inactive; tests exercise it explicitly
    return compile_packet(REPORT, DB, packet_id="packet_1", created_at=T0, image_asset_id=image, **kwargs)


def well_behaved(model_input):
    """What a compliant model returns: one confident answer, the rest honestly unassessed."""
    model_input = json.loads(json.dumps(model_input, default=dict))  # the provider sees plain JSON
    questions = model_input["questions"]
    first = questions[0]
    answers = [{"question_id": first["question_id"], "answer_state": "ANSWERED",
                "selected_candidate_ids": [first["candidates"][0]["candidate_id"]],
                "support_fact_ids": first["support_fact_ids"][:1],
                "prose": "Form and movement read as evenly matched across the page."}]
    answers += [{"question_id": q["question_id"], "answer_state": "NOT_ASSESSABLE", "selected_candidate_ids": [],
                 "support_fact_ids": [], "prose": None} for q in questions[1:]]
    return {"contract_version": "1.0.0", "packet_id": model_input["packet_id"],
            "output_schema_version": model_input["output_schema_version"], "answers": answers,
            "soft_fields": [{"field_id": "SOFT_LIMITATION",
                             "text": "The proxy measures are uncalibrated and no reference cohort applies.",
                             "support_fact_ids": []}]}


# --- packet -----------------------------------------------------------------
def test_packet_includes_only_answerable_questions_and_explains_every_omission():
    c = compilation()
    packet = c.packet.to_dict()
    pack = DB.packs["PREMIUM_INDIVIDUAL_GRAPHIC_V1"]
    included = [q["question_id"] for q in packet["questions"]]
    omitted = [o.item_id for o in c.omissions if o.item_id.startswith("Q_")]
    assert sorted(included + omitted) == sorted(pack["question_ids"]) and not set(included) & set(omitted)
    reasons = {o.item_id: (o.reason, o.detail) for o in c.omissions}
    assert reasons["Q_CTX_TASK"] == ("not_model_answered", "USER_OR_REVIEWER")
    assert reasons["Q_GLOBAL_EVIDENCE_CONFLICT"] == (
        "candidate_generator_unsupported", "conflict_detector_unavailable")
    assert reasons["Q_SPACE_MARGINS"] == ("missing_input", "VERIFIED_PAGE_BOUNDARIES")
    assert reasons["Q_FORM_ORNAMENT"] == ("candidate_generator_unsupported", "glyph_feature_not_implemented")
    assert reasons["Q_HIERARCHY_MAIN"] == (
        "candidate_generator_unsupported", "graphic_sign_detector_unavailable")
    assert reasons["Q_FORM_LOOPS"] == ("missing_input", "IDENTIFIED_LOOP_EXAMPLES")
    assert reasons["SOFT_GRAPHIC_PORTRAIT"] == ("missing_support", "SUPPLIED_GRAPHIC_SIGNS")
    assert all(DB.questions[q].model_call_role == "ANSWER" for q in included)
    assert packet["report_digest"] == REPORT.digest and packet["interpretation_database_sha256"] == DB.sha256
    assert set(c.soft_field_limits) == {"SOFT_LIMITATION"}


def test_packet_is_deterministic_and_the_model_input_is_minimized():
    a, b = compilation(), compilation()
    assert a.packet.digest == b.packet.digest and a.model_input_digest == b.model_input_digest
    text = json.dumps(a.model_input)
    for private in (OWNER, "report_1", "asset_1", REPORT.digest):
        assert private not in text
    facts = {f["fact_id"] for f in a.model_input["facts"]}
    assert facts == set(a.packet.data["allowed_fact_ids"])
    assert all(f["availability"] in ("READY", "UNCALIBRATED") for f in a.model_input["facts"])


def test_without_an_authorized_image_nothing_is_asked():
    with pytest.raises(NotApplicable) as err:
        compilation(image=None)
    assert err.value.reason == "authorized_image_unavailable"
    assert "AUTHORIZED_IMAGE" in DB.packs["PREMIUM_INDIVIDUAL_GRAPHIC_V1"]["preconditions"]


def test_default_dynamic_registry_is_exhaustive_for_the_individual_pack():
    pack = DB.packs["PREMIUM_INDIVIDUAL_GRAPHIC_V1"]
    expected = {}
    for question_id in pack["question_ids"]:
        spec = DB.questions[question_id]
        if spec.model_call_role == "ANSWER" and spec.selection_domain == "DYNAMIC":
            if spec.generator_id in expected:
                assert expected[spec.generator_id] == spec.candidate_kind
            expected[spec.generator_id] = spec.candidate_kind
    assert set(expected) == set(GENERATOR_DISPOSITIONS)
    for generator_id, candidate_kind in expected.items():
        assert GENERATOR_DISPOSITIONS[generator_id].candidate_kind == candidate_kind
    assert {generator_id for generator_id, disposition in GENERATOR_DISPOSITIONS.items()
            if disposition.state == SUPPORTED} == {
                "GEN_LINE_EDGE_TREND_V1", "GEN_INK_APPEARANCE_FACT_V1", "GEN_THICKNESS_FACT_V1"}


def test_supported_fact_producers_are_deterministic_zero_safe_and_fail_closed():
    facts = {
        "fact.start": {"feature_id": "LINE_START_DRIFT", "value": 0.0},
        "fact.end": {"feature_id": "LINE_END_DRIFT", "value": -0.2},
        "fact.darkness_cv": {"feature_id": "INK_DARKNESS_CV", "value": 0.0},
        "fact.darkness_mean": {"feature_id": "INK_DARKNESS_MEAN", "value": 0.7},
        "fact.width_mean": {"feature_id": "STROKE_WIDTH_MEAN", "value": 0.0},
        "fact.width_cv": {"feature_id": "STROKE_WIDTH_CV", "value": 0.1},
    }
    line = tuple(DEFAULT_CANDIDATE_PRODUCERS["GEN_LINE_EDGE_TREND_V1"](facts))
    assert [(c.candidate_id, c.kind, c.support_fact_ids) for c in line] == [
        ("GEN_LINE_EDGE_TREND_V1:LINE_START_DRIFT", "LINE_EDGE_TREND", ("fact.start",)),
        ("GEN_LINE_EDGE_TREND_V1:LINE_END_DRIFT", "LINE_EDGE_TREND", ("fact.end",)),
    ]
    darkness = tuple(DEFAULT_CANDIDATE_PRODUCERS["GEN_INK_APPEARANCE_FACT_V1"](facts))
    assert [(c.candidate_id, c.kind, c.support_fact_ids) for c in darkness] == [
        ("GEN_INK_APPEARANCE_FACT_V1:INK_DARKNESS_VARIATION", "INK_APPEARANCE_FACT",
         ("fact.darkness_cv", "fact.darkness_mean")),
    ]
    width = tuple(DEFAULT_CANDIDATE_PRODUCERS["GEN_THICKNESS_FACT_V1"](facts))
    assert [(c.candidate_id, c.kind, c.support_fact_ids) for c in width] == [
        ("GEN_THICKNESS_FACT_V1:STROKE_WIDTH_PROFILE", "THICKNESS_FACT",
         ("fact.width_mean", "fact.width_cv")),
    ]
    assert not DEFAULT_CANDIDATE_PRODUCERS["GEN_INK_APPEARANCE_FACT_V1"]({
        "fact.mean": {"feature_id": "INK_DARKNESS_MEAN", "value": 0.0}})
    assert not DEFAULT_CANDIDATE_PRODUCERS["GEN_THICKNESS_FACT_V1"]({
        "fact.cv": {"feature_id": "STROKE_WIDTH_CV", "value": 0.0}})
    assert line == tuple(DEFAULT_CANDIDATE_PRODUCERS["GEN_LINE_EDGE_TREND_V1"](facts))


def test_default_packet_adds_only_the_three_supported_dynamic_questions():
    c = compilation()
    packet = c.packet.to_dict()
    dynamic = {q["question_id"]: q for q in packet["questions"] if q["selection_domain"] == "DYNAMIC"}
    assert set(dynamic) == {"Q_SPACE_MARGIN_TREND", "Q_STROKE_DARKNESS", "Q_STROKE_WIDTH"}
    assert len(packet["questions"]) == 14
    assert dynamic["Q_SPACE_MARGIN_TREND"]["candidate_ids"] == [
        "GEN_LINE_EDGE_TREND_V1:LINE_START_DRIFT", "GEN_LINE_EDGE_TREND_V1:LINE_END_DRIFT"]
    assert dynamic["Q_STROKE_DARKNESS"]["candidate_ids"] == [
        "GEN_INK_APPEARANCE_FACT_V1:INK_DARKNESS_VARIATION"]
    assert dynamic["Q_STROKE_WIDTH"]["candidate_ids"] == [
        "GEN_THICKNESS_FACT_V1:STROKE_WIDTH_PROFILE"]


def test_dynamic_questions_need_a_registered_producer_and_empty_candidates_are_omitted():
    fact = REPORT.data["facts"][0]["fact_id"]
    conflict = Candidate("conflict.slant_vs_visual", "MEASUREMENT_CONFLICT_CANDIDATE",
                         "candidate.conflict", "Slant conflict", (fact,))
    with_candidate = compilation(producers={"GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1": lambda facts: [conflict]})
    question = next(q for q in with_candidate.packet.to_dict()["questions"]
                    if q["question_id"] == "Q_GLOBAL_EVIDENCE_CONFLICT")
    assert question["candidate_ids"] == ["conflict.slant_vs_visual"]
    empty = compilation(producers={"GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1": lambda facts: []})
    assert ("Q_GLOBAL_EVIDENCE_CONFLICT", "no_eligible_candidate") in {(o.item_id, o.reason) for o in empty.omissions}
    forged = Candidate("conflict.x", "MEASUREMENT_CONFLICT_CANDIDATE", "k", "x", ("fact.NOT_IN_REPORT",))
    with pytest.raises(InvalidInput) as outside:
        compilation(producers={"GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1": lambda facts: [forged]})
    assert outside.value.code == "candidate_support_outside_report"
    wrong_kind = Candidate("conflict.wrong", "THICKNESS_FACT", "k", "x", (fact,))
    with pytest.raises(InvalidInput) as mismatch:
        compilation(producers={"GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1": lambda facts: [wrong_kind]})
    assert mismatch.value.code == "candidate_kind_mismatch"


def test_a_drifted_interpretation_database_is_refused(tmp_path):
    copy_path = tmp_path / "db.json"
    copy_path.write_bytes(DEFAULT_PATH.read_bytes().replace(b'"max_characters": 350', b'"max_characters": 3500', 1))
    with pytest.raises(PermanentFailure):
        load_interpretation_database(copy_path)


# --- schema -------------------------------------------------------------------
def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def test_output_schema_is_strict_and_encodes_only_frozen_ids():
    c = compilation()
    schema = output_schema(c)
    for node in _objects(schema):
        assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
    branches = schema["properties"]["answers"]["items"]["anyOf"]
    packet = c.packet.to_dict()
    for branch, question in zip(branches, packet["questions"]):
        props = branch["properties"]
        assert props["question_id"]["enum"] == [question["question_id"]]
        assert props["selected_candidate_ids"]["items"]["enum"] == question["candidate_ids"]
        assert props["selected_candidate_ids"]["maxItems"] == (1 if question["cardinality"] == "SINGLE"
                                                               else len(question["candidate_ids"]))
        allowed = answer_support(packet)[question["question_id"]]
        assert props["support_fact_ids"]["items"].get("enum", []) == allowed
        assert set(allowed) <= set(packet["allowed_fact_ids"])
        if not allowed:
            assert props["support_fact_ids"]["maxItems"] == 0
    soft = schema["properties"]["soft_fields"]["items"]["anyOf"]
    assert [s["properties"]["field_id"]["enum"] for s in soft] == [["SOFT_LIMITATION"]]


# --- validation -----------------------------------------------------------------
def _apply(doc, patch):
    for op in patch:
        if op["op"] == "all_answers_state":
            for answer in doc["answers"]:
                answer.update(answer_state=op["value"], selected_candidate_ids=[], prose=None)
            continue
        *parents, last = [p for p in op["path"].split("/")[1:]]
        target = doc
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(last) if isinstance(target, list) else last
        if op["op"] == "remove":
            del target[key]
        elif op["op"] == "duplicate_answer":
            target.append(copy.deepcopy(target[key]))
        else:
            value = op["value"]
            if isinstance(value, str) and value.startswith("@long:"):
                value = "a" * int(value.split(":")[1])
            target[key] = value
    return doc


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_adversarial_output_cases(case):
    c = compilation()
    output = _apply(well_behaved(c.model_input), case["patch"])
    outcome = validate_output(c, output)
    codes = {issue.code for issue in outcome.issues}
    if case["expect"]:
        assert outcome.value is None and set(case["expect"]) <= codes, codes
    else:
        assert outcome.value is not None, outcome.issues


def test_an_answer_cannot_cite_facts_outside_its_own_question():
    c = compilation()
    packet = c.packet.to_dict()
    support = answer_support(packet)
    first = packet["questions"][0]["question_id"]
    foreign = sorted(set(packet["allowed_fact_ids"]) - set(support[first]))
    assert foreign, "fixture needs a fact outside the first question's support"
    output = well_behaved(c.model_input)
    output["answers"][0]["support_fact_ids"] = foreign[:1]
    result = validate_output(c, output)
    assert result.value is None and "ANSWER_SUPPORT_OUTSIDE_QUESTION" in {i.code for i in result.issues}


# --- attempts -------------------------------------------------------------------
class Images:
    def __init__(self, image=IMAGE):
        self.image = image

    def authorized_image(self, owner_id, report):
        return self.image


class World:
    def __init__(self, responder=None, *, image=IMAGE, limit=100_000, allow_inactive=True):
        self.clock = FakeClock(T0 + timedelta(minutes=5))
        self.permissions = PermissionService(InMemoryPermissionStore(), self.clock, SequentialIds(),
                                             allow_draft_policy=True)
        self.store = InMemoryReportStore()
        self.store.append(OWNER, REPORT)
        self.model = FakePremiumModel(responder or (lambda request: well_behaved(request.packet)), clock=self.clock)
        self.budget = InMemorySpendBudget(limit)
        self.publisher = InMemoryOverlayPublisher(lambda owner: self.store, self.permissions)
        self.runner = PremiumRunner(
            reports=lambda owner: self.store, permissions=self.permissions, images=Images(image), model=self.model,
            budget=self.budget, publisher=self.publisher, database=DB, clock=self.clock, ids=SequentialIds(),
            context=lambda: CallContext("corr-1", Environment.TEST, self.clock.now() + timedelta(seconds=60)),
            allow_inactive_content=allow_inactive)

    def grant(self):
        self.permissions.record(subject_id=OWNER, actor_id=OWNER, purpose_id="third_party_ai_processing",
                                scope=Scope("REPORT", "report_1"), decision=Decision.GRANT, notice_version=NOTICE)
        return self.permissions.require(OWNER, "third_party_ai_processing", Scope("REPORT", "report_1"))

    def withdraw(self):
        self.clock.advance(1)
        self.permissions.record(subject_id=OWNER, actor_id=OWNER, purpose_id="third_party_ai_processing",
                                scope=Scope("SUBJECT_WIDE"), decision=Decision.WITHDRAW, notice_version="settings")

    def job(self, attempt=1, revision=1):
        return PremiumJob("job_1", OWNER, "report_1", revision, self.grant(), attempt)


def test_valid_output_publishes_one_overlay_revision_and_free_facts_are_unchanged():
    world = World()
    record = world.runner.run(world.job())
    assert (record.outcome, record.revision) == (Outcome.SUCCEEDED, 2)
    owner, latest = world.store.latest("report_1")
    assert latest.data["premium_overlay_id"] == f"overlay_{record.attempt_id}"
    assert latest.data["facts"] == REPORT.data["facts"]
    request = world.model.requests[0]
    assert len(world.model.requests) == 1 and request.image == IMAGE and request.policy_version == "premium-policy-1"
    assert world.budget.reserved == {} and world.budget.spent == 150


def test_stale_consent_blocks_before_the_call_and_during_publication():
    world = World()
    job = world.job()
    world.withdraw()
    assert world.runner.run(job).error_code == "permission_changed" and world.model.requests == []

    racing = World()
    job = racing.job()

    def withdraw_mid_call(request):
        racing.withdraw()
        return well_behaved(request.packet)

    racing.model._responder = withdraw_mid_call
    record = racing.runner.run(job)
    assert (record.outcome, record.error_code) == (Outcome.FENCED, "permission_changed")
    assert racing.store.latest("report_1")[1].data["revision"] == 1


def test_withdrawal_after_compilation_stops_the_transfer():
    world = World()
    job = world.job()

    class WithdrawWhileCompiling(Images):
        def authorized_image(self, owner_id, report):
            world.withdraw()  # commits after the first check, before any private data is sent
            return IMAGE

    world.runner._images = WithdrawWhileCompiling()
    record = world.runner.run(job)
    assert (record.outcome, record.error_code) == (Outcome.FENCED, "permission_changed")
    assert world.model.requests == [] and world.budget.reserved == {} and world.budget.spent == 0


def test_inactive_t26_content_is_refused_without_a_call():
    with pytest.raises(Unsupported):
        compilation(allow_inactive=False)
    world = World(allow_inactive=False)
    record = world.runner.run(world.job())
    assert (record.outcome, record.error_code) == (Outcome.FAILED, "interpretation_pack_inactive")
    assert world.model.requests == [] and world.budget.reserved == {}


def test_budget_reserves_input_and_image_tokens_not_only_output():
    c = compilation()
    bound = billable_token_bound(c, IMAGE)
    assert bound > MAX_OUTPUT_TOKENS + IMAGE_INPUT_TOKEN_BOUND
    assert billable_token_bound(c, None) == bound - IMAGE_INPUT_TOKEN_BOUND
    world = World(limit=bound - 1)
    assert world.runner.run(world.job()).outcome is Outcome.BUDGET_EXHAUSTED and world.model.requests == []


def test_no_image_is_not_applicable_and_never_calls_or_reserves():
    world = World(image=None)
    record = world.runner.run(world.job())
    assert (record.outcome, record.error_code) == (Outcome.NOT_APPLICABLE, "authorized_image_unavailable")
    assert world.model.requests == [] and world.budget.reserved == {} and world.budget.spent == 0


def test_budget_exhaustion_prevents_the_call():
    world = World(limit=100)
    assert world.runner.run(world.job()).outcome is Outcome.BUDGET_EXHAUSTED
    assert world.model.requests == []


@pytest.mark.parametrize("state,outcome,code", [
    (port.GenerationState.REFUSED, Outcome.REFUSED, "provider_refused"),
    (port.GenerationState.INCOMPLETE, Outcome.FAILED, "output_incomplete"),
])
def test_refusal_and_truncation_are_explicit_and_unpublished(state, outcome, code):
    world = World(lambda request: state)
    record = world.runner.run(world.job())
    assert (record.outcome, record.error_code) == (outcome, code)
    assert world.store.latest("report_1")[1].data["revision"] == 1 and world.budget.spent == 100


def test_timeout_after_transmission_is_ambiguous_and_keeps_the_reservation():
    world = World()
    world.model.faults.inject("generate", AmbiguousOutcome("provider_timeout"), after_effect=True)
    record = world.runner.run(world.job())
    assert record.outcome is Outcome.AMBIGUOUS and len(world.budget.reserved) == 1
    assert world.store.latest("report_1")[1].data["revision"] == 1


def test_transient_failures_allow_one_retry_then_fail():
    world = World()
    world.model.faults.inject("generate", RateLimited(retry_after_s=5), times=2)
    assert world.runner.run(world.job(attempt=1)).outcome is Outcome.RETRYABLE
    assert world.runner.run(world.job(attempt=2)).outcome is Outcome.FAILED
    assert world.budget.reserved == {}


def test_prompt_injected_output_is_rejected_not_published():
    def obeys_the_page(request):
        output = well_behaved(request.packet)
        output["soft_fields"][0]["text"] = "The note on the page says to visit https://example.invalid now."
        output["answers"][0]["selected_candidate_ids"] = ["GLOBAL_BALANCE.GENIUS"]
        return output

    world = World(obeys_the_page)
    record = world.runner.run(world.job())
    assert (record.outcome, record.error_code) == (Outcome.FAILED, "output_rejected")
    assert {"LINK_OR_MARKUP", "OUTPUT_CANDIDATE_ESCAPE"} <= set(record.issue_codes)
    assert world.store.latest("report_1")[1].data["revision"] == 1


def test_a_job_for_a_superseded_revision_is_fenced():
    world = World()
    assert world.runner.run(world.job()).outcome is Outcome.SUCCEEDED
    record = world.runner.run(world.job(revision=1))
    assert (record.outcome, record.error_code) == (Outcome.FENCED, "report_revised")
    assert len(world.model.requests) == 1
