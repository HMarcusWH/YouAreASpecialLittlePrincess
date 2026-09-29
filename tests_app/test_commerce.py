"""T19 ledger: verified grants, credit lots, reservations, refunds and metered Premium jobs."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from princess_app.adapters.fakes import FakePaymentProvider, FakePremiumModel, SequentialIds
from princess_app.adapters.stripe import StripePaymentProvider
from princess_app.adapters.postgres.access import PostgresReportAccess
from princess_app.adapters.postgres.commerce import (
    PostgresImageSource,
    PostgresLedger,
    PostgresOverlayPublisher,
    PostgresPremiumQueue,
)
from princess_app.adapters.postgres.stores import PostgresIdentityStore, PostgresPermissionStore, PostgresReportStore
from princess_app.application.commerce import CommerceService
from princess_app.application.permissions import PermissionService
from princess_app.application.premium import (
    InMemorySpendBudget,
    PremiumRestoreReconciler,
    PremiumRunner,
    load_interpretation_database,
)
from princess_app.application.premium.service import AttemptRecord, Outcome
from princess_app.application.premium.worker import PremiumWorker
from princess_app.application.reports import ReportReader
from princess_app.domain.commerce import CATALOG, PREMIUM_SINGLE, Platform, catalog_entry
from princess_app.domain.permissions import Decision, Scope
from princess_app.ports import model as model_port
from princess_app.ports.base import (
    AmbiguousOutcome,
    Environment,
    InvalidInput,
    NotAuthorized,
    NotFound,
    ProviderMode,
    TransientUnavailable,
    Unauthenticated,
)
from princess_app.ports.payments import PaymentRail
from test_intake import NOTICE, Env, erasure
from test_persistence import account, world  # noqa: F401 - fixture re-export

DB = load_interpretation_database()
STRIPE, APPLE, GOOGLE = PaymentRail.STRIPE, PaymentRail.APPLE_APP_STORE, PaymentRail.GOOGLE_PLAY


def sku(rail):
    return catalog_entry(PREMIUM_SINGLE, rail).store_product_id


class Shop:
    def __init__(self, env: Env):
        self.env = env
        self.providers = {rail: FakePaymentProvider(rail, catalog=CATALOG, clock=env.clock,
                                                    environment=Environment.TEST) for rail in PaymentRail}
        self.ledger = PostgresLedger(env.app_db, SequentialIds())
        self.service = self._service(self.ledger)
        # The completion worker scans every owner's grants with the worker login.
        self.worker_service = self._service(PostgresLedger(env.worker_db, SequentialIds()))

    def _service(self, ledger):
        return CommerceService(ledger=ledger, providers=self.providers, permissions=self.env.permissions,
                               reports=lambda owner: PostgresReportStore(self.env.app_db, owner),
                               clock=self.env.clock, ids=SequentialIds(), environment=Environment.TEST)

    def webhook(self, rail, refs, **kwargs):
        body, headers = self.providers[rail].signed_event("transaction.updated", refs, **kwargs)
        return self.service.ingest_event(rail, body, headers, hashlib.sha256(body).hexdigest(), self.env.ctx())

    def buy_web(self, owner, intent="intent_0001"):
        session = self.service.start_web_checkout(owner, PREMIUM_SINGLE, intent, self.env.ctx())
        ref = self.providers[STRIPE].simulate_checkout_paid(session.provider_session_ref)
        return ref, self.webhook(STRIPE, [ref])

    def buy_store(self, owner, rail, **kwargs):
        account_ref = self.service.payment_account(owner)
        proof = self.providers[rail].simulate_purchase(account_ref, sku(rail), **kwargs)
        return proof, self.service.claim_store_purchase(owner, rail, proof, self.env.ctx())

    def credits(self, owner, platform=Platform.WEB):
        return self.service.balance(owner, platform)

    def entries(self, owner):
        with self.env.app_db.session(owner) as conn:
            return [r[0] for r in conn.execute(text("SELECT kind FROM app.ledger_entry ORDER BY entry_id")).all()]


@pytest.fixture
def shop(app_db, worker_db):
    return Shop(Env(app_db, worker_db))


def test_web_purchase_grants_once_from_verified_events_only(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    session = shop.service.start_web_checkout(owner, PREMIUM_SINGLE, "intent_0001", shop.env.ctx())
    assert shop.credits(owner).available == 0  # a checkout (or its redirect) grants nothing
    ref = shop.providers[STRIPE].simulate_checkout_paid(session.provider_session_ref)
    body, headers = shop.providers[STRIPE].signed_event("checkout.session.completed", [ref])
    sha = hashlib.sha256(body).hexdigest()
    assert shop.service.ingest_event(STRIPE, body, headers, sha, shop.env.ctx()) == ["granted"]
    assert shop.service.ingest_event(STRIPE, body, headers, sha, shop.env.ctx()) == ["already_granted"]
    assert shop.webhook(STRIPE, [ref]) == ["already_granted"]  # a distinct event about the same payment
    assert shop.credits(owner).available == 1
    assert shop.credits(owner, Platform.IOS).available == 0  # origin policy: no cross-store spending by default
    assert shop.entries(owner) == ["GRANT"]
    tampered = body.replace(b"checkout.session.completed", b"checkout.session.complete")
    with pytest.raises(Unauthenticated):  # the signature covers the unmodified raw body
        shop.service.ingest_event(STRIPE, tampered, headers, sha, shop.env.ctx())


def test_real_stripe_adapter_reconciles_into_the_existing_ledger_once(shop, world):  # noqa: F811
    owner = account(world, "sub-stripe-adapter").principal_id
    account_ref = shop.service.payment_account(owner)
    secret = "whsec-test-only"
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST" and request.url.path == "/v1/checkout/sessions":
            return httpx.Response(200, json={
                "object": "checkout.session", "id": "cs_realish_1", "livemode": False,
                "url": "https://checkout.stripe.com/c/pay/cs_realish_1",
                "expires_at": int(shop.env.clock.now().timestamp()) + 1800,
            })
        if request.method == "GET" and request.url.path == "/v1/payment_intents/pi_realish_1":
            return httpx.Response(200, json={
                "object": "payment_intent", "id": "pi_realish_1", "livemode": False, "status": "succeeded",
                "created": int(shop.env.clock.now().timestamp()),
                "metadata": {
                    "internal_product_id": PREMIUM_SINGLE,
                    "store_product_id": sku(STRIPE),
                    "account_ref": account_ref,
                    "environment": "test",
                    "intent_ref": "intent_realish_1",
                },
                "latest_charge": {
                    "object": "charge", "id": "ch_realish_1", "refunded": False,
                    "amount": 999, "amount_refunded": 0,
                },
            })
        raise AssertionError(f"unexpected Stripe request: {request.method} {request.url}")

    stripe = StripePaymentProvider(
        api_key="sk_test_not-real",
        webhook_secret=secret,
        api_version="test-pinned-version",
        success_url="https://app.example.test/purchase/success",
        cancel_url="https://app.example.test/purchase/cancel",
        catalog=CATALOG,
        clock=shop.env.clock,
        environment=Environment.TEST,
        mode=ProviderMode.SANDBOX,
        activation_approved=True,
        transport=httpx.MockTransport(handler),
    )
    service = CommerceService(
        ledger=shop.ledger,
        providers={**shop.providers, STRIPE: stripe},
        permissions=shop.env.permissions,
        reports=lambda principal: PostgresReportStore(shop.env.app_db, principal),
        clock=shop.env.clock,
        ids=SequentialIds(),
        environment=Environment.TEST,
    )

    session = service.start_web_checkout(owner, PREMIUM_SINGLE, "intent_realish_1", shop.env.ctx())
    assert session.provider_session_ref == "cs_realish_1"
    assert service.balance(owner, Platform.WEB).available == 0

    payload = {
        "id": "evt_realish_1",
        "type": "checkout.session.completed",
        "created": int(shop.env.clock.now().timestamp()),
        "livemode": False,
        "data": {"object": {
            "object": "checkout.session",
            "payment_intent": "pi_realish_1",
            "metadata": {"environment": "test"},
        }},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(shop.env.clock.now().timestamp())
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    headers = {"Stripe-Signature": f"t={timestamp},v1={signature}"}
    digest = hashlib.sha256(raw).hexdigest()

    assert service.ingest_event(STRIPE, raw, headers, digest, shop.env.ctx()) == ["granted"]
    assert service.ingest_event(STRIPE, raw, headers, digest, shop.env.ctx()) == ["already_granted"]
    assert service.balance(owner, Platform.WEB).available == 1
    assert shop.entries(owner) == ["GRANT"]
    assert sum(request.url.path == "/v1/payment_intents/pi_realish_1" for request in seen) == 2


def test_store_claims_reject_pending_foreign_and_malformed_purchases(shop, world):  # noqa: F811
    alice = account(world, "sub-a").principal_id
    bob = account(world, "sub-b").principal_id
    proof, result = shop.buy_store(alice, APPLE, pending=True)
    assert result.outcome == "payment_pending" and shop.credits(alice, Platform.IOS).available == 0
    shop.providers[APPLE].simulate_settle_pending(shop.providers[APPLE].transaction_ref_from_proof(proof))
    claimed = shop.service.claim_store_purchase(alice, APPLE, proof, shop.env.ctx())
    assert (claimed.outcome, claimed.finish_on_client) == ("granted", True)  # Apple finishes on the client
    assert shop.service.claim_store_purchase(bob, APPLE, proof, shop.env.ctx()).outcome == "account_mismatch"
    assert shop.credits(bob, Platform.IOS).available == 0
    acct = shop.service.payment_account(alice)
    staging = shop.providers[GOOGLE].simulate_purchase(acct, sku(GOOGLE), environment=Environment.STAGING)
    assert shop.service.claim_store_purchase(alice, GOOGLE, staging, shop.env.ctx()).outcome == "wrong_environment"
    unknown = shop.providers[GOOGLE].simulate_purchase(acct, "some.other.sku")
    assert shop.service.claim_store_purchase(alice, GOOGLE, unknown, shop.env.ctx()).outcome == "unknown_product"
    assert shop.credits(alice, Platform.ANDROID).available == 0


def test_google_consumption_follows_the_grant_and_is_retried(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    shop.providers[GOOGLE].faults.inject("complete_store_purchase", TransientUnavailable("play_unavailable"))
    proof, result = shop.buy_store(owner, GOOGLE)
    assert result.outcome == "granted" and shop.credits(owner, Platform.ANDROID).available == 1  # grant is durable
    ref = shop.providers[GOOGLE].transaction_ref_from_proof(proof)
    assert not shop.providers[GOOGLE]._txns[ref].completed
    assert shop.worker_service.complete_pending(shop.env.ctx()) == 1
    assert shop.providers[GOOGLE]._txns[ref].completed
    assert shop.worker_service.complete_pending(shop.env.ctx()) == 0


def test_the_last_credit_cannot_be_reserved_twice(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    shop.buy_web(owner)
    results = []

    def reserve(i):
        try:
            shop.ledger.reserve_and_enqueue(owner, operation_key=f"op:{i}", rails=[STRIPE], report_id="report_x",
                                            revision=1, permission_epoch=0, platform=Platform.WEB,
                                            job_id=f"pjob_{i}", reservation_id=f"resv_{i}", at=shop.env.clock.now())
            results.append("ok")
        except NotAuthorized:
            results.append("none")

    threads = [threading.Thread(target=reserve, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and shop.credits(owner).available == 0
    winner = next(i for i in range(8) if shop.ledger.premium_status(owner, f"pjob_{i}"))
    again = shop.ledger.reserve_and_enqueue(owner, operation_key=f"op:{winner}", rails=[STRIPE],
                                            report_id="report_x", revision=1, permission_epoch=0,
                                            platform=Platform.WEB, job_id="pjob_new", reservation_id="resv_new",
                                            at=shop.env.clock.now())
    assert (again.job_id, again.created) == (f"pjob_{winner}", False)  # same intended operation converges


def test_refunds_are_compensating_entries(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    ref, _ = shop.buy_web(owner)
    shop.providers[STRIPE].simulate_refund(ref)
    assert shop.webhook(STRIPE, [ref]) == ["refunded"]
    assert shop.webhook(STRIPE, [ref]) == ["already_refunded"]
    assert shop.credits(owner).available == 0
    assert shop.entries(owner) == ["GRANT", "REVOKE"]
    unknown = shop.providers[STRIPE].simulate_purchase("acct-unknown", sku(STRIPE))
    shop.providers[STRIPE].simulate_refund(shop.providers[STRIPE].transaction_ref_from_proof(unknown))
    assert shop.webhook(STRIPE, [shop.providers[STRIPE].transaction_ref_from_proof(unknown)]) == ["refund_unmatched"]


def test_a_deleted_account_is_not_resurrected_by_a_late_purchase(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    session = shop.service.start_web_checkout(owner, PREMIUM_SINGLE, "intent_0001", shop.env.ctx())
    ref = shop.providers[STRIPE].simulate_checkout_paid(session.provider_session_ref)
    PostgresIdentityStore(shop.env.app_db).mark_deleted(owner, shop.env.clock.now())
    assert shop.webhook(STRIPE, [ref]) == ["owner_deleted_refund_requested"]
    assert shop.providers[STRIPE].retrieve_authoritative_purchase(ref, "", shop.env.ctx()).state.value == "REFUNDED"
    with shop.env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.credit_lot")).scalar() == 0
    with pytest.raises(NotFound):  # and a deleted account cannot start another checkout
        shop.service.start_web_checkout(owner, PREMIUM_SINGLE, "intent_0002", shop.env.ctx())


# --- metered Premium --------------------------------------------------------
def answer(request):
    packet = request.packet
    return {"contract_version": "1.0.0", "packet_id": packet["packet_id"],
            "output_schema_version": packet["output_schema_version"],
            "answers": [{"question_id": q["question_id"], "answer_state": "NOT_ASSESSABLE",
                         "selected_candidate_ids": [], "support_fact_ids": [], "prose": None}
                        for q in packet["questions"]],
            "soft_fields": []}


class Studio:
    """A published Free report with an authorized image and a purchased credit."""

    def __init__(self, shop, world, responder=answer):  # noqa: F811
        env = shop.env
        self.shop, self.env = shop, env
        self.owner = account(world, "sub-p").principal_id
        capture, run_id = env.analysis(self.owner)
        assert env.worker().run_once().outcome == "SUCCEEDED"
        self.report_id = env.intake.status(self.owner, run_id).report_id
        env.permissions.record(subject_id=self.owner, actor_id=self.owner, purpose_id="third_party_ai_processing",
                               scope=Scope("REPORT", self.report_id), decision=Decision.GRANT, notice_version=NOTICE)
        self.ref, _ = shop.buy_web(self.owner)
        self.model = FakePremiumModel(responder, clock=env.clock)
        worker_permissions = PermissionService(PostgresPermissionStore(env.worker_db), env.clock, SequentialIds(),
                                               allow_draft_policy=True)
        self.queue = PostgresPremiumQueue(env.worker_db)
        runner = PremiumRunner(
            reports=lambda owner: PostgresReportStore(env.worker_db, owner), permissions=worker_permissions,
            images=PostgresImageSource(env.worker_db), model=self.model, budget=InMemorySpendBudget(100_000),
            attempts=self.queue, publisher=PostgresOverlayPublisher(env.worker_db, allow_draft_policy=True),
            database=DB, clock=env.clock, context=env.ctx, allow_inactive_content=True)
        self.runner = runner
        self.worker = PremiumWorker(queue=self.queue, runner=runner, clock=env.clock, worker_id="premium-1")

    def request(self):
        return self.shop.service.request_premium(self.owner, self.report_id, Platform.WEB)

    def reservation_state(self):
        with self.env.app_db.session(self.owner) as conn:
            return conn.execute(text("SELECT state FROM app.credit_reservation")).scalar()

    def revision(self):
        return PostgresReportStore(self.env.app_db, self.owner).latest(self.report_id)[1].data["revision"]


def test_premium_spends_exactly_one_credit_when_the_overlay_publishes(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    first = studio.request()
    assert studio.request() == type(first)(first.job_id, first.reservation_id, False)  # retried request converges
    assert shop.credits(studio.owner).available == 0
    done = studio.worker.run_once()
    assert (done.record.outcome.value, done.job_state) == ("SUCCEEDED", "SUCCEEDED")
    assert shop.service.premium_status(studio.owner, first.job_id) == ("SUCCEEDED", None)
    assert studio.revision() == 2 and studio.reservation_state() == "SPENT"
    assert shop.entries(studio.owner) == ["GRANT", "RESERVE", "SPEND"]
    with pytest.raises(InvalidInput):
        studio.request()  # the report already carries its Premium overlay
    assert studio.worker.run_once() is None


def test_failed_generation_releases_the_credit_and_allows_a_new_attempt(shop, world):  # noqa: F811
    studio = Studio(shop, world, responder=lambda request: model_port.GenerationState.REFUSED)
    first = studio.request()
    done = studio.worker.run_once()
    assert (done.record.outcome.value, done.job_state) == ("REFUSED", "FAILED")
    assert studio.reservation_state() == "RELEASED" and shop.credits(studio.owner).available == 1
    assert studio.revision() == 1
    again = studio.request()  # the returned credit can be spent on a fresh attempt
    assert again.created and again.job_id != first.job_id and shop.credits(studio.owner).available == 0
    assert studio.request() == type(again)(again.job_id, again.reservation_id, False)
    assert shop.service.premium_status(studio.owner, first.job_id)[0] == "FAILED"  # history is kept


def test_ambiguous_outcomes_retry_once_then_release(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.model.faults.inject("generate", AmbiguousOutcome("provider_timeout"), after_effect=True, times=2)
    studio.request()
    assert studio.worker.run_once().job_state == "QUEUED"
    assert studio.worker.run_once().job_state == "FAILED"
    assert studio.reservation_state() == "RELEASED" and shop.credits(studio.owner).available == 1


def test_restore_reconciliation_detects_remote_execution_without_a_second_generation(
        shop, world, admin_engine):  # noqa: F811
    studio = Studio(shop, world)
    studio.model.faults.inject("generate", AmbiguousOutcome("provider_timeout"), after_effect=True)
    requested = studio.request()
    first = studio.worker.run_once()
    assert (first.record.outcome.value, first.job_state) == ("AMBIGUOUS", "QUEUED")
    assert len(studio.model.requests) == 1

    # Simulate restoring a backup from immediately before the provider call.
    # Remote fake state remains outside the restored PostgreSQL snapshot.
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM app.provider_attempt"))
        conn.execute(text(
            "UPDATE app.job SET state = 'QUEUED', attempts = 0, fencing_token = 0, lease_owner = NULL, "
            "lease_expires_at = NULL, last_error = NULL WHERE job_id = :j"
        ), {"j": requested.job_id})

    result = PremiumRestoreReconciler(
        queue=studio.queue, runner=studio.runner, model=studio.model, attempts=studio.queue,
        clock=studio.env.clock, context=studio.env.ctx,
    ).run()
    assert (result.checked, result.remote_execution_found, result.safe_to_resume, result.failed_closed) == (1, 1, 0, 0)
    assert len(studio.model.requests) == 1 and len(studio.model.lookups) == 1
    assert shop.service.premium_status(studio.owner, requested.job_id) == (
        "FAILED", "restored_provider_attempt_detected",
    )
    assert studio.reservation_state() == "RELEASED"
    assert studio.revision() == 1
    with studio.env.worker_db.session() as conn:
        row = conn.execute(text(
            "SELECT state, packet_digest, provider_request_id FROM app.provider_attempt"
        )).one()
    assert row[0] == "COMPLETED" and len(row[1]) == 64 and row[2]
    assert PremiumRestoreReconciler(
        queue=studio.queue, runner=studio.runner, model=studio.model, attempts=studio.queue,
        clock=studio.env.clock, context=studio.env.ctx,
    ).run().checked == 0


def test_restore_reconciliation_fails_closed_without_provider_lookup(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.model.profile = type(studio.model.profile)(
        port=studio.model.profile.port, provider=studio.model.profile.provider,
        mode=studio.model.profile.mode,
        capabilities=frozenset(
            capability for capability in studio.model.profile.capabilities
            if capability != model_port.ATTEMPT_LOOKUP
        ),
    )
    requested = studio.request()
    result = PremiumRestoreReconciler(
        queue=studio.queue, runner=studio.runner, model=studio.model, attempts=studio.queue,
        clock=studio.env.clock, context=studio.env.ctx,
    ).run()
    assert (result.checked, result.failed_closed) == (1, 1)
    assert studio.model.requests == [] and studio.model.lookups == []
    assert shop.service.premium_status(studio.owner, requested.job_id) == (
        "FAILED", "restore_lookup_unsupported",
    )
    assert studio.reservation_state() == "RELEASED"

def test_a_refund_during_generation_blocks_publication(shop, world):  # noqa: F811
    holder = {}

    def refund_mid_call(request):
        shop.providers[STRIPE].simulate_refund(holder["studio"].ref)
        shop.webhook(STRIPE, [holder["studio"].ref])
        return answer(request)

    studio = Studio(shop, world, responder=refund_mid_call)
    holder["studio"] = studio
    requested = studio.request()
    done = studio.worker.run_once()
    # The refund cancelled the leased job, so the in-flight attempt lost its lease.
    assert (done.record.outcome.value, done.record.error_code, done.job_state) == ("FENCED", "lease_lost", "FENCED")
    assert shop.service.premium_status(studio.owner, requested.job_id) == ("CANCELLED", "credit_refunded")
    assert studio.revision() == 1 and studio.reservation_state() == "REVOKED"
    assert shop.credits(studio.owner).available == 0


def test_reserved_credits_are_counted_per_platform(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.request()
    assert shop.credits(studio.owner).reserved == 1
    assert shop.credits(studio.owner, Platform.IOS).reserved == 0  # a web reservation is not an iOS one


def test_premium_needs_permission_and_an_eligible_credit(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    with pytest.raises(NotAuthorized):
        shop.service.request_premium(studio.owner, studio.report_id, Platform.IOS)  # web credit, iOS spend
    studio.env.clock.advance(1)
    studio.env.permissions.record(subject_id=studio.owner, actor_id=studio.owner,
                                  purpose_id="third_party_ai_processing", scope=Scope("SUBJECT_WIDE"),
                                  decision=Decision.WITHDRAW, notice_version="settings")
    with pytest.raises(NotAuthorized):
        studio.request()
    assert shop.credits(studio.owner).available == 1


def test_stale_premium_workers_cannot_publish(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.request()
    queue = PostgresPremiumQueue(studio.env.worker_db)
    stale = queue.claim("old", 30, studio.env.clock.now())
    studio.env.clock.advance(31)
    assert studio.worker.run_once().job_state == "SUCCEEDED"  # a new worker reclaims and publishes
    assert queue.finish(stale, AttemptRecord("a", stale.job_id, Outcome.FAILED, "late"),
                        studio.env.clock.now() + timedelta(seconds=1)) == "FENCED"
    assert studio.reservation_state() == "SPENT"


def test_a_first_time_store_completion_is_recorded_under_the_owner(shop, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    proof, result = shop.buy_store(owner, GOOGLE)  # consume succeeds inside the API request
    assert result.outcome == "granted"
    with shop.env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT completed_at IS NOT NULL FROM app.financial_transaction")).scalar()
    shop.providers[GOOGLE].faults.inject("complete_store_purchase", TransientUnavailable("must_not_be_called"))
    assert shop.worker_service.complete_pending(shop.env.ctx()) == 0  # nothing left to repeat


def test_a_refund_before_claim_cancels_the_queued_job(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    requested = studio.request()
    shop.providers[STRIPE].simulate_refund(studio.ref)
    assert shop.webhook(STRIPE, [studio.ref]) == ["refunded"]
    assert shop.service.premium_status(studio.owner, requested.job_id) == ("CANCELLED", "credit_refunded")
    assert studio.worker.run_once() is None and studio.model.requests == []


def test_crashed_final_attempts_are_not_reclaimed_and_release_the_credit(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    requested = studio.request()
    queue = PostgresPremiumQueue(studio.env.worker_db)
    for _ in range(2):  # two workers crash mid-attempt; neither reaches finish()
        assert queue.claim("crashing", 30, studio.env.clock.now()) is not None
        studio.env.clock.advance(31)
    assert queue.claim("another", 30, studio.env.clock.now()) is None  # the attempt cap holds on recovery
    assert studio.worker.run_once() is None and studio.model.requests == []
    assert shop.service.premium_status(studio.owner, requested.job_id) == ("FAILED", "attempts_exhausted")
    assert studio.reservation_state() == "RELEASED" and shop.credits(studio.owner).available == 1


def test_a_successful_retry_clears_the_earlier_error(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.model.faults.inject("generate", TransientUnavailable("provider_unavailable"))
    requested = studio.request()
    assert studio.worker.run_once().job_state == "QUEUED"
    assert shop.service.premium_status(studio.owner, requested.job_id) == ("QUEUED", "provider_unavailable")
    assert studio.worker.run_once().job_state == "SUCCEEDED"
    assert shop.service.premium_status(studio.owner, requested.job_id) == ("SUCCEEDED", None)


def test_the_buyer_reads_the_published_overlay_until_ai_processing_is_withdrawn(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.request()
    assert studio.worker.run_once().job_state == "SUCCEEDED"
    reader = ReportReader(PostgresReportStore(studio.env.app_db, studio.owner), studio.env.clock,
                          PostgresReportAccess(studio.env.app_db))
    owner_view = reader.view(report_id=studio.report_id, principal_id=studio.owner, projection="OWNER").data
    assert any(s["premium_section_id"] for s in owner_view["sections"])
    assert reader.view(report_id=studio.report_id, principal_id=studio.owner, projection="PREMIUM")
    content = reader.premium_content(report_id=studio.report_id, principal_id=studio.owner)
    assert content["evidence_class"] == "AI_SYNTHESIS" and content["answers"] and content["revision"] == 2

    studio.env.clock.advance(1)
    studio.env.permissions.record(subject_id=studio.owner, actor_id=studio.owner,
                                  purpose_id="third_party_ai_processing", scope=Scope("REPORT", studio.report_id),
                                  decision=Decision.WITHDRAW, notice_version="settings")
    with studio.env.app_db.session(studio.owner) as conn:  # erased in the withdrawal's own transaction
        row = conn.execute(text("SELECT packet, output, erased_at IS NOT NULL FROM app.premium_overlay")).first()
    assert row == (None, None, True)
    owner_view = reader.view(report_id=studio.report_id, principal_id=studio.owner, projection="OWNER").data
    assert not any(s["premium_section_id"] for s in owner_view["sections"])
    assert "notice.premium_revoked" in {n["localization_key"] for n in owner_view["notices"]}
    with pytest.raises(NotAuthorized):
        reader.premium_content(report_id=studio.report_id, principal_id=studio.owner)


def test_reads_disclose_an_erased_source_image(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    reader = ReportReader(PostgresReportStore(studio.env.app_db, studio.owner), studio.env.clock,
                          PostgresReportAccess(studio.env.app_db))
    view = reader.view(report_id=studio.report_id, principal_id=studio.owner, projection="OWNER").data
    assert view["authorized_asset_ids"]
    with studio.env.app_db.session(studio.owner) as conn:
        capture_id = conn.execute(text("SELECT capture_id FROM app.capture")).scalar()
    studio.env.repo.request_retention_review(studio.owner, capture_id, studio.env.clock.now())
    assert "ERASED" in {o.action for o in erasure(studio.env).run_once()}  # no image-retention grant
    view = reader.view(report_id=studio.report_id, principal_id=studio.owner, projection="OWNER").data
    assert not view["authorized_asset_ids"]
    assert "notice.source_image_unavailable" in {n["localization_key"] for n in view["notices"]}
    with pytest.raises(NotFound):
        reader.premium_content(report_id="report_missing", principal_id=studio.owner)


def test_account_erasure_settles_open_reservations_before_removing_jobs(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.request()
    PostgresIdentityStore(studio.env.app_db).mark_deleted(studio.owner, studio.env.clock.now())
    assert "ERASED" in {o.action for o in erasure(studio.env).run_once()}
    assert studio.reservation_state() == "RELEASED"
    assert shop.entries(studio.owner)[-1] == "RELEASE"
    with studio.env.app_db.session(studio.owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.job")).scalar() == 0


def test_premium_publication_re_evaluates_the_grant_itself(shop, world):  # noqa: F811
    studio = Studio(shop, world)
    studio.request()
    studio.worker._runner._publisher.allow_draft_policy = False  # a deployment that retired the draft notice
    done = studio.worker.run_once()
    assert (done.record.outcome.value, done.record.error_code) == ("FENCED", "permission_changed")
    assert studio.revision() == 1 and studio.reservation_state() == "RELEASED"
