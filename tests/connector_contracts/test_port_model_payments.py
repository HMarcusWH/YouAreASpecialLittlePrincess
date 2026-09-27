"""PremiumModelProvider and PaymentProvider contract cases."""
from __future__ import annotations

import pytest
from port_harness import ctx

from princess_app.adapters.fakes import FakeClock, FakeNativePurchaseClient, FakePaymentProvider, FakePremiumModel
from princess_app.ports import model, payments
from princess_app.ports.base import AmbiguousOutcome, Environment, InvalidInput, RateLimited, Unauthenticated
from princess_contracts import canonical_digest

PACKET = {"questions": []}
DIGEST = canonical_digest(PACKET)


def request(attempt="att_1", packet=None):
    packet = PACKET if packet is None else packet
    return model.GenerationRequest(attempt_id=attempt, packet=packet, packet_digest=canonical_digest(packet),
                                   output_schema={"type": "object"}, policy_version="policy-1")


def test_model_returns_parsed_output_and_redacts_repr():
    clock = FakeClock()
    fake = FakePremiumModel(lambda r: {"answers": []}, clock=clock)
    result = fake.generate(request(), ctx(clock))
    assert result.state is model.GenerationState.COMPLETED and result.output == {"answers": []}
    assert "questions" not in repr(request()) and "answers" not in repr(result)


@pytest.mark.parametrize("state", [model.GenerationState.REFUSED, model.GenerationState.INCOMPLETE])
def test_refusal_and_truncation_carry_no_output(state):
    clock = FakeClock()
    result = FakePremiumModel(lambda r: state, clock=clock).generate(request(), ctx(clock))
    assert result.state is state and result.output is None


def test_rate_limit_and_timeout_after_acceptance():
    clock = FakeClock()
    fake = FakePremiumModel(lambda r: {"answers": []}, clock=clock)
    fake.faults.inject("generate", RateLimited(retry_after_s=20))
    with pytest.raises(RateLimited):
        fake.generate(request(), ctx(clock))
    assert fake.requests == []
    fake.faults.inject("generate", AmbiguousOutcome("timeout_after_send"), after_effect=True)
    with pytest.raises(AmbiguousOutcome):
        fake.generate(request(), ctx(clock))
    assert len(fake.requests) == 1  # the provider did receive (and may bill) the request


def test_generation_request_snapshots_mappings_and_binds_digest():
    packet = {"questions": [{"id": "q1"}]}
    schema = {"type": "object"}
    req = request(packet=packet)
    packet["questions"].append({"id": "injected"})
    schema["type"] = "array"
    assert len(req.packet["questions"]) == 1 and req.output_schema["type"] == "object"
    with pytest.raises(TypeError):
        req.packet["questions"] = []  # type: ignore[index]
    with pytest.raises(InvalidInput) as err:
        model.GenerationRequest("att_1", {"questions": []}, "a" * 64, {}, "policy-1")
    assert err.value.code == "packet_digest_mismatch"


def test_generation_request_validation():
    with pytest.raises(InvalidInput):
        model.GenerationRequest("att_1", {}, "not-a-digest", {}, "policy-1")
    with pytest.raises(InvalidInput):
        model.ProviderGenerationResult(model.GenerationState.REFUSED, {"x": 1}, None, "m", None)


CATALOG = [
    payments.CatalogProduct("credits_1", payments.PaymentRail.GOOGLE_PLAY, "g.credits.1", 1),
    payments.CatalogProduct("unlock_forever", payments.PaymentRail.GOOGLE_PLAY, "g.unlock", 0, consumable=False),
    payments.CatalogProduct("credits_1_ios", payments.PaymentRail.APPLE_APP_STORE, "a.credits.1", 1),
    payments.CatalogProduct("credits_1_web", payments.PaymentRail.STRIPE, "price_1", 1),
]


def rail(kind):
    clock = FakeClock()
    return clock, FakePaymentProvider(kind, clock=clock, catalog=CATALOG)


def test_google_proof_verifies_with_account_binding_and_consume_is_idempotent():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    proof = google.simulate_purchase("acct_1", "g.credits.1")
    obs = google.verify_purchase(proof, "acct_1", ctx(clock))
    assert obs.state is payments.PurchaseState.PURCHASED and obs.product_id == "credits_1"
    assert obs.account_binding is payments.AccountBinding.MATCHED
    assert obs.completion_action is payments.CompletionAction.SERVER_CONSUME
    other = google.verify_purchase(proof, "acct_2", ctx(clock))
    assert other.account_binding is payments.AccountBinding.MISMATCHED
    google.complete_store_purchase(obs.transaction_ref, payments.CompletionAction.SERVER_CONSUME, ctx(clock))
    google.complete_store_purchase(obs.transaction_ref, payments.CompletionAction.SERVER_CONSUME, ctx(clock))
    assert google.retrieve_authoritative_purchase(obs.transaction_ref, "acct_1", ctx(clock)).completed


def test_google_non_consumable_is_acknowledged_not_consumed():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    obs = google.verify_purchase(google.simulate_purchase("acct_1", "g.unlock"), "acct_1", ctx(clock))
    assert obs.completion_action is payments.CompletionAction.SERVER_ACKNOWLEDGE


@pytest.mark.parametrize("body", [
    b'{"id": "e1", "type": "t", "environment": "test", "transactions": "pi_000001"}',
    b'{"id": "e1", "type": "t", "environment": "test", "transactions": [1, 2]}',
    b'{"id": 5, "type": "t", "environment": "test", "transactions": ["pi_1"]}',
    b'["not", "an", "object"]',
])
def test_signed_but_malformed_events_are_rejected(body):
    import hashlib
    import hmac

    clock, stripe = rail(payments.PaymentRail.STRIPE)
    ts = str(int(clock.now().timestamp()))
    mac = hmac.new(b"fake-webhook-secret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    with pytest.raises(InvalidInput):
        stripe.verify_and_normalize_event(body, {"x-fake-signature": f"t={ts},v1={mac}"}, ctx(clock))


def test_consume_timeout_after_acceptance_is_ambiguous_then_reconcilable():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    proof = google.simulate_purchase("acct_1", "g.credits.1")
    ref = google.transaction_ref_from_proof(proof)
    google.faults.inject("complete_store_purchase", AmbiguousOutcome("timeout_after_send"), after_effect=True)
    with pytest.raises(AmbiguousOutcome):
        google.complete_store_purchase(ref, payments.CompletionAction.SERVER_CONSUME, ctx(clock))
    assert google.retrieve_authoritative_purchase(ref, "acct_1", ctx(clock)).completed is True


def test_forged_or_tampered_proof_is_rejected():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    proof = google.simulate_purchase("acct_1", "g.credits.1")
    for bad in ("fakeproof.ptok_000001.000000000000000000000000", proof + "x", "anything"):
        with pytest.raises(Unauthenticated):
            google.verify_purchase(bad, "acct_1", ctx(clock))


def test_pending_then_purchased_then_refunded_are_observations_not_grants():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    proof = google.simulate_purchase("acct_1", "g.credits.1", pending=True)
    ref = google.transaction_ref_from_proof(proof)
    assert google.verify_purchase(proof, "acct_1", ctx(clock)).state is payments.PurchaseState.PENDING
    google.simulate_settle_pending(ref)
    assert google.verify_purchase(proof, "acct_1", ctx(clock)).state is payments.PurchaseState.PURCHASED
    google.simulate_refund(ref)
    obs = google.retrieve_authoritative_purchase(ref, "acct_1", ctx(clock))
    assert obs.state is payments.PurchaseState.REFUNDED and obs.refunded_at is not None


def test_wrong_environment_proof_is_visible_to_the_ledger():
    clock, google = rail(payments.PaymentRail.GOOGLE_PLAY)
    proof = google.simulate_purchase("acct_1", "g.credits.1", environment=Environment.PRODUCTION)
    assert google.verify_purchase(proof, "acct_1", ctx(clock)).environment is Environment.PRODUCTION


def test_signed_events_verify_raw_body_and_reject_tampering_replay_window():
    clock, stripe = rail(payments.PaymentRail.STRIPE)
    body, headers = stripe.signed_event("payment.succeeded", ["pi_000001"])
    event = stripe.verify_and_normalize_event(body, headers, ctx(clock))
    assert event.transaction_refs == ("pi_000001",)
    with pytest.raises(Unauthenticated):
        stripe.verify_and_normalize_event(body.replace(b"pi_000001", b"pi_000002"), headers, ctx(clock))
    forged_body, forged_headers = stripe.signed_event("payment.succeeded", ["pi_1"], secret=b"attacker")
    with pytest.raises(Unauthenticated):
        stripe.verify_and_normalize_event(forged_body, forged_headers, ctx(clock))
    clock.advance(3600)
    with pytest.raises(Unauthenticated):
        stripe.verify_and_normalize_event(body, headers, ctx(clock))


def test_web_checkout_redirect_is_not_payment_until_provider_says_so():
    clock, stripe = rail(payments.PaymentRail.STRIPE)
    session = stripe.create_web_checkout("intent_1", CATALOG[3], "acct_1", ctx(clock))
    assert stripe.create_web_checkout("intent_1", CATALOG[3], "acct_1", ctx(clock)) == session  # retry
    assert "checkout" not in repr(session)
    ref = stripe.reconcile(clock.now(), ctx(clock))[0].transaction_ref
    assert stripe.retrieve_authoritative_purchase(ref, "acct_1", ctx(clock)).state is payments.PurchaseState.PENDING
    assert len(stripe.reconcile(clock.now(), ctx(clock))) == 1  # one chargeable intent, not two
    stripe.simulate_checkout_paid(session.provider_session_ref)
    assert stripe.retrieve_authoritative_purchase(ref, "acct_1", ctx(clock)).state is payments.PurchaseState.PURCHASED
    with pytest.raises(InvalidInput):
        stripe.create_web_checkout("intent_2", CATALOG[0], "acct_1", ctx(clock))


def test_native_client_returns_proofs_and_apple_finish_is_client_side():
    clock, apple = rail(payments.PaymentRail.APPLE_APP_STORE)
    client = FakeNativePurchaseClient(apple, "acct_1")
    outcome = client.begin_purchase("a.credits.1", "session-token")
    assert outcome.state == "PURCHASED" and client.recover_pending_transactions() == [outcome.proof]
    obs = apple.verify_purchase(outcome.proof.proof, "acct_1", ctx(clock))
    assert obs.completion_action is payments.CompletionAction.CLIENT_FINISH and obs.completed is False
    client.finish_after_server_grant(outcome.proof)
    assert client.recover_pending_transactions() == []
    assert apple.verify_purchase(outcome.proof.proof, "acct_1", ctx(clock)).completed is True
    assert client.begin_purchase("a.credits.1", "t", cancel=True).proof is None
    updates = []
    unsubscribe = client.observe_transaction_updates(updates.append)
    pending = client.begin_purchase("a.credits.1", "t", pending=True).proof
    client.settle_pending(pending)
    assert [u.pending for u in updates] == [False]
    assert apple.verify_purchase(pending.proof, "acct_1", ctx(clock)).state is payments.PurchaseState.PURCHASED
    unsubscribe()
    client.settle_pending(pending)
    assert len(updates) == 1
    with pytest.raises(InvalidInput):
        FakeNativePurchaseClient(rail(payments.PaymentRail.STRIPE)[1], "acct_1")
