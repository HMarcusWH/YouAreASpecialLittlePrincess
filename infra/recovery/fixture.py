#!/usr/bin/env python3
"""Synthetic application fixture for the T24 real PostgreSQL restore drill.

All lifecycle mutations go through the ordinary API/application code. SQL is
used only for bounded observation of the synthetic rows being rehearsed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import text

from princess_api.app import create_app
from princess_api.compose import ROOT, UuidIds, compose
from princess_app.adapters.localfs import LocalObjectStore
from princess_app.adapters.localfs.tombstones import JsonlTombstoneLog
from princess_app.adapters.postgres.intake import PostgresIntakeRepository
from princess_app.adapters.postgres.outbox import PostgresErasureOutbox
from princess_app.adapters.postgres.stores import Database, PostgresIdentityStore, PostgresPermissionStore, make_engine
from princess_app.application.erasure import ErasureWorker
from princess_app.application.intake import propagate_withdrawal
from princess_app.application.permissions import PermissionService
from princess_app.config import load_runtime_config
from princess_app.domain.permissions import Scope
from princess_app.ports.base import CallContext, Environment, SystemClock
from princess_graphology import __version__ as ENGINE_VERSION

NOTICE = "notice.consent-choices:1"
PURPOSE = "third_party_ai_processing"
SCOPE = Scope("SUBJECT_WIDE")
SUBJECT_CAPTURE = "recovery-capture-owner"
SUBJECT_ACCOUNT = "recovery-deleted-account"
SUBJECT_PERMISSION = "recovery-permission-owner"


def emit(**values) -> None:
    print(json.dumps(values, sort_keys=True))


def handwriting_png() -> bytes:
    image = np.full((360, 900), 245, np.uint8)
    for i, line in enumerate(("synthetic recovery specimen", "never production data", "restore rehearsal")):
        cv2.putText(image, line, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
                    1.5, 25, 3, cv2.LINE_AA)
    matrix = cv2.getRotationMatrix2D((450, 180), 3.0, 1.0)
    image = cv2.warpAffine(image, matrix, (900, 360), borderValue=245)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise SystemExit("synthetic_png_encode_failed")
    return encoded.tobytes()


def api_services():
    config = load_runtime_config(os.environ, ROOT)
    if config.component != "api" or config.environment is not Environment.TEST:
        raise SystemExit("recovery fixture requires test api component")
    return config, compose(config)


def login(client: TestClient, subject: str) -> tuple[str, dict[str, str]]:
    token_response = client.post("/v1/dev/id-tokens", json={"subject": subject})
    if token_response.status_code != 201:
        raise SystemExit("synthetic_login_token_failed")
    token = token_response.json()["id_token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/v1/me", headers=headers)
    if response.status_code != 200:
        raise SystemExit("synthetic_login_failed")
    return response.json()["principal_id"], headers


def load_state(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"capture_owner_id", "capture_id", "asset_id", "deleted_account_id", "permission_owner_id"}
    if set(data) != required:
        raise SystemExit("recovery_state_shape_invalid")
    return data


def seed(path: Path) -> None:
    config, services = api_services()
    client = TestClient(create_app(services))
    capture_owner, capture_auth = login(client, SUBJECT_CAPTURE)
    deleted_account, _ = login(client, SUBJECT_ACCOUNT)
    permission_owner, permission_auth = login(client, SUBJECT_PERMISSION)

    data = handwriting_png()
    ticket_response = client.post("/v1/uploads", json={"media_type": "image/png"}, headers=capture_auth)
    if ticket_response.status_code != 201:
        raise SystemExit("synthetic_upload_reservation_failed")
    ticket = ticket_response.json()
    location = urlsplit(ticket["url"])
    upload_response = client.put(
        location.path + ("?" + location.query if location.query else ""),
        content=data,
        headers={"content-type": "image/png"},
    )
    if upload_response.status_code != 204:
        raise SystemExit("synthetic_upload_failed")
    complete = client.post(
        f"/v1/uploads/{ticket['upload_id']}/complete",
        json={"sha256": hashlib.sha256(data).hexdigest()},
        headers=capture_auth,
    )
    if complete.status_code != 200:
        raise SystemExit("synthetic_upload_completion_failed")
    capture_id = complete.json()["capture_id"]

    permission = client.post(
        "/v1/me/permissions",
        json={
            "purpose_id": PURPOSE,
            "scope_kind": SCOPE.kind,
            "scope_ref": None,
            "decision": "GRANT",
            "notice_version": NOTICE,
            "request_id": "recovery-grant-0001",
        },
        headers=permission_auth,
    )
    if permission.status_code != 201:
        raise SystemExit("synthetic_permission_grant_failed")

    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    with db.session(capture_owner) as conn:
        asset_id = conn.execute(
            text("SELECT asset_id FROM app.capture WHERE capture_id = :c"),
            {"c": capture_id},
        ).scalar_one()

    state = {
        "capture_owner_id": capture_owner,
        "capture_id": capture_id,
        "asset_id": asset_id,
        "deleted_account_id": deleted_account,
        "permission_owner_id": permission_owner,
    }
    path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    emit(command="seed", synthetic_principals=3, captures=1, permission_grants=1)


def mutate(path: Path) -> None:
    _, services = api_services()
    client = TestClient(create_app(services))
    state = load_state(path)

    capture_owner, capture_auth = login(client, SUBJECT_CAPTURE)
    deleted_account, account_auth = login(client, SUBJECT_ACCOUNT)
    permission_owner, permission_auth = login(client, SUBJECT_PERMISSION)
    if (capture_owner, deleted_account, permission_owner) != (
        state["capture_owner_id"], state["deleted_account_id"], state["permission_owner_id"]
    ):
        raise SystemExit("identity_binding_changed_before_mutation")

    capture = client.delete(f"/v1/captures/{state['capture_id']}", headers=capture_auth)
    account = client.delete("/v1/me", headers=account_auth)
    permission = client.post(
        "/v1/me/permissions",
        json={
            "purpose_id": PURPOSE,
            "scope_kind": SCOPE.kind,
            "scope_ref": None,
            "decision": "WITHDRAW",
            "notice_version": NOTICE,
            "request_id": "recovery-withdraw-0001",
        },
        headers=permission_auth,
    )
    if capture.status_code != 202 or account.status_code != 202 or permission.status_code != 201:
        raise SystemExit("post_backup_mutation_failed")
    emit(command="mutate", capture_delete=202, account_delete=202, permission_withdraw=201)


def erasure() -> None:
    config = load_runtime_config(os.environ, ROOT)
    if config.component != "analysis_worker" or config.environment is not Environment.TEST:
        raise SystemExit("recovery erasure requires test analysis_worker component")
    clock = SystemClock()
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    store = LocalObjectStore(
        Path(os.environ["PRINCESS_LOCAL_STORAGE_DIR"]),
        signing_key=config.secret("PRINCESS_STORAGE_READ_KEY").encode(),
        clock=clock,
        environment=config.environment,
    )

    def context() -> CallContext:
        return CallContext(uuid.uuid4().hex, config.environment, clock.now() + timedelta(seconds=60))

    permissions = PermissionService(PostgresPermissionStore(db), clock, UuidIds(), allow_draft_policy=True)
    repo = PostgresIntakeRepository(db, engine_version=ENGINE_VERSION)
    worker = ErasureWorker(
        outbox=PostgresErasureOutbox(db),
        store=store,
        permissions=permissions,
        clock=clock,
        context=context,
        propagate=lambda owner, purpose, scope, decision: propagate_withdrawal(
            repo, permissions, owner, purpose, scope, decision, clock.now()
        ),
        tombstones=JsonlTombstoneLog(Path(os.environ["PRINCESS_TOMBSTONE_DIR"])),
    )
    counts: Counter[str] = Counter()
    for _ in range(50):
        rows = worker.run_once()
        if not rows:
            break
        counts.update(row.action for row in rows)
    else:
        raise SystemExit("erasure_did_not_quiesce")
    emit(command="erase", outcomes=dict(sorted(counts.items())))


def observed(path: Path) -> dict[str, bool]:
    config, services = api_services()
    state = load_state(path)
    db = Database(make_engine(config.secret("PRINCESS_DATABASE_URL")))
    with db.session(state["capture_owner_id"]) as conn:
        capture_deleted = bool(conn.execute(
            text("SELECT deleted_at IS NOT NULL FROM app.capture WHERE capture_id = :c"),
            {"c": state["capture_id"]},
        ).scalar_one())
    principal = PostgresIdentityStore(db).principal(state["deleted_account_id"])
    if principal is None:
        raise SystemExit("synthetic_principal_missing")
    permission = PermissionService(PostgresPermissionStore(db), services.clock, UuidIds(), allow_draft_policy=True)
    allowed = permission.check(state["permission_owner_id"], PURPOSE, SCOPE).allowed
    object_deleted = services.dev_store.verify_deletion(
        state["asset_id"],
        CallContext("recovery-observe", Environment.TEST, services.clock.now() + timedelta(seconds=30)),
    )
    contents = JsonlTombstoneLog(Path(os.environ["PRINCESS_TOMBSTONE_DIR"])).read()
    return {
        "capture_deleted": capture_deleted,
        "account_deleted": principal.deleted_at is not None,
        "permission_allowed": allowed,
        "object_deleted": object_deleted,
        "tombstones_readable": contents.unreadable == 0 and len(contents.tombstones) >= 3,
    }


def assert_state(path: Path, mode: str) -> None:
    values = observed(path)
    if mode in {"current", "reconciled"}:
        expected = {
            "capture_deleted": True,
            "account_deleted": True,
            "permission_allowed": False,
            "object_deleted": True,
            "tombstones_readable": True,
        }
    else:
        expected = {
            "capture_deleted": False,
            "account_deleted": False,
            "permission_allowed": True,
            # Object storage was not restored with PostgreSQL.
            "object_deleted": True,
            "tombstones_readable": True,
        }
    if values != expected:
        raise SystemExit(f"recovery_assertion_failed:{mode}")
    if mode == "resurrected":
        emit(
            command="assert-resurrected",
            capture=True,
            account=True,
            permission=True,
            object_erasure_preserved=True,
        )
    else:
        emit(command=f"assert-{mode}", reconciled=True, object_erasure_verified=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("seed", "mutate", "erase", "assert-current", "assert-resurrected",
                                             "assert-reconciled"))
    parser.add_argument("state", nargs="?", default="/recovery/state.json")
    args = parser.parse_args()
    path = Path(args.state)
    if args.command == "seed":
        seed(path)
    elif args.command == "mutate":
        mutate(path)
    elif args.command == "erase":
        erasure()
    else:
        assert_state(path, args.command.removeprefix("assert-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
