"""HTTP boundary over PostgreSQL stores with fake identity (T02)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from princess_api import Services, create_app
from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, SequentialIds
from princess_app.adapters.postgres.stores import (
    PostgresIdentityStore,
    PostgresPermissionStore,
    PostgresReportStore,
)
from princess_app.application.identity import IdentityService
from princess_app.application.permissions import PermissionService
from princess_app.ports.base import Environment
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
        permissions=PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds()),
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
    assert api.get(f"/v1/reports/{rid}?projection=PREMIUM", headers=alice).status_code == 422


def test_permission_lifecycle_returns_contract_grant_snapshots(client):
    api, clock = client
    alice = login(api, "alice")
    body = {"purpose_id": "third_party_ai_processing", "scope_kind": "REPORT", "scope_ref": "report_1",
            "decision": "GRANT", "notice_version": "notice_2026_09"}
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
        permissions=PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds()),
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
