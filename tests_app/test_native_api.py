"""Native-facing API contracts (mobile completion plan S01) over the composed local stack.

Pending-work discovery, report-scoped deletion, authorized source-image
delivery, consent notice delivery and same-owner comparisons. Every route is
owner-scoped and none of them calls a model.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from princess_api import create_app
from princess_api.compose import compose
from princess_app.adapters.imaging import decode_image
from princess_app.adapters.localfs import LocalObjectStore
from princess_app.adapters.postgres.intake import PostgresJobQueue
from princess_app.application.analysis_worker import AnalysisWorker
from princess_app.application.notices import NoticeCatalog, parse_registry
from princess_app.config import load_runtime_config
from princess_app.ports.base import CallContext, PermanentFailure, SystemClock
from princess_contracts import compile_document
from princess_graphology import GraphologyEngine, __version__
from test_intake import handwriting_png

ROOT = Path(__file__).resolve().parents[1]
NOTICE = "notice.consent-choices:1"


class Stack:
    def __init__(self, app_url, worker_db, tmp_path, monkeypatch):
        monkeypatch.setenv("PRINCESS_LOCAL_STORAGE_DIR", str(tmp_path))
        env = {"PRINCESS_ENV": "test", "PRINCESS_COMPONENT": "api", "PRINCESS_DATABASE_URL": app_url,
               "PRINCESS_SESSION_SECRET": "session-secret-0123456789",
               "PRINCESS_IDENTITY_AUDIENCE": "princess-test",
               "PRINCESS_STORAGE_SIGNING_KEY": "signing-key-0123456789"}
        self.services = compose(load_runtime_config(env, ROOT))
        self.api = TestClient(create_app(self.services))
        clock = SystemClock()
        store = LocalObjectStore(tmp_path, signing_key=b"worker-read-key-0123456789", clock=clock,
                                 environment=self.services.environment)
        self.worker = AnalysisWorker(
            queue=PostgresJobQueue(worker_db, allow_draft_policy=True), store=store, decode=decode_image,
            engine=GraphologyEngine(), clock=clock,
            context=lambda: CallContext("w", self.services.environment, clock.now() + timedelta(seconds=60)),
            worker_id="native-worker", engine_version=__version__)
        self.tmp_path = tmp_path

    def login(self, subject: str) -> dict[str, str]:
        token = self.api.post("/v1/dev/id-tokens", json={"subject": subject}).json()["id_token"]
        return {"Authorization": f"Bearer {token}"}

    def capture(self, auth, angle=3.0) -> dict:
        data = handwriting_png(angle=angle)
        ticket = self.api.post("/v1/uploads", json={"media_type": "image/png"}, headers=auth).json()
        path = urlsplit(ticket["url"])
        put = self.api.put(path.path + "?" + path.query, content=data, headers={"content-type": "image/png"})
        assert put.status_code == 204
        capture = self.api.post(f"/v1/uploads/{ticket['upload_id']}/complete",
                                json={"sha256": hashlib.sha256(data).hexdigest()}, headers=auth).json()
        capture["bytes"] = data
        return capture

    def start(self, auth, capture) -> str:
        grant = {"purpose_id": "service_processing", "scope_kind": "SPECIMEN", "scope_ref": capture["capture_id"],
                 "decision": "GRANT", "notice_version": NOTICE, "request_id": f"native-{capture['capture_id']}"}
        assert self.api.post("/v1/me/permissions", json=grant, headers=auth).status_code == 201
        started = self.api.post("/v1/analyses", json={"capture_id": capture["capture_id"]}, headers=auth)
        assert started.status_code == 202
        return started.json()["run_id"]

    def report(self, auth, angle=3.0) -> tuple[dict, str, str]:
        capture = self.capture(auth, angle)
        run_id = self.start(auth, capture)
        assert self.worker.run_once().outcome == "SUCCEEDED"
        status = self.api.get(f"/v1/analyses/{run_id}", headers=auth).json()
        assert status["state"] == "SUCCEEDED"
        return capture, run_id, status["report_id"]


@pytest.fixture
def stack(app_url, worker_db, tmp_path, monkeypatch):
    return Stack(app_url, worker_db, tmp_path, monkeypatch)


def test_consent_notices_serve_the_exact_registry_text_and_draft_status(stack):
    api = stack.api
    english = api.get("/v1/consent-notices").json()["notices"]
    assert [n["notice_version"] for n in english] == [NOTICE]
    notice = english[0]
    # Draft notices only count with synthetic data (test environment).
    assert notice["status"] == "DRAFT" and notice["accepted_for_use"] is True and notice["locale"] == "en"
    service = next(p for p in notice["purposes"] if p["purpose_id"] == "service_processing")
    assert service["label"] == "Analyse this page" and service["purpose_version"] == 1
    swedish = api.get("/v1/consent-notices?locale=sv-SE").json()["notices"][0]
    assert swedish["locale"] == "sv"
    assert next(p for p in swedish["purposes"] if p["purpose_id"] == "service_processing")["label"].startswith(
        "Analysera")
    assert api.get("/v1/consent-notices?locale=../../etc").status_code == 422

    production_like = NoticeCatalog.from_registry(ROOT / "contracts" / "consent" / "v1" / "notices.json",
                                                  allow_draft_policy=False)
    assert production_like.describe("en")[0]["accepted_for_use"] is False


def test_notice_registry_that_disagrees_with_domain_coverage_is_refused():
    registry = {"contract_version": "notice-registry/v1", "notices": [{
        "notice_id": "notice.consent-choices", "version": 1, "status": "DRAFT",
        "purposes": [{"purpose_id": "service_processing", "purpose_version": 1}], "copy": []}]}
    with pytest.raises(PermanentFailure) as err:
        parse_registry(registry)
    assert err.value.code == "notice_registry_mismatch"


def test_recent_runs_support_recovery_and_stay_owner_scoped(stack):
    api = stack.api
    alice, bob = stack.login("alice"), stack.login("bob")
    assert api.get("/v1/analyses", headers=alice).json() == {"items": []}
    _, done_run, report_id = stack.report(alice)
    pending_capture = stack.capture(alice, angle=1.0)
    pending_run = stack.start(alice, pending_capture)

    items = api.get("/v1/analyses", headers=alice).json()["items"]
    assert [item["run_id"] for item in items] == [pending_run, done_run]
    assert items[0]["state"] == "QUEUED" and items[0]["report_id"] is None
    assert items[1] == {"run_id": done_run, "state": "SUCCEEDED", "report_id": report_id, "error_code": None,
                        "created_at": items[1]["created_at"]}
    assert api.get("/v1/analyses?limit=1", headers=alice).json()["items"][0]["run_id"] == pending_run
    assert api.get("/v1/analyses?limit=0", headers=alice).status_code == 422
    assert api.get("/v1/analyses?limit=51", headers=alice).status_code == 422
    assert api.get("/v1/analyses", headers=bob).json() == {"items": []}
    assert api.get("/v1/analyses").status_code == 401

    # A deleted specimen takes its runs out of discovery, like run status.
    assert api.delete(f"/v1/captures/{pending_capture['capture_id']}", headers=alice).status_code == 202
    assert [item["run_id"] for item in api.get("/v1/analyses", headers=alice).json()["items"]] == [done_run]


def test_report_deletion_resolves_the_specimen_server_side(stack):
    api = stack.api
    alice, bob = stack.login("alice"), stack.login("bob")
    capture, run_id, report_id = stack.report(alice)
    assert api.delete(f"/v1/reports/{report_id}", headers=bob).status_code == 404
    assert api.get(f"/v1/reports/{report_id}", headers=alice).status_code == 200

    deleted = api.delete(f"/v1/reports/{report_id}", headers=alice)
    assert deleted.status_code == 202 and deleted.json() == {"state": "DELETION_REQUESTED"}
    assert api.get(f"/v1/reports/{report_id}", headers=alice).status_code == 404
    assert api.get(f"/v1/analyses/{run_id}", headers=alice).status_code == 404
    assert api.get("/v1/reports", headers=alice).json()["items"] == []
    assert api.delete(f"/v1/reports/{report_id}", headers=alice).status_code == 404  # not a second deletion
    tombstones = (stack.tmp_path / "tombstones" / "tombstones.jsonl").read_text()
    assert capture["capture_id"] in tombstones and "CAPTURE_DELETED" in tombstones


def test_source_image_is_served_only_through_a_live_owner_projection(stack, app_db):
    api = stack.api
    alice, bob = stack.login("alice"), stack.login("bob")
    capture, _, report_id = stack.report(alice)
    owner = api.get(f"/v1/reports/{report_id}", headers=alice).json()
    assert owner["authorized_asset_ids"]

    image = api.get(f"/v1/reports/{report_id}/source-image", headers=alice)
    assert image.status_code == 200 and image.content == capture["bytes"]
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "private, no-store"
    assert api.get(f"/v1/reports/{report_id}/source-image", headers=bob).status_code == 404
    assert api.get(f"/v1/reports/{report_id}/source-image").status_code == 401

    # Once retention erased the original, the projection omits it and nothing is served.
    alice_id = api.get("/v1/me", headers=alice).json()["principal_id"]
    with app_db.session(alice_id) as conn:
        conn.execute(text("UPDATE app.asset SET deleted_at = now() WHERE asset_id IN "
                          "(SELECT asset_id FROM app.capture WHERE capture_id = :c)"), {"c": capture["capture_id"]})
    assert api.get(f"/v1/reports/{report_id}", headers=alice).json()["authorized_asset_ids"] == []
    gone = api.get(f"/v1/reports/{report_id}/source-image", headers=alice)
    assert gone.status_code == 404 and gone.json() == {"error": "source_image_not_available"}


def test_same_owner_comparisons_use_saved_reports_and_refuse_foreign_inputs(stack):
    api = stack.api
    alice, bob = stack.login("alice"), stack.login("bob")
    _, _, first = stack.report(alice, angle=3.0)
    _, _, second = stack.report(alice, angle=-4.0)
    _, _, foreign = stack.report(bob, angle=2.0)

    pair = api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, second]}, headers=alice)
    assert pair.status_code == 200
    compiled = compile_document("Comparison", pair.json())
    assert compiled.ok, compiled.issues
    body = pair.json()
    assert body["kind"] == "PAIR" and body["input_report_ids"] == [first, second]
    assert [row["report_id"] for row in body["inputs"]] == [first, second]
    assert body["coverage"]["common_n"] == len(body["common_feature_ids"]) > 0
    reversed_pair = api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [second, first]},
                             headers=alice).json()
    by_feature = {d["feature_id"]: d for d in body["differences"]}
    for row in reversed_pair["differences"]:
        assert row["signed_delta"] == -by_feature[row["feature_id"]]["signed_delta"]

    history = api.post("/v1/comparisons", json={"kind": "HISTORY", "report_ids": [second, first]}, headers=alice)
    assert history.status_code == 200 and history.json()["ordering_basis"] == "REPORT_CREATED_AT"

    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, foreign]},
                    headers=alice).status_code == 404
    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, first]},
                    headers=alice).status_code == 422
    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first]},
                    headers=alice).status_code == 422
    assert api.post("/v1/comparisons", json={"kind": "SIMILARITY", "report_ids": [first, second]},
                    headers=alice).status_code == 422
    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, second]}).status_code == 401

    # A deleted input cannot be reopened through comparison.
    assert api.delete(f"/v1/reports/{second}", headers=alice).status_code == 202
    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, second]},
                    headers=alice).status_code == 404

    stack.services.comparisons_enabled = False
    assert api.post("/v1/comparisons", json={"kind": "PAIR", "report_ids": [first, second]},
                    headers=alice).status_code == 501
