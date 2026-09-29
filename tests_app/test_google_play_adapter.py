"""Google Play server adapter tests with mocked Developer API and authenticated RTDN."""
from __future__ import annotations

import base64
import json
from datetime import timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from princess_app.adapters.fakes import FakeClock
from princess_app.adapters.google import GooglePlayPaymentProvider
from princess_app.domain.commerce import CATALOG
from princess_app.ports import payments
from princess_app.ports.base import CallContext, Environment, InvalidInput, ProviderMode, Unauthenticated, Unsupported

PACKAGE = "se.inktrospect.test"
ACCOUNT = "11111111-1111-4111-8111-111111111111"
TOKEN = "purchase_token_123"


class Setup:
    def __init__(self, catalog=CATALOG):
        self.clock = FakeClock()
        self.service_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pubsub_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.purchase = self.product()
        self.voided_pages = []
        self.seen = []

        def handler(request):
            self.seen.append(request)
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(200, json={"access_token": "access-test", "expires_in": 3600})
            if request.url.path.endswith("/purchases/voidedpurchases"):
                index = 1 if request.url.params.get("pageSelection.token") else 0
                return httpx.Response(200, json=self.voided_pages[index] if self.voided_pages else {
                    "voidedPurchases": [], "tokenPagination": {},
                })
            if "/purchases/productsv2/tokens/" in request.url.path:
                return httpx.Response(200, json=self.purchase)
            if request.url.path.endswith(":consume") or request.url.path.endswith(":acknowledge"):
                return httpx.Response(204)
            return httpx.Response(404, json={})

        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.pubsub_key.public_key()))
        public.update({"kid": "pubsub-key-1", "alg": "RS256", "use": "sig"})
        service_pem = self.service_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        self.provider = GooglePlayPaymentProvider(
            package_name=PACKAGE,
            service_account={
                "client_email": "publisher@example.iam.gserviceaccount.com",
                "private_key": service_pem,
                "private_key_id": "service-key-1",
            },
            pubsub_audience="https://api.example.test/v1/payments/google_play/events",
            pubsub_service_account_email="push@example.iam.gserviceaccount.com",
            catalog=catalog,
            clock=self.clock,
            environment=Environment.TEST,
            mode=ProviderMode.SANDBOX,
            activation_approved=True,
            transport=httpx.MockTransport(handler),
            pubsub_jwks_source=lambda: {"keys": [public]},
        )

    def ctx(self, env=Environment.TEST):
        return CallContext("corr_google", env, self.clock.now() + timedelta(seconds=30))

    def product(self, *, state="PURCHASED", account=ACCOUNT, product="premium_single_draft",
                refundable=1, consumed=False):
        return {
            "kind": "androidpublisher#productPurchaseV2",
            "purchaseStateContext": {"purchaseState": state},
            "testPurchaseContext": {"fopType": "TEST"},
            "orderId": "GPA.1234-5678-9012-34567",
            "obfuscatedExternalAccountId": account,
            "purchaseCompletionTime": self.clock.now().isoformat().replace("+00:00", "Z"),
            "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
            "productLineItem": [{
                "productId": product,
                "productOfferDetails": {
                    "quantity": 1,
                    "refundableQuantity": refundable,
                    "consumptionState": (
                        "CONSUMPTION_STATE_CONSUMED" if consumed
                        else "CONSUMPTION_STATE_YET_TO_BE_CONSUMED"
                    ),
                },
            }],
        }

    def pubsub_token(self, *, audience=None, email="push@example.iam.gserviceaccount.com"):
        now = int(self.clock.now().timestamp())
        return jwt.encode(
            {
                "iss": "https://accounts.google.com",
                "aud": audience or "https://api.example.test/v1/payments/google_play/events",
                "email": email,
                "email_verified": True,
                "iat": now,
                "exp": now + 300,
            },
            self.pubsub_key,
            algorithm="RS256",
            headers={"kid": "pubsub-key-1"},
        )

    def rtdn(self, notification=None):
        data = notification or {
            "version": "1.0",
            "packageName": PACKAGE,
            "eventTimeMillis": str(int(self.clock.now().timestamp() * 1000)),
            "oneTimeProductNotification": {
                "version": "1.0",
                "notificationType": 1,
                "purchaseToken": TOKEN,
                "sku": "premium_single_draft",
            },
        }
        envelope = {
            "message": {
                "messageId": "message-1",
                "data": base64.b64encode(json.dumps(data).encode()).decode(),
            },
            "subscription": "projects/p/subscriptions/s",
        }
        return json.dumps(envelope).encode(), {"Authorization": "Bearer " + self.pubsub_token()}


def test_productsv2_verification_binds_purchase_token_account_and_product():
    setup = Setup()
    obs = setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    assert (obs.state, obs.account_binding, obs.product_id, obs.completion_action) == (
        payments.PurchaseState.PURCHASED,
        payments.AccountBinding.MATCHED,
        "premium_single",
        payments.CompletionAction.SERVER_CONSUME,
    )
    assert obs.transaction_ref == TOKEN and obs.completed is False
    mismatch = setup.provider.verify_purchase(TOKEN, "22222222-2222-4222-8222-222222222222", setup.ctx())
    assert mismatch.account_binding is payments.AccountBinding.MISMATCHED

    setup.purchase = setup.product(state="PENDING")
    assert setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx()).state is payments.PurchaseState.PENDING
    setup.purchase = setup.product(refundable=0)
    assert setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx()).state is payments.PurchaseState.REFUNDED


def test_sandbox_requires_a_test_purchase_and_unknown_product_never_grants():
    setup = Setup()
    setup.purchase = setup.product()
    del setup.purchase["testPurchaseContext"]
    with pytest.raises(InvalidInput):
        setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    setup.purchase = setup.product(product="other.sku")
    obs = setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    assert obs.product_id == "unknown_product"


def test_authenticated_rtdn_names_purchase_token_but_is_not_purchase_truth():
    setup = Setup()
    raw, headers = setup.rtdn()
    event = setup.provider.verify_and_normalize_event(raw, headers, setup.ctx())
    assert event.event_id == "message-1"
    assert event.transaction_refs == (TOKEN,)
    assert event.event_type == "one_time_product:1"

    bad = {"Authorization": "Bearer " + setup.pubsub_token(audience="https://wrong.example")}
    with pytest.raises(Unauthenticated):
        setup.provider.verify_and_normalize_event(raw, bad, setup.ctx())

    wrong_package = {
        "version": "1.0",
        "packageName": "other.package",
        "eventTimeMillis": str(int(setup.clock.now().timestamp() * 1000)),
        "testNotification": {"version": "1.0"},
    }
    raw, headers = setup.rtdn(wrong_package)
    with pytest.raises(InvalidInput):
        setup.provider.verify_and_normalize_event(raw, headers, setup.ctx())


def test_server_consume_occurs_only_when_explicitly_called_after_grant():
    setup = Setup()
    obs = setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    assert obs.completed is False
    setup.provider.complete_store_purchase(TOKEN, payments.CompletionAction.SERVER_CONSUME, setup.ctx())
    paths = [request.url.path for request in setup.seen]
    assert any("/purchases/productsv2/tokens/" in path for path in paths)
    assert any(path.endswith(f"/purchases/products/premium_single_draft/tokens/{TOKEN}:consume") for path in paths)


def test_non_consumable_uses_server_acknowledge():
    custom = list(CATALOG)
    custom = [
        payments.CatalogProduct(p.product_id, p.rail, p.store_product_id, p.credits,
                                consumable=False if p.rail is payments.PaymentRail.GOOGLE_PLAY else p.consumable)
        for p in custom
    ]
    setup = Setup(tuple(custom))
    obs = setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    assert obs.completion_action is payments.CompletionAction.SERVER_ACKNOWLEDGE
    setup.provider.complete_store_purchase(TOKEN, payments.CompletionAction.SERVER_ACKNOWLEDGE, setup.ctx())
    assert any(request.url.path.endswith(f"/tokens/{TOKEN}:acknowledge") for request in setup.seen)


def test_service_account_assertion_and_access_token_are_server_side_only():
    setup = Setup()
    setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx())
    oauth = next(request for request in setup.seen if request.url.host == "oauth2.googleapis.com")
    form = dict(item.split("=", 1) for item in oauth.content.decode().split("&"))
    assertion = form["assertion"]
    header = jwt.get_unverified_header(assertion)
    claims = jwt.decode(
        assertion,
        setup.service_key.public_key(),
        algorithms=["RS256"],
        audience="https://oauth2.googleapis.com/token",
        options={"verify_exp": False, "verify_iat": False},
    )
    assert header["kid"] == "service-key-1"
    assert claims["scope"] == "https://www.googleapis.com/auth/androidpublisher"
    api = next(request for request in setup.seen if request.url.host == "androidpublisher.googleapis.com")
    assert api.headers["authorization"] == "Bearer access-test"
    assert "access-test" not in repr(setup.provider)


def test_voided_purchase_reconcile_requeries_authoritative_product_state():
    setup = Setup()
    setup.purchase = setup.product(refundable=0)
    setup.voided_pages = [{
        "voidedPurchases": [{"purchaseToken": TOKEN, "voidedTimeMillis": "1"}],
        "tokenPagination": {},
    }]
    rows = setup.provider.reconcile(setup.clock.now() - timedelta(hours=1), setup.ctx())
    assert len(rows) == 1 and rows[0].state is payments.PurchaseState.REFUNDED
    voided = next(r for r in setup.seen if r.url.path.endswith("/purchases/voidedpurchases"))
    assert voided.url.params.get("type") == "0" and voided.url.params.get("startTime")
    assert voided.url.params.get("includeQuantityBasedPartialRefund") == "true"


def test_voided_purchase_reconcile_uses_documented_token_paging():
    setup = Setup()
    setup.purchase = setup.product(refundable=0)
    setup.voided_pages = [
        {
            "voidedPurchases": [{"purchaseToken": TOKEN, "voidedTimeMillis": "1", "voidedQuantity": 1}],
            "tokenPagination": {"nextPageToken": "page-2"},
        },
        {"voidedPurchases": [], "tokenPagination": {}},
    ]
    rows = setup.provider.reconcile(setup.clock.now() - timedelta(hours=1), setup.ctx())
    assert len(rows) == 1 and rows[0].transaction_ref == TOKEN
    calls = [r for r in setup.seen if r.url.path.endswith("/purchases/voidedpurchases")]
    assert len(calls) == 2
    assert calls[1].url.params.get("pageSelection.token") == "page-2"
    assert calls[1].url.params.get("includeQuantityBasedPartialRefund") == "true"


def test_refund_remains_explicitly_unsupported():
    setup = Setup()
    with pytest.raises(Unsupported):
        setup.provider.request_refund_if_supported(TOKEN, setup.ctx())
    with pytest.raises(InvalidInput):
        setup.provider.verify_purchase(TOKEN, ACCOUNT, setup.ctx(Environment.PRODUCTION))
