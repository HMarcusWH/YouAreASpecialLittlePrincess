"""R2-C real PostgreSQL owner reads of saved /4 report snapshots.

Requires the disposable, row-level-security-enabled PostgreSQL test database.
Uses synthetic handwriting; never enables a public writer or Premium provider.
"""
from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from princess_api import Services, create_app
from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, SequentialIds
from princess_app.adapters.postgres.access import PostgresReportAccess
from princess_app.adapters.postgres.stores import (
    PostgresIdentityStore, PostgresPermissionStore, PostgresReportStore,
)
from princess_app.application.identity import IdentityService
from princess_app.application.permissions import PermissionService
from princess_app.domain.evidence import build_evidence_bundle
from princess_app.domain.reports import assemble_report
from princess_app.domain.reports.story import CHAPTER_ORDER, story_policy_from_reviewed_reading
from princess_app.ports.base import Environment
from princess_graphology.measurements import IMPLEMENTED_FEATURE_IDS
from princess_contracts import compile_document
from test_persistence import T0, load, reference_for, seed_run, publish_report


def make_api(app_db, *, live_rights=True):
    clock = FakeClock(T0)
    identity = FakeIdentityProvider(audience="princess-api", clock=clock)
    services = Services(
        environment=Environment.TEST, clock=clock,
        identity=IdentityService(identity, PostgresIdentityStore(app_db), clock, SequentialIds()),
        permissions=PermissionService(PostgresPermissionStore(app_db), clock, SequentialIds(),
                                      allow_draft_policy=True),
        report_store_for=lambda principal: PostgresReportStore(app_db, principal),
        report_access=PostgresReportAccess(app_db) if live_rights else None,
        # Deliberately claim commercial/export switches from the API surface,
        # while the /4 projection must still refuse unreleased capabilities.
        kill_switches={"commerce": True, "premium_generation": False, "sharing": True},
        exports=object(), dev_identity=identity,
    )
    return TestClient(create_app(services))


def principal(api, subject):
    issued = api.post("/v1/dev/id-tokens", json={"subject": subject})
    assert issued.status_code == 201
    auth = {"Authorization": f"Bearer {issued.json()['id_token']}"}
    who = api.get("/v1/me", headers=auth)
    assert who.status_code == 200
    return auth, who.json()["principal_id"]


def save_story(app_db, owner, *, run_id="run_story", locale="sv", lines=3, words=3):
    source = seed_run(app_db, owner, run_id=run_id, asset_id=f"asset_{run_id}")
    ref = reference_for(owner, run_id, f"asset_{run_id}")
    ref["versions"]["template"] = "individual-report/4"
    result = copy.deepcopy(load("engine-result.synthetic.json"))
    result["measurements"]["PAGE_LINE_COUNT"]["raw_value"] = lines
    result["measurements"]["PAGE_WORD_COUNT"]["raw_value"] = words
    evidence = build_evidence_bundle(load("evidence-payload.synthetic.json"), ref,
                                     f"evidence_{run_id}")
    assert evidence.ok, evidence.issues
    source.complete_run(owner, run_id, result=result, processed_sha256=ref["processed_sha256"],
                        at=T0, evidence=evidence.value)
    assembled = assemble_report(report_id=f"report_{run_id}", analysis=ref, result=result,
                                created_at=T0, locale=locale, evidence=evidence.value,
                                story_policy=story_policy_from_reviewed_reading())
    assert assembled.ok, assembled.issues
    PostgresReportStore(app_db, owner).append(owner, assembled.value)
    return assembled.value


def retain_capture(app_db, owner, report):
    """Simulate a current, matching synthetic original; no raw image is stored."""
    asset_id = report.data["analysis"]["input_asset_id"]
    sha = report.data["analysis"]["input_sha256"]
    with app_db.session(owner) as conn:
        conn.execute(text("INSERT INTO app.upload (upload_id, owner_id, asset_id, media_type, max_bytes, "
                          "state, created_at, expires_at, completed_at) "
                          "VALUES (:u, :o, :a, 'image/png', 10000, 'COMPLETED', :t, :expiry, :t)"),
                     {"u": f"upload_{asset_id}", "o": owner, "a": asset_id, "t": T0,
                      "expiry": T0 + timedelta(hours=1)})
        conn.execute(text("INSERT INTO app.capture (capture_id, owner_id, upload_id, asset_id, "
                          "media_type, width, height, exif_orientation, sha256, created_at) "
                          "VALUES (:c, :o, :u, :a, 'image/png', 120, 80, 1, :h, :t)"),
                     {"c": f"capture_{asset_id}", "o": owner, "u": f"upload_{asset_id}",
                      "a": asset_id, "h": sha, "t": T0})
    return f"capture_{asset_id}"


def assert_saved_projection(response, original, *, with_image):
    assert response.status_code == 200, response.text
    data = response.json()
    assert compile_document("ReportViewModel", data).ok
    assert data["source_digest"] == original.data["document_digest"]
    assert data["source_revision"] == original.data["revision"] == 1
    assert data["locale"] == original.data["locale"]
    assert len(data["facts"]) == len(IMPLEMENTED_FEATURE_IDS) == 64
    assert set(CHAPTER_ORDER) <= {s["section_id"] for s in data["sections"]}
    assert data["authorized_asset_ids"] == ([original.data["analysis"]["input_asset_id"]]
                                            if with_image else [])
    assert next(a for a in data["actions"] if a["kind"] == "EXPORT")["enabled"] is False
    if not with_image:
        assert "notice.source_image_unavailable" in [n["localization_key"] for n in data["notices"]]
        assert not any(a["kind"] == "PURCHASE" for a in data["actions"])
    return data


def test_saved_story_owner_read_and_source_revocation_are_independent(app_db):
    api = make_api(app_db)
    alice, owner = principal(api, "story_alice")
    bob, _ = principal(api, "story_bob")
    report = save_story(app_db, owner)
    rid = report.data["report_id"]

    # Source exists as an asset row but has no verified retained capture yet.
    missing = assert_saved_projection(api.get(f"/v1/reports/{rid}", headers=alice), report,
                                      with_image=False)
    assert api.get(f"/v1/reports/{rid}/source-image", headers=alice).status_code == 404
    for path in (f"/v1/reports/{rid}", f"/v1/reports/{rid}/evidence",
                 f"/v1/reports/{rid}/source-image"):
        assert api.get(path, headers=bob).status_code == 404
    evidence = api.get(f"/v1/reports/{rid}/evidence", headers=alice)
    assert evidence.status_code == 200 and compile_document("EvidenceBundle", evidence.json()).ok
    authentic_region_ids = {r["region_id"] for r in evidence.json()["regions"]}
    assert all(set(f["source_region_ids"]) <= authentic_region_ids for f in missing["facts"])
    authentic_fact_ids = {f["fact_id"] for f in missing["facts"]}
    assert all(set(s["fact_ids"]) <= authentic_fact_ids for s in missing["sections"])
    assert any(row["report_id"] == rid for row in api.get("/v1/reports", headers=alice).json()["items"])

    captured = retain_capture(app_db, owner, report)
    visible = assert_saved_projection(api.get(f"/v1/reports/{rid}?projection=FREE", headers=alice),
                                      report, with_image=True)
    assert next(a for a in visible["actions"] if a["kind"] == "PURCHASE")["enabled"] is False
    assert visible["facts"] == missing["facts"] and visible["sections"] == missing["sections"]
    with app_db.session(owner) as conn:
        stored_digest_before = conn.execute(text(
            "SELECT digest FROM app.report_revision WHERE report_id = :r AND revision = 1"),
            {"r": rid}).scalar_one()
        # Source-link tampering must not make an unrelated retained image available.
        conn.execute(text("UPDATE app.capture SET sha256 = :h WHERE capture_id = :c"),
                     {"h": "f" * 64, "c": captured})
    assert_saved_projection(api.get(f"/v1/reports/{rid}", headers=alice), report, with_image=False)
    with app_db.session(owner) as conn:
        conn.execute(text("UPDATE app.capture SET sha256 = :h WHERE capture_id = :c"),
                     {"h": report.data["analysis"]["input_sha256"], "c": captured})
        conn.execute(text("UPDATE app.capture SET deleted_at = :t WHERE capture_id = :c"),
                     {"t": T0, "c": captured})
    revoked = assert_saved_projection(api.get(f"/v1/reports/{rid}", headers=alice), report,
                                      with_image=False)
    assert revoked["facts"] == visible["facts"] and revoked["sections"] == visible["sections"]
    assert api.get(f"/v1/reports/{rid}/evidence", headers=alice).status_code == 200
    with app_db.session(owner) as conn:
        assert conn.execute(text(
            "SELECT digest FROM app.report_revision WHERE report_id = :r AND revision = 1"),
            {"r": rid}).scalar_one() == stored_digest_before

    # A deployment rollback must still read the saved report but never infer
    # a right to retained image bytes when its live resolver is unavailable.
    previous_runtime = make_api(app_db, live_rights=False)
    old_auth, _ = principal(previous_runtime, "story_alice")
    after_rollback = assert_saved_projection(previous_runtime.get(f"/v1/reports/{rid}", headers=old_auth),
                                             report, with_image=False)
    assert after_rollback["source_digest"] == visible["source_digest"]


@pytest.mark.parametrize("locale,lines,words", [
    ("en", 3, 0), ("sv", 0, 0),
])
def test_saved_story_unsuitable_specimen_never_offers_purchase(app_db, locale, lines, words):
    api = make_api(app_db)
    auth, owner = principal(api, f"short_{locale}")
    report = save_story(app_db, owner, run_id=f"run_short_{locale}", locale=locale,
                        lines=lines, words=words)
    retain_capture(app_db, owner, report)
    projected = assert_saved_projection(api.get(f"/v1/reports/{report.data['report_id']}", headers=auth),
                                        report, with_image=True)
    assert not any(a["kind"] == "PURCHASE" for a in projected["actions"])
    # No commerce provider is configured; a read cannot attempt a credit grant.
    assert api.get(f"/v1/reports/{report.data['report_id']}/premium", headers=auth).status_code == 403


def test_legacy_source_authorization_projection_unchanged(app_db):
    api = make_api(app_db)
    auth, owner = principal(api, "legacy_previous")
    legacy = publish_report(app_db, owner, "run_legacy")
    response = api.get(f"/v1/reports/{legacy.data['report_id']}", headers=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["authorized_asset_ids"] == [legacy.data["analysis"]["input_asset_id"]]
    assert next(a for a in data["actions"] if a["kind"] == "EXPORT")["enabled"] is True
    assert next(a for a in data["actions"] if a["kind"] == "PURCHASE")["enabled"] is True
