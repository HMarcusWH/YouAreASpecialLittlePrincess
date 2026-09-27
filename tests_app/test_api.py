"""HTTP boundary over PostgreSQL stores with fake identity (T02)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from princess_api import Services, create_app
from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, FakePaymentProvider, SequentialIds
from princess_app.adapters.postgres.commerce import PostgresLedger
from princess_app.adapters.postgres.stores import (
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
)
from princess_app.application.commerce import CommerceService
from princess_app.application.identity import IdentityService
from princess_app.application.permissions import PermissionService
from princess_app.domain.commerce import CATALOG
from princess_app.ports.base import Environment
from princess_app.ports.payments import PaymentRail
from princess_contracts import compile_document
from test_persistence import publish_report

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(app_db):
    clock = FakeClock(T0)
    provider = FakeIdentityProvider(clock=clock)
    services = Services(
        environment=Environment.TEST, clock=clock,
        identity=IdentityService(provider, PostgresIdentityStore(app_db), clock, SequentialIds(), "princess-api"),
        permissions=PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds(),
                                      allow_draft_policy=True),
        report_store_for=lambda pid: PostgresReportStore(app_db, pid),
        kill_switches={"commerce": False, "sharing": True}, dev_identity=provider)
    return TestClient(create_app(services)), clock


def login(api, subject):
    token = api.post("/v1/dev/id-tokens", json={"subject": subject}).json()["id_token"]
    return {"Authorization": f"Bearer {token}"}


def test_authentication_is_required_and_errors_are_typed(client):
    api, _ = client
    assert api.get("/v1/me").status_code == 401
    bad = api.get("/v1/me", headers={"Authorization": "Bearer fakeid.kid-1.tok_404"})
    assert bad.status_code == 401 and bad.json() == {"error": "malformed_or_unknown_token"}
    assert bad.headers["www-authenticate"] == "Bearer"


def test_login_me_and_owner_scoped_report_reads(client, app_db):
    api, _ = client
    alice, bob = login(api, "alice"), login(api, "bob")
    alice_id = api.get("/v1/me", headers=alice).json()["principal_id"]
    api.get("/v1/me", headers=bob)
    report = publish_report(app_db, alice_id)
    rid = report.data["report_id"]
    view = api.get(f"/v1/reports/{rid}?projection=FREE", headers=alice)
    assert view.status_code == 200
    compiled = compile_document("ReportViewModel", view.json())
    assert compiled.ok and compiled.value.data["projection"] == "FREE"
    purchase = next(a for a in view.json()["actions"] if a["kind"] == "PURCHASE")
    assert purchase == {"action_id": "action.purchase", "kind": "PURCHASE", "enabled": False,
                        "reason": "commerce_disabled"}
    assert api.get(f"/v1/reports/{rid}", headers=bob).status_code == 404
    assert api.get("/v1/reports/report_guess", headers=alice).status_code == 404
    assert api.get(f"/v1/reports/{rid}?projection=PREMIUM", headers=alice).status_code == 403  # no unlocked overlay


def test_permission_lifecycle_returns_contract_grant_snapshots(client):
    api, clock = client
    alice = login(api, "alice")
    body = {"purpose_id": "third_party_ai_processing", "scope_kind": "REPORT", "scope_ref": "report_1",
            "decision": "GRANT", "notice_version": "notice.consent-choices:1"}
    granted = api.post("/v1/me/permissions", json=body, headers=alice)
    assert granted.status_code == 201 and compile_document("GrantSnapshot", granted.json()).ok
    assert granted.json()["status"] == "GRANTED" and granted.json()["scope"] == "REPORT:report_1"
    check = api.get("/v1/me/permissions/third_party_ai_processing?scope_kind=REPORT&scope_ref=report_1",
                    headers=alice)
    assert check.json()["allowed"] is True
    clock.advance(1)
    api.post("/v1/me/permissions", headers=alice, json={**body, "scope_kind": "SUBJECT_WIDE", "scope_ref": None,
                                                         "decision": "WITHDRAW"})
    assert api.get("/v1/me/permissions/third_party_ai_processing?scope_kind=REPORT&scope_ref=report_1",
                   headers=alice).json() == {"purpose_id": "third_party_ai_processing", "allowed": False,
                                             "reason": "withdraw"}
    sharing = api.post("/v1/me/permissions", headers=alice, json={**body, "purpose_id": "ordinary_sharing",
                                                                   "scope_kind": "SHARE_GRANT"})
    assert sharing.status_code == 201
    assert api.get("/v1/me/permissions/partner_comparison?scope_kind=COMPARISON&scope_ref=report_1",
                   headers=alice).json()["allowed"] is False
    bad = api.post("/v1/me/permissions", headers=alice, json={**body, "purpose_id": "model_training",
                                                               "scope_kind": "SUBJECT_WIDE", "scope_ref": None})
    assert bad.status_code == 422
    extra = api.post("/v1/me/permissions", headers=alice, json={**body, "precheck": True})
    assert extra.status_code == 422


def test_guest_flow_transfer_and_deletion(client, app_db):
    api, clock = client
    guest = api.post("/v1/guest-sessions").json()
    guest_headers = {"Authorization": f"Bearer {guest['guest_token']}"}
    assert api.get("/v1/me", headers=guest_headers).json()["kind"] == "GUEST"
    publish_report(app_db, guest["principal_id"])
    alice = login(api, "alice")
    moved = api.post("/v1/me/guest-transfer", json={"guest_token": guest["guest_token"]}, headers=alice)
    assert moved.status_code == 200 and moved.json()["transferred_principal_id"] == guest["principal_id"]
    assert api.get("/v1/me", headers=guest_headers).status_code == 401
    again = api.post("/v1/me/guest-transfer", json={"guest_token": guest["guest_token"]}, headers=alice)
    assert again.status_code == 409
    assert api.get("/v1/reports/report_run_1", headers=alice).status_code == 200
    clock.advance(1)
    assert api.delete("/v1/me", headers=alice).status_code == 202
    assert api.get("/v1/me", headers=alice).status_code == 401


def test_logout_everywhere_revokes_outstanding_tokens(client):
    api, clock = client
    alice = login(api, "alice")
    api.get("/v1/me", headers=alice)
    clock.advance(1)
    assert api.post("/v1/me/logout-everywhere", headers=alice).status_code == 204
    assert api.get("/v1/me", headers=alice).status_code == 401
    clock.advance(1)
    assert api.get("/v1/me", headers=login(api, "alice")).status_code == 200


def test_dev_token_route_only_exists_in_local_and_test(app_db):
    clock = FakeClock(T0)
    provider = FakeIdentityProvider(clock=clock, environment=Environment.PREVIEW)
    services = Services(
        environment=Environment.PREVIEW, clock=clock,
        identity=IdentityService(provider, PostgresIdentityStore(app_db), clock, SequentialIds(), "princess-api"),
        permissions=PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds(),
                                      allow_draft_policy=True),
        report_store_for=lambda pid: PostgresReportStore(app_db, pid), dev_identity=provider)
    assert TestClient(create_app(services)).post("/v1/dev/id-tokens", json={"subject": "x"}).status_code == 404


def test_report_fixture_parity_between_store_and_api(client, app_db):
    api, _ = client
    alice = login(api, "alice")
    alice_id = api.get("/v1/me", headers=alice).json()["principal_id"]
    report = publish_report(app_db, alice_id)
    served = api.get(f"/v1/reports/{report.data['report_id']}", headers=alice).json()
    assert served["source_digest"] == report.data["document_digest"]
    assert json.dumps(sorted(f["fact_id"] for f in served["facts"])) == json.dumps(
        sorted(f["fact_id"] for f in report.data["facts"]))


def test_every_api_route_is_a_registered_telemetry_template(client):
    from princess_app.ports.telemetry import ROUTE_TEMPLATES

    api, _ = client
    paths = {route.path for route in api.app.routes if route.path.startswith("/v1/")}
    assert paths and paths <= ROUTE_TEMPLATES


def test_composed_local_stack_upload_to_report(app_url, worker_db, tmp_path, monkeypatch):
    """compose() from a validated local config, then a separately built worker
    sharing only the database and the filesystem store."""
    import hashlib
    from urllib.parse import urlsplit

    from princess_api.compose import compose
    from princess_app.adapters.imaging import decode_image
    from princess_app.adapters.localfs import LocalObjectStore
    from princess_app.adapters.postgres.intake import PostgresJobQueue
    from princess_app.application.analysis_worker import AnalysisWorker
    from princess_app.config import load_runtime_config
    from princess_app.ports.base import CallContext, SystemClock
    from princess_graphology import GraphologyEngine, __version__
    from test_intake import handwriting_png

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PRINCESS_LOCAL_STORAGE_DIR", str(tmp_path))
    # The integration database is princess_test, so compose with the reviewed "test" manifest.
    env = {"PRINCESS_ENV": "test", "PRINCESS_COMPONENT": "api", "PRINCESS_DATABASE_URL": app_url,
           "PRINCESS_SESSION_SECRET": "session-secret-0123456789", "PRINCESS_IDENTITY_AUDIENCE": "princess-test",
           "PRINCESS_STORAGE_SIGNING_KEY": "signing-key-0123456789"}
    services = compose(load_runtime_config(env, root))
    api = TestClient(create_app(services))
    token = api.post("/v1/dev/id-tokens", json={"subject": "stack-user"}).json()["id_token"]
    auth = {"Authorization": f"Bearer {token}"}
    data = handwriting_png()
    ticket = api.post("/v1/uploads", json={"media_type": "image/png"}, headers=auth).json()
    path = urlsplit(ticket["url"])
    assert api.put(path.path + "?" + path.query, content=data, headers={"content-type": "image/png"}).status_code == 204
    bad_sig = api.put(path.path + "?sig=" + "0" * 64, content=data, headers={"content-type": "image/png"})
    assert bad_sig.status_code == 401
    from princess_app.domain.intake import MAX_UPLOAD_BYTES
    random_id = "/v1/dev/uploads/upl_random?sig=" + "0" * 64  # size is checked before the ID or signature
    assert api.put(random_id, content=b"x" * (MAX_UPLOAD_BYTES + 1)).status_code == 413
    chunked = api.put(random_id, content=iter([b"x" * (1 << 20)] * 21))  # no declared length
    assert chunked.status_code == 413
    capture = api.post(f"/v1/uploads/{ticket['upload_id']}/complete",
                       json={"sha256": hashlib.sha256(data).hexdigest()}, headers=auth).json()
    assert api.post("/v1/analyses", json={"capture_id": capture["capture_id"]}, headers=auth).status_code == 403
    grant = {"purpose_id": "service_processing", "scope_kind": "SPECIMEN", "scope_ref": capture["capture_id"],
             "decision": "GRANT", "notice_version": "notice.consent-choices:1"}
    assert api.post("/v1/me/permissions", json=grant, headers=auth).status_code == 201
    started = api.post("/v1/analyses", json={"capture_id": capture["capture_id"]}, headers=auth)
    assert started.status_code == 202 and started.json()["state"] == "QUEUED"
    run_id = started.json()["run_id"]
    assert api.post("/v1/analyses", json={"capture_id": capture["capture_id"]}, headers=auth).json()["run_id"] == run_id
    clock = SystemClock()
    worker_store = LocalObjectStore(tmp_path, signing_key=b"worker-read-key-0123456789", clock=clock,
                                    environment=services.environment)
    worker = AnalysisWorker(queue=PostgresJobQueue(worker_db), store=worker_store, decode=decode_image,
                            engine=GraphologyEngine(), clock=clock,
                            context=lambda: CallContext("w", services.environment, clock.now() + timedelta(seconds=60)),
                            worker_id="stack-worker", engine_version=__version__)
    assert worker.run_once().outcome == "SUCCEEDED"
    status = api.get(f"/v1/analyses/{run_id}", headers=auth).json()
    assert status["state"] == "SUCCEEDED" and status["report_id"]
    report = api.get(f"/v1/reports/{status['report_id']}?projection=FREE", headers=auth)
    assert report.status_code == 200 and len(report.json()["facts"]) == 64
    assert api.get(f"/v1/reports/{status['report_id']}/premium", headers=auth).status_code == 403  # nothing bought
    export = api.post("/v1/report-exports", json={"report_id": status["report_id"], "layout": "A4"}, headers=auth)
    assert export.status_code == 202 and export.json()["state"] == "QUEUED"
    assert export.json()["downloaded_copies"] == "downloaded_copies_cannot_be_recalled"
    export_id = export.json()["export_id"]
    assert api.get(f"/v1/report-exports/{export_id}", headers=auth).json()["state"] == "QUEUED"
    assert api.get(f"/v1/report-exports/{export_id}/file", headers=auth).status_code == 409  # not rendered yet
    other = {"Authorization": f"Bearer {api.post('/v1/guest-sessions').json()['guest_token']}"}
    assert api.get(f"/v1/report-exports/{export_id}", headers=other).status_code == 404
    assert api.delete(f"/v1/captures/{capture['capture_id']}", headers=auth).status_code == 202
    assert api.get(f"/v1/reports/{status['report_id']}", headers=auth).status_code == 404


def commerce_client(app_db, *, selling):  # noqa: D103
    clock = FakeClock(T0)
    provider = FakeIdentityProvider(clock=clock)
    permissions = PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds(), allow_draft_policy=True)
    rails = {rail: FakePaymentProvider(rail, catalog=CATALOG, clock=clock, environment=Environment.TEST)
             for rail in PaymentRail}
    commerce = CommerceService(ledger=PostgresLedger(app_db, SequentialIds()), providers=rails,
                               permissions=permissions, reports=lambda pid: PostgresReportStore(app_db, pid),
                               clock=clock, ids=SequentialIds(), environment=Environment.TEST)
    services = Services(
        environment=Environment.TEST, clock=clock,
        identity=IdentityService(provider, PostgresIdentityStore(app_db), clock, SequentialIds(), "princess-api"),
        permissions=permissions, report_store_for=lambda pid: PostgresReportStore(app_db, pid),
        kill_switches={"commerce": selling, "premium_generation": selling}, dev_identity=provider,
        commerce=commerce)
    return TestClient(create_app(services)), rails, services


def test_commerce_routes_need_accounts_verified_events_and_open_sales(app_db):
    api, rails, services = commerce_client(app_db, selling=True)
    catalog = api.get("/v1/catalog").json()["products"]
    assert [p["product_id"] for p in catalog] == ["premium_single"]
    assert "price" not in json.dumps(catalog).lower().replace("price_premium", "")  # prices are owner-gated
    guest = {"Authorization": f"Bearer {api.post('/v1/guest-sessions').json()['guest_token']}"}
    body = {"product_id": "premium_single", "intent_ref": "intent_0001"}
    assert api.post("/v1/checkout/web", json=body, headers=guest).status_code == 403  # accounts only
    alice = login(api, "alice")
    session = api.post("/v1/checkout/web", json=body, headers=alice)
    assert session.status_code == 201
    assert api.get("/v1/me/credits?platform=web", headers=alice).json()["available"] == 0  # redirect grants nothing
    stripe = rails[PaymentRail.STRIPE]
    ref = stripe.simulate_checkout_paid(next(iter(stripe._sessions)))
    raw, headers = stripe.signed_event("checkout.session.completed", [ref])
    forged = api.post("/v1/payments/stripe/events", content=raw, headers={"x-fake-signature": "t=1,v1=00"})
    assert forged.status_code == 401
    huge = api.post("/v1/payments/stripe/events", content=iter([b"{" * (64 << 10)] * 5))
    assert huge.status_code == 413  # cut off while streaming, before any signature work
    assert api.post("/v1/payments/stripe/events", content=raw, headers=headers).status_code == 200
    assert api.get("/v1/me/credits?platform=web", headers=alice).json() == {"platform": "web", "available": 1,
                                                                            "reserved": 0}
    assert api.post("/v1/reports/report_missing/premium", json={"platform": "web"},
                    headers=alice).status_code == 404

    services.kill_switches["commerce"] = False  # sales off: no new checkouts, webhooks still flow
    assert api.post("/v1/checkout/web", json={**body, "intent_ref": "intent_0002"},
                    headers=alice).status_code == 501
    raw, headers = stripe.signed_event("checkout.session.completed", [ref])
    assert api.post("/v1/payments/stripe/events", content=raw, headers=headers).status_code == 200
