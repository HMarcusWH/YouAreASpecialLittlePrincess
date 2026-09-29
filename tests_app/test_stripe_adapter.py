"""Stripe PaymentProvider adapter against in-process HTTP transport.

No network, Stripe account, real key, price or customer data is used here.
Production composition remains fake-only until T19's owner/provider gates clear.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from princess_app.adapters.fakes import FakeClock
from princess_app.adapters.stripe import StripePaymentProvider
from princess_app.ports import payments
from princess_app.ports.base import (
    AmbiguousOutcome,
    CallContext,
    Environment,
    InvalidInput,
    PermanentFailure,
    ProviderMode,
    RateLimited,
    TransientUnavailable,
    Unauthenticated,
    Unsupported,
)

KEY = "sk_test_not-a-real-key"
WEBHOOK = "whsec_not-a-real-secret"
API_VERSION = "test-pinned-version"
PRODUCT = payments.CatalogProduct("premium_single", payments.PaymentRail.STRIPE, "price_test_1", 1)


def pi(ref="pi_test_1", *, status="succeeded", account="acct_1", product="premium_single",
       store_product="price_test_1", environment="test", livemode=False, refunded=False,
       amount=999, amount_refunded=0):
    return {
        "object": "payment_intent",
        "id": ref,
        "livemode": livemode,
        "status": status,
        "created": 1_700_000_000,
        "metadata": {
            "internal_product_id": product,
            "store_product_id": store_product,
            "account_ref": account,
            "environment": environment,
            "intent_ref": "intent_1",
        },
        "latest_charge": {
            "object": "charge",
            "id": "ch_test_1",
            "refunded": refunded,
            "amount": amount,
            "amount_refunded": amount_refunded,
            "created": 1_700_000_001,
        },
    }


class Setup:
    def __init__(self, handler=None, *, mode=ProviderMode.SANDBOX, environment=Environment.TEST):
        self.clock = FakeClock()
        self.seen = []

        def record(request):
            self.seen.append(request)
            if handler is None:
                raise AssertionError(f"unexpected request: {request.method} {request.url}")
            return handler(request)

        self.provider = StripePaymentProvider(
            api_key=KEY,
            webhook_secret=WEBHOOK,
            api_version=API_VERSION,
            success_url="https://app.example.test/purchase/success",
            cancel_url="https://app.example.test/purchase/cancel",
            catalog=[PRODUCT],
            clock=self.clock,
            environment=environment,
            mode=mode,
            activation_approved=True,
            transport=httpx.MockTransport(record),
        )
        self.environment = environment

    def ctx(self, environment=None):
        return CallContext(
            "corr_1",
            environment or self.environment,
            self.clock.now() + timedelta(seconds=30),
        )

    def signed_event(self, payload, *, timestamp=None, secret=WEBHOOK):
        body = json.dumps(payload, separators=(",", ":")).encode()
        ts = int(self.clock.now().timestamp()) if timestamp is None else timestamp
        sig = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
        return body, {"Stripe-Signature": f"t={ts},v1={sig}"}


def checkout_payload():
    return {
        "object": "checkout.session",
        "id": "cs_test_1",
        "url": "https://checkout.stripe.com/c/pay/cs_test_1",
        "expires_at": 1_700_001_800,
        "livemode": False,
    }


def test_construction_is_gated_mode_checked_and_redacted():
    clock = FakeClock()
    common = dict(
        api_key=KEY,
        webhook_secret=WEBHOOK,
        api_version=API_VERSION,
        success_url="https://app.example.test/success",
        cancel_url="https://app.example.test/cancel",
        catalog=[PRODUCT],
        clock=clock,
    )
    with pytest.raises(Unsupported):
        StripePaymentProvider(**common, environment=Environment.TEST, mode=ProviderMode.SANDBOX)
    with pytest.raises(InvalidInput):
        StripePaymentProvider(**common, environment=Environment.LOCAL, mode=ProviderMode.FAKE, activation_approved=True)
    with pytest.raises(InvalidInput):
        StripePaymentProvider(**common, environment=Environment.PRODUCTION, mode=ProviderMode.SANDBOX,
                              activation_approved=True)
    with pytest.raises(InvalidInput):
        StripePaymentProvider(**common, environment=Environment.TEST, mode=ProviderMode.SANDBOX,
                              activation_approved=True, success_url="http://unsafe.invalid")
    setup = Setup(lambda r: httpx.Response(500))
    assert KEY not in repr(setup.provider) and WEBHOOK not in repr(setup.provider)


def test_checkout_uses_server_catalog_account_metadata_and_idempotency():
    setup = Setup(lambda r: httpx.Response(200, json=checkout_payload()))
    session = setup.provider.create_web_checkout("intent_1", PRODUCT, "acct_1", setup.ctx())
    assert session.provider_session_ref == "cs_test_1"
    assert session.redirect_url.startswith("https://checkout.stripe.com/")
    [request] = setup.seen
    assert request.url.path == "/v1/checkout/sessions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["stripe-version"] == API_VERSION
    assert request.headers["idempotency-key"] == "intent_1"
    form = parse_qs(request.content.decode())
    assert form["mode"] == ["payment"]
    assert form["line_items[0][price]"] == ["price_test_1"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["client_reference_id"] == ["acct_1"]
    for prefix in ("metadata", "payment_intent_data[metadata]"):
        assert form[f"{prefix}[internal_product_id]"] == ["premium_single"]
        assert form[f"{prefix}[store_product_id]"] == ["price_test_1"]
        assert form[f"{prefix}[account_ref]"] == ["acct_1"]
        assert form[f"{prefix}[environment]"] == ["test"]
        assert form[f"{prefix}[intent_ref]"] == ["intent_1"]


def test_checkout_rejects_wrong_catalog_and_cross_environment_before_http():
    setup = Setup(lambda r: httpx.Response(200, json=checkout_payload()))
    wrong = payments.CatalogProduct("premium_single", payments.PaymentRail.STRIPE, "price_other", 1)
    with pytest.raises(InvalidInput):
        setup.provider.create_web_checkout("intent_1", wrong, "acct_1", setup.ctx())
    with pytest.raises(InvalidInput):
        setup.provider.create_web_checkout("intent_1", PRODUCT, "acct_1", setup.ctx(Environment.STAGING))
    assert setup.seen == []


def test_raw_body_signature_is_verified_before_event_parsing():
    setup = Setup(lambda r: httpx.Response(500))
    payload = {
        "id": "evt_test_1",
        "type": "checkout.session.completed",
        "created": int(setup.clock.now().timestamp()),
        "livemode": False,
        "data": {"object": {
            "object": "checkout.session",
            "payment_intent": "pi_test_1",
            "metadata": {"environment": "test"},
        }},
    }
    body, headers = setup.signed_event(payload)
    event = setup.provider.verify_and_normalize_event(body, headers, setup.ctx())
    assert event.transaction_refs == ("pi_test_1",)
    assert event.environment is Environment.TEST

    with pytest.raises(Unauthenticated):
        setup.provider.verify_and_normalize_event(body + b" ", headers, setup.ctx())
    stale_body, stale = setup.signed_event(payload, timestamp=int(setup.clock.now().timestamp()) - 301)
    with pytest.raises(Unauthenticated):
        setup.provider.verify_and_normalize_event(stale_body, stale, setup.ctx())
    with pytest.raises(Unauthenticated):
        setup.provider.verify_and_normalize_event(body, {"Stripe-Signature": "t=1,v1=00"}, setup.ctx())


def test_verified_irrelevant_event_is_a_noop_and_relevant_shape_fails_closed():
    setup = Setup(lambda r: httpx.Response(500))
    irrelevant = {
        "id": "evt_test_2",
        "type": "customer.updated",
        "created": int(setup.clock.now().timestamp()),
        "livemode": False,
        "data": {"object": {"object": "customer", "id": "cus_test_1"}},
    }
    body, headers = setup.signed_event(irrelevant)
    assert setup.provider.verify_and_normalize_event(body, headers, setup.ctx()).transaction_refs == ()

    malformed = {**irrelevant, "id": "evt_test_3", "type": "payment_intent.succeeded",
                 "data": {"object": {"object": "customer", "id": "cus_test_1"}}}
    body, headers = setup.signed_event(malformed)
    with pytest.raises(InvalidInput):
        setup.provider.verify_and_normalize_event(body, headers, setup.ctx())


def test_authoritative_lookup_binds_product_account_environment_and_refund_state():
    setup = Setup(lambda r: httpx.Response(200, json=pi()))
    observed = setup.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", setup.ctx())
    assert observed.state is payments.PurchaseState.PURCHASED
    assert observed.account_binding is payments.AccountBinding.MATCHED
    assert observed.product_id == "premium_single"
    assert observed.environment is Environment.TEST
    assert observed.completion_action is payments.CompletionAction.NONE

    mismatch = setup.provider.retrieve_authoritative_purchase("pi_test_1", "acct_other", setup.ctx())
    assert mismatch.account_binding is payments.AccountBinding.MISMATCHED

    refunded = Setup(lambda r: httpx.Response(200, json=pi(refunded=True, amount_refunded=999)))
    assert refunded.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", refunded.ctx()).state is \
        payments.PurchaseState.REFUNDED

    partial = Setup(lambda r: httpx.Response(200, json=pi(amount_refunded=100)))
    assert partial.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", partial.ctx()).state is \
        payments.PurchaseState.UNKNOWN


@pytest.mark.parametrize("status,state", [
    ("processing", payments.PurchaseState.PENDING),
    ("requires_action", payments.PurchaseState.PENDING),
    ("requires_payment_method", payments.PurchaseState.FAILED),
    ("canceled", payments.PurchaseState.CANCELLED),
    ("something_new", payments.PurchaseState.UNKNOWN),
])
def test_payment_intent_states_never_upgrade_unknown_or_failed_to_purchased(status, state):
    setup = Setup(lambda r: httpx.Response(200, json=pi(status=status)))
    assert setup.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", setup.ctx()).state is state


def test_unknown_product_or_missing_environment_cannot_be_grant_ready():
    unknown = Setup(lambda r: httpx.Response(200, json=pi(product="other_product", store_product="price_other")))
    observation = unknown.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", unknown.ctx())
    assert observation.product_id == "other_product"

    missing_env = Setup(lambda r: httpx.Response(200, json=pi(environment="not-an-environment")))
    observation = missing_env.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", missing_env.ctx())
    assert observation.environment is Environment.LOCAL


def test_reconcile_is_bounded_paginated_and_uses_authoritative_payment_intents():
    calls = []

    def handler(request):
        calls.append(request)
        params = dict(request.url.params.multi_items())
        if "starting_after" not in params:
            return httpx.Response(200, json={"object": "list", "data": [pi("pi_test_1")], "has_more": True})
        assert params["starting_after"] == "pi_test_1"
        return httpx.Response(200, json={"object": "list", "data": [pi("pi_test_2")], "has_more": False})

    setup = Setup(handler)
    observations = setup.provider.reconcile(setup.clock.now() - timedelta(hours=1), setup.ctx())
    assert [o.transaction_ref for o in observations] == ["pi_test_1", "pi_test_2"]
    assert all(o.state is payments.PurchaseState.PURCHASED for o in observations)
    assert len(calls) == 2
    first = dict(calls[0].url.params.multi_items())
    assert first["limit"] == "100" and first["expand[]"] == "data.latest_charge"
    assert first["created[gte]"].isdigit()


@pytest.mark.parametrize("response,error", [
    (httpx.Response(429, headers={"retry-after": "5"}, json={"error": {"message": "slow"}}), RateLimited),
    (httpx.Response(503, json={"error": {"message": "down"}}), TransientUnavailable),
    (httpx.Response(401, json={"error": {"message": KEY}}), PermanentFailure),
    (httpx.Response(400, json={"error": {"message": "bad request details"}}), PermanentFailure),
])
def test_http_failures_are_typed_and_provider_messages_are_redacted(response, error):
    setup = Setup(lambda r: response)
    with pytest.raises(error) as err:
        setup.provider.retrieve_authoritative_purchase("pi_test_1", "acct_1", setup.ctx())
    assert KEY not in str(err.value) and "bad request" not in str(err.value)


def test_mutating_timeout_is_ambiguous_but_connect_failure_is_retryable():
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    timed = Setup(timeout)
    with pytest.raises(AmbiguousOutcome):
        timed.provider.create_web_checkout("intent_1", PRODUCT, "acct_1", timed.ctx())
    unreachable = Setup(refused)
    with pytest.raises(TransientUnavailable):
        unreachable.provider.create_web_checkout("intent_1", PRODUCT, "acct_1", unreachable.ctx())


def test_stripe_does_not_claim_native_or_refund_capabilities():
    setup = Setup(lambda r: httpx.Response(500))
    assert payments.VERIFY_PROOF not in setup.provider.profile.capabilities
    assert payments.REFUND_REQUEST not in setup.provider.profile.capabilities
    with pytest.raises(Unsupported):
        setup.provider.verify_purchase("proof", "acct_1", setup.ctx())
    with pytest.raises(Unsupported):
        setup.provider.request_refund_if_supported("pi_test_1", setup.ctx())
