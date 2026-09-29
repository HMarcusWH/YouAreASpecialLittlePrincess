"""Apple App Store server adapter tests with an in-process JWS trust chain."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from princess_app.adapters.apple import AppleAppStorePaymentProvider
from princess_app.adapters.fakes import FakeClock
from princess_app.domain.commerce import CATALOG
from princess_app.ports import payments
from princess_app.ports.base import (
    CallContext,
    Environment,
    InvalidInput,
    ProviderMode,
    Unauthenticated,
    Unsupported,
)

BUNDLE = "se.inktrospect.test"
ACCOUNT = "11111111-1111-4111-8111-111111111111"
PRODUCT = "se.princess.premium.single.draft"


def certificate(subject, issuer, public_key, issuer_key, *, ca):
    now = datetime.now(timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(issuer_key, hashes.SHA256())
    )


class Setup:
    def __init__(self):
        self.clock = FakeClock()
        self.root_key = ec.generate_private_key(ec.SECP256R1())
        self.root = certificate("Root", "Root", self.root_key.public_key(), self.root_key, ca=True)
        self.leaf_key = ec.generate_private_key(ec.SECP256R1())
        self.leaf = certificate("Leaf", "Root", self.leaf_key.public_key(), self.root_key, ca=False)
        self.api_key = ec.generate_private_key(ec.SECP256R1())
        self.seen = []
        self.transaction = self.txn()

        def handler(request):
            self.seen.append(request)
            if request.url.path == "/inApps/v1/transactions/2000000000001":
                return httpx.Response(200, json={"signedTransactionInfo": self.sign(self.transaction)})
            return httpx.Response(404, json={})

        self.provider = AppleAppStorePaymentProvider(
            bundle_id=BUNDLE,
            issuer_id="issuer-test",
            key_id="KEYTEST1",
            private_key_pem=self.api_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            trusted_root_certificates=[self.root.public_bytes(serialization.Encoding.PEM)],
            catalog=CATALOG,
            clock=self.clock,
            environment=Environment.TEST,
            mode=ProviderMode.SANDBOX,
            activation_approved=True,
            transport=httpx.MockTransport(handler),
        )

    def ctx(self, env=Environment.TEST):
        return CallContext("corr_apple", env, self.clock.now() + timedelta(seconds=30))

    def sign(self, payload):
        x5c = [base64.b64encode(self.leaf.public_bytes(serialization.Encoding.DER)).decode()]
        return jwt.encode(payload, self.leaf_key, algorithm="ES256", headers={"x5c": x5c})

    def txn(self, *, account=ACCOUNT, product=PRODUCT, environment="Sandbox", revoked=False):
        now = int(self.clock.now().timestamp() * 1000)
        out = {
            "transactionId": "2000000000001",
            "originalTransactionId": "2000000000000",
            "bundleId": BUNDLE,
            "productId": product,
            "purchaseDate": now,
            "quantity": 1,
            "environment": environment,
            "appAccountToken": account,
        }
        if revoked:
            out["revocationDate"] = now + 1000
        return out


def test_purchase_jws_binds_account_product_bundle_and_environment():
    setup = Setup()
    obs = setup.provider.verify_purchase(setup.sign(setup.transaction), ACCOUNT, setup.ctx())
    assert (obs.state, obs.account_binding, obs.product_id, obs.completion_action) == (
        payments.PurchaseState.PURCHASED,
        payments.AccountBinding.MATCHED,
        "premium_single",
        payments.CompletionAction.CLIENT_FINISH,
    )
    assert obs.original_transaction_ref == "2000000000000"
    mismatch = setup.provider.verify_purchase(setup.sign(setup.transaction), "22222222-2222-4222-8222-222222222222",
                                             setup.ctx())
    assert mismatch.account_binding is payments.AccountBinding.MISMATCHED

    revoked = setup.provider.verify_purchase(setup.sign(setup.txn(revoked=True)), ACCOUNT, setup.ctx())
    assert revoked.state is payments.PurchaseState.REVOKED and revoked.refunded_at is not None


def test_wrong_bundle_environment_and_untrusted_certificate_fail_closed():
    setup = Setup()
    bad = setup.txn()
    bad["bundleId"] = "other.bundle"
    with pytest.raises(InvalidInput):
        setup.provider.verify_purchase(setup.sign(bad), ACCOUNT, setup.ctx())
    with pytest.raises(InvalidInput):
        setup.provider.verify_purchase(setup.sign(setup.txn(environment="Production")), ACCOUNT, setup.ctx())

    other_key = ec.generate_private_key(ec.SECP256R1())
    other_root = certificate("Other", "Other", other_key.public_key(), other_key, ca=True)
    other_leaf_key = ec.generate_private_key(ec.SECP256R1())
    other_leaf = certificate("OtherLeaf", "Other", other_leaf_key.public_key(), other_key, ca=False)
    token = jwt.encode(
        setup.transaction,
        other_leaf_key,
        algorithm="ES256",
        headers={"x5c": [base64.b64encode(other_leaf.public_bytes(serialization.Encoding.DER)).decode()]},
    )
    with pytest.raises(Unauthenticated):
        setup.provider.verify_purchase(token, ACCOUNT, setup.ctx())


def test_v2_notification_verifies_outer_and_nested_jws():
    setup = Setup()
    now = int(setup.clock.now().timestamp() * 1000)
    signed_transaction = setup.sign(setup.transaction)
    outer = setup.sign({
        "notificationUUID": "notification-1",
        "notificationType": "ONE_TIME_CHARGE",
        "signedDate": now,
        "data": {
            "bundleId": BUNDLE,
            "environment": "Sandbox",
            "signedTransactionInfo": signed_transaction,
        },
    })
    raw = json.dumps({"signedPayload": outer}).encode()
    event = setup.provider.verify_and_normalize_event(raw, {}, setup.ctx())
    assert event.event_id == "notification-1"
    assert event.transaction_refs == ("2000000000001",)
    assert event.event_type == "ONE_TIME_CHARGE"

    tampered = outer[:-1] + ("A" if outer[-1] != "A" else "B")
    with pytest.raises(Unauthenticated):
        setup.provider.verify_and_normalize_event(json.dumps({"signedPayload": tampered}).encode(), {}, setup.ctx())


def test_authoritative_lookup_uses_server_jwt_and_reverifies_signed_transaction():
    setup = Setup()
    obs = setup.provider.retrieve_authoritative_purchase("2000000000001", ACCOUNT, setup.ctx())
    assert obs.state is payments.PurchaseState.PURCHASED
    [request] = setup.seen
    assert request.url.path == "/inApps/v1/transactions/2000000000001"
    scheme, token = request.headers["authorization"].split(" ", 1)
    assert scheme == "Bearer"
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, setup.api_key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1")
    assert header["kid"] == "KEYTEST1"
    assert claims["iss"] == "issuer-test" and claims["bid"] == BUNDLE


def test_unimplemented_server_completion_refund_and_reconcile_are_explicit():
    setup = Setup()
    with pytest.raises(Unsupported):
        setup.provider.complete_store_purchase("2000000000001", payments.CompletionAction.CLIENT_FINISH, setup.ctx())
    with pytest.raises(Unsupported):
        setup.provider.request_refund_if_supported("2000000000001", setup.ctx())
    with pytest.raises(Unsupported):
        setup.provider.reconcile(setup.clock.now(), setup.ctx())
    with pytest.raises(InvalidInput):
        setup.provider.verify_purchase(setup.sign(setup.transaction), ACCOUNT, setup.ctx(Environment.PRODUCTION))
