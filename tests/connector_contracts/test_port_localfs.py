"""Filesystem ObjectStore: same contract cases as the fake, persisted on disk."""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from port_harness import ctx

from princess_app.adapters.fakes import FakeClock
from princess_app.adapters.localfs import LocalObjectStore
from princess_app.ports import storage
from princess_app.ports.base import Conflict, Environment, InvalidInput, NotFound, Unauthenticated, Unsupported

POLICY = storage.UploadPolicy(frozenset({"image/png"}), max_bytes=1024, expires_in_s=300)
KEY = b"local-signing-key-0123456789"


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def local(tmp_path):
    clock = FakeClock()
    return clock, LocalObjectStore(tmp_path, signing_key=KEY, clock=clock, environment=Environment.TEST)


def put(store, ticket, data, sig=None):
    signature = sig if sig is not None else parse_qs(urlsplit(ticket.url).query)["sig"][0]
    store.accept_signed_put(ticket.upload_id, signature, data, "image/png")


def test_signed_put_promote_read_and_cross_instance_persistence(local, tmp_path):
    clock, store = local
    ticket = store.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    put(store, ticket, b"bytes")
    stored = store.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))
    other = LocalObjectStore(tmp_path, signing_key=KEY, clock=clock, environment=Environment.TEST)
    assert other.read_object(stored, ctx(clock)) == b"bytes"  # e.g. the worker process
    assert store.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock)) == stored


def test_bad_signature_expiry_size_and_overwrite(local):
    clock, store = local
    ticket = store.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    with pytest.raises(Unauthenticated):
        put(store, ticket, b"bytes", sig="0" * 64)
    with pytest.raises(InvalidInput):
        put(store, ticket, b"x" * 2048)
    put(store, ticket, b"original")
    put(store, ticket, b"swapped!")
    with pytest.raises(Conflict):
        store.promote_verified_input(ticket.upload_id, sha(b"original"), ctx(clock))
    clock.advance(301)
    with pytest.raises(Unauthenticated):
        put(store, ticket, b"late")
    with pytest.raises(Conflict):
        store.promote_verified_input(ticket.upload_id, sha(b"swapped!"), ctx(clock))


def test_delete_revokes_slots_and_versions(local):
    clock, store = local
    ticket = store.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    put(store, ticket, b"bytes")
    stored = store.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))
    store.delete_asset_versions("asset_1", ctx(clock))
    assert store.verify_deletion("asset_1", ctx(clock))
    with pytest.raises(NotFound):
        store.read_object(stored, ctx(clock))
    with pytest.raises(NotFound):
        put(store, ticket, b"again")


def test_filesystem_store_never_composes_into_production(tmp_path):
    with pytest.raises(InvalidInput):
        LocalObjectStore(tmp_path, signing_key=KEY, clock=FakeClock(), environment=Environment.PRODUCTION)


def test_download_tickets_are_not_advertised_without_a_route(local):
    clock, store = local
    assert storage.DOWNLOAD_TICKETS not in store.profile.capabilities
    stored = store.write_derivative("export_1", None, b"%PDF-", "application/pdf", ctx(clock))
    with pytest.raises(Unsupported):
        store.issue_download_ticket(stored, 60, ctx(clock))
