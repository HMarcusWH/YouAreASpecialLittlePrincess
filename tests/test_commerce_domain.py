"""T19 domain rules: what an observation may do, spend eligibility, operation keys."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from princess_app.domain.commerce import (
    CATALOG,
    PREMIUM_SINGLE,
    GrantDecision,
    Platform,
    assess,
    catalog_entry,
    premium_operation_key,
    spendable_rails,
)
from princess_app.ports.base import Environment, InvalidInput
from princess_app.ports.payments import (
    AccountBinding,
    CompletionAction,
    PaymentRail,
    PurchaseState,
    TransactionObservation,
)

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def observation(**overrides):
    base = dict(rail=PaymentRail.GOOGLE_PLAY, environment=Environment.TEST, transaction_ref="ptok_1",
                product_id=PREMIUM_SINGLE, quantity=1, state=PurchaseState.PURCHASED,
                account_binding=AccountBinding.MATCHED, completion_action=CompletionAction.SERVER_CONSUME,
                purchased_at=T0)
    return TransactionObservation(**{**base, **overrides})


@pytest.mark.parametrize("overrides,decision,reason", [
    ({}, GrantDecision.GRANT, "purchased"),
    ({"environment": Environment.PRODUCTION}, GrantDecision.REJECT, "wrong_environment"),
    ({"state": PurchaseState.PENDING}, GrantDecision.PENDING, "payment_pending"),
    ({"state": PurchaseState.CANCELLED}, GrantDecision.REJECT, "state_cancelled"),
    ({"state": PurchaseState.REFUNDED}, GrantDecision.REFUND, "refunded"),
    ({"state": PurchaseState.REVOKED}, GrantDecision.REFUND, "revoked"),
    ({"account_binding": AccountBinding.MISMATCHED}, GrantDecision.REJECT, "account_binding_mismatched"),
    ({"account_binding": AccountBinding.UNKNOWN}, GrantDecision.REJECT, "account_binding_unknown"),
    ({"product_id": "premium_forty"}, GrantDecision.REJECT, "unknown_product"),
])
def test_only_authoritative_purchases_of_catalog_products_grant(overrides, decision, reason):
    outcome = assess(observation(**overrides), environment=Environment.TEST)
    assert (outcome.decision, outcome.reason) == (decision, reason)


def test_catalog_maps_every_rail_and_carries_no_prices():
    assert {entry.rail for entry in CATALOG} == set(PaymentRail)
    assert all(entry.credits == 1 for entry in CATALOG)
    assert catalog_entry(PREMIUM_SINGLE, PaymentRail.STRIPE).store_product_id.endswith("_draft")
    assert not any(hasattr(entry, "price") for entry in CATALOG)


def test_default_spend_policy_keeps_credits_on_their_origin_platform():
    assert spendable_rails(Platform.WEB) == (PaymentRail.STRIPE,)
    assert spendable_rails(Platform.IOS) == (PaymentRail.APPLE_APP_STORE,)
    portable = {rail: frozenset(Platform) for rail in PaymentRail}
    assert set(spendable_rails(Platform.ANDROID, portable)) == set(PaymentRail)


def test_operation_keys_identify_one_intended_deliverable():
    key = premium_operation_key("prn_1", "report_1", 1, "en", "premium-policy-1")
    assert key == premium_operation_key("prn_1", "report_1", 1, "en", "premium-policy-1")
    assert key != premium_operation_key("prn_1", "report_1", 2, "en", "premium-policy-1")
    with pytest.raises(InvalidInput):
        premium_operation_key("prn_1", "report_1", 0, "en", "premium-policy-1")
