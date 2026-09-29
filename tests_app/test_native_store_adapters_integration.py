"""Real-adapter-shaped Apple/Google observations flowing through the PostgreSQL T19 ledger."""
from __future__ import annotations

from princess_app.adapters.fakes import SequentialIds
from princess_app.adapters.postgres.commerce import PostgresLedger
from princess_app.adapters.postgres.stores import PostgresReportStore
from princess_app.application.commerce import CommerceService
from princess_app.domain.commerce import Platform
from princess_app.ports.base import Environment
from princess_app.ports.payments import PaymentRail
from test_apple_adapter import Setup as AppleSetup
from test_google_play_adapter import Setup as GoogleSetup, TOKEN
from test_intake import Env
from test_persistence import account, world  # noqa: F401 - fixture re-export


def service(env, provider):
    return CommerceService(
        ledger=PostgresLedger(env.app_db, SequentialIds()),
        providers={provider.rail: provider},
        permissions=env.permissions,
        reports=lambda owner: PostgresReportStore(env.app_db, owner),
        clock=env.clock,
        ids=SequentialIds(),
        environment=Environment.TEST,
    )


def test_apple_signed_transaction_grants_once_and_requires_client_finish(app_db, worker_db, world):  # noqa: F811
    env = Env(app_db, worker_db)
    owner = account(world, "apple-real-adapter").principal_id
    ledger = PostgresLedger(app_db, SequentialIds())
    account_ref = ledger.account_ref(owner, env.clock.now())

    setup = AppleSetup()
    setup.transaction = setup.txn(account=account_ref)
    commerce = CommerceService(
        ledger=ledger,
        providers={PaymentRail.APPLE_APP_STORE: setup.provider},
        permissions=env.permissions,
        reports=lambda principal: PostgresReportStore(app_db, principal),
        clock=env.clock,
        ids=SequentialIds(),
        environment=Environment.TEST,
    )
    proof = setup.sign(setup.transaction)
    first = commerce.claim_store_purchase(owner, PaymentRail.APPLE_APP_STORE, proof, env.ctx())
    second = commerce.claim_store_purchase(owner, PaymentRail.APPLE_APP_STORE, proof, env.ctx())
    assert (first.outcome, first.finish_on_client) == ("granted", True)
    assert (second.outcome, second.finish_on_client) == ("already_granted", True)
    assert commerce.balance(owner, Platform.IOS).available == 1
    assert commerce.balance(owner, Platform.WEB).available == 0


def test_google_productsv2_grants_once_then_consumes_after_durable_grant(app_db, worker_db, world):  # noqa: F811
    env = Env(app_db, worker_db)
    owner = account(world, "google-real-adapter").principal_id
    ledger = PostgresLedger(app_db, SequentialIds())
    account_ref = ledger.account_ref(owner, env.clock.now())

    setup = GoogleSetup()
    setup.purchase = setup.product(account=account_ref)
    commerce = CommerceService(
        ledger=ledger,
        providers={PaymentRail.GOOGLE_PLAY: setup.provider},
        permissions=env.permissions,
        reports=lambda principal: PostgresReportStore(app_db, principal),
        clock=env.clock,
        ids=SequentialIds(),
        environment=Environment.TEST,
    )
    first = commerce.claim_store_purchase(owner, PaymentRail.GOOGLE_PLAY, TOKEN, env.ctx())
    second = commerce.claim_store_purchase(owner, PaymentRail.GOOGLE_PLAY, TOKEN, env.ctx())
    assert (first.outcome, first.finish_on_client) == ("granted", False)
    assert (second.outcome, second.finish_on_client) == ("already_granted", False)
    assert commerce.balance(owner, Platform.ANDROID).available == 1
    assert commerce.balance(owner, Platform.WEB).available == 0
    assert any(request.url.path.endswith(f"/tokens/{TOKEN}:consume") for request in setup.seen)
