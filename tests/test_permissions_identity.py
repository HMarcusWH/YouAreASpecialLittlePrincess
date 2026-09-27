"""T02 permission ledger and identity lifecycle over in-memory stores."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, SequentialIds
from princess_app.application.identity import IdentityService, InMemoryIdentityStore
from princess_app.application.permissions import InMemoryPermissionStore, PermissionService
from princess_app.domain.permissions import GRANT_SCOPES, SUBJECT_WIDE, Decision, PermissionEvent, Scope, evaluate
from princess_app.ports.base import CallContext, Conflict, Environment, InvalidInput, NotAuthorized, Unauthenticated

ROOT = Path(__file__).resolve().parents[1]
SPECIMEN = Scope("SPECIMEN", "capture_1")
OTHER_SPECIMEN = Scope("SPECIMEN", "capture_2")


def service():
    clock = FakeClock()
    return clock, PermissionService(InMemoryPermissionStore(), clock, SequentialIds())


def record(svc, purpose, scope, decision, subject="writer_1"):
    return svc.record(subject_id=subject, actor_id=subject, purpose_id=purpose, scope=scope, decision=decision,
                      notice_version="notice_v1")


def test_grant_scopes_mirror_the_t03_registry():
    registry = json.loads((ROOT / "contracts" / "consent" / "v1" / "purposes.json").read_text())
    assert {p["purpose_id"]: frozenset(p["grant_scopes"]) for p in registry["purposes"]} == GRANT_SCOPES


def test_grant_withdraw_and_regrant_follow_the_latest_recorded_decision():
    clock, svc = service()
    assert svc.check("writer_1", "service_processing", SPECIMEN).reason == "no_decision"
    record(svc, "service_processing", SPECIMEN, Decision.GRANT)
    first = svc.require("writer_1", "service_processing", SPECIMEN)
    clock.advance(1)
    record(svc, "service_processing", SPECIMEN, Decision.WITHDRAW)
    assert svc.check("writer_1", "service_processing", SPECIMEN).reason == "withdraw"
    assert not svc.still_valid("writer_1", "service_processing", SPECIMEN, first)
    clock.advance(1)
    record(svc, "service_processing", SPECIMEN, Decision.GRANT)
    assert svc.check("writer_1", "service_processing", SPECIMEN).allowed


def test_subject_wide_withdrawal_revokes_item_grants_and_item_scope_is_isolated():
    clock, svc = service()
    record(svc, "image_retention", SPECIMEN, Decision.GRANT)
    assert not svc.check("writer_1", "image_retention", OTHER_SPECIMEN).allowed
    clock.advance(1)
    record(svc, "image_retention", SUBJECT_WIDE, Decision.WITHDRAW)
    assert not svc.check("writer_1", "image_retention", SPECIMEN).allowed


def test_withdrawal_during_use_blocks_publication_with_the_epoch():
    clock, svc = service()
    record(svc, "third_party_ai_processing", Scope("REPORT", "report_1"), Decision.GRANT)
    epoch = svc.require("writer_1", "third_party_ai_processing", Scope("REPORT", "report_1"))
    clock.advance(5)
    record(svc, "third_party_ai_processing", SUBJECT_WIDE, Decision.WITHDRAW)
    assert not svc.still_valid("writer_1", "third_party_ai_processing", Scope("REPORT", "report_1"), epoch)
    with pytest.raises(NotAuthorized):
        svc.require("writer_1", "third_party_ai_processing", Scope("REPORT", "report_1"))


def test_sharing_grant_never_authorizes_partner_comparison():
    _, svc = service()
    record(svc, "ordinary_sharing", Scope("SHARE_GRANT", "share_1"), Decision.GRANT)
    assert not svc.check("writer_1", "partner_comparison", Scope("COMPARISON", "share_1")).allowed
    with pytest.raises(InvalidInput):
        record(svc, "ordinary_sharing", Scope("COMPARISON", "cmp_1"), Decision.GRANT)


def test_permissions_are_per_subject():
    _, svc = service()
    record(svc, "service_processing", SPECIMEN, Decision.GRANT, subject="writer_1")
    assert not svc.check("writer_2", "service_processing", SPECIMEN).allowed


@pytest.mark.parametrize("purpose,scope", [
    ("model_training", SUBJECT_WIDE), ("public_example", Scope("SPECIMEN", "c")),
    ("service_processing", SUBJECT_WIDE), ("product_analytics", Scope("SPECIMEN", "c")),
])
def test_ungrantable_scopes_are_rejected(purpose, scope):
    _, svc = service()
    with pytest.raises(InvalidInput):
        record(svc, purpose, scope, Decision.GRANT)


def test_future_effective_grant_and_no_backdating():
    clock, svc = service()
    svc.record(subject_id="w", actor_id="w", purpose_id="product_analytics", scope=SUBJECT_WIDE,
               decision=Decision.GRANT, notice_version="n1", effective_at=clock.now() + timedelta(hours=1))
    assert not svc.check("w", "product_analytics", SUBJECT_WIDE).allowed
    clock.advance(3601)
    assert svc.check("w", "product_analytics", SUBJECT_WIDE).allowed
    with pytest.raises(InvalidInput):
        svc.record(subject_id="w", actor_id="w", purpose_id="product_analytics", scope=SUBJECT_WIDE,
                   decision=Decision.GRANT, notice_version="n1", effective_at=clock.now() - timedelta(seconds=1))


def test_stale_purpose_version_does_not_authorize(monkeypatch):
    clock, svc = service()
    record(svc, "service_processing", SPECIMEN, Decision.GRANT)
    from princess_contracts import generated as g
    versions = {**g.PURPOSE_AUTHORITY["versions"], "service_processing": [1, 2]}
    monkeypatch.setitem(g.PURPOSE_AUTHORITY, "versions", versions)
    assert svc.check("writer_1", "service_processing", SPECIMEN).reason == "stale_purpose_version"


def test_replayed_event_ids_do_not_change_the_outcome():
    clock, svc = service()
    grant = record(svc, "service_processing", SPECIMEN, Decision.GRANT)
    clock.advance(1)
    withdraw = record(svc, "service_processing", SPECIMEN, Decision.WITHDRAW)
    replayed = [grant, withdraw, replace(grant, sequence=0)]  # an old grant replayed with a stale sequence
    assert not evaluate(replayed, subject_id="writer_1", purpose_id="service_processing", scope=SPECIMEN,
                        at=clock.now()).allowed


def test_unknown_purpose_version_is_rejected():
    clock = FakeClock()
    with pytest.raises(InvalidInput):
        PermissionEvent("e1", "w", "service_processing", 99, SPECIMEN, Decision.GRANT, clock.now(), clock.now(),
                        "w", "n1")


AUD = "princess-api"


def identity():
    clock = FakeClock()
    provider = FakeIdentityProvider(clock=clock)
    store = InMemoryIdentityStore()
    return clock, provider, store, IdentityService(provider, store, clock, SequentialIds(), AUD)


def ctx(clock):
    return CallContext("corr-1", Environment.TEST, clock.now() + timedelta(seconds=30))


def test_first_login_creates_one_principal_and_email_never_links():
    clock, provider, store, svc = identity()
    a = svc.authenticate(provider.issue_token("sub-a", AUD, email="same@example.invalid", email_verified=True),
                         ctx(clock))
    again = svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    b = svc.authenticate(provider.issue_token("sub-b", AUD, email="same@example.invalid", email_verified=True),
                         ctx(clock))
    assert a.principal_id == again.principal_id != b.principal_id


def test_logout_everywhere_rejects_older_but_unexpired_tokens():
    clock, provider, store, svc = identity()
    token = provider.issue_token("sub-a", AUD, ttl_s=3600)
    principal = svc.authenticate(token, ctx(clock))
    clock.advance(10)
    svc.logout_everywhere(principal, ctx(clock))
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(token, ctx(clock))
    assert err.value.code == "session_revoked"
    clock.advance(1)
    assert svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock)).principal_id == principal.principal_id


def test_deleted_account_cannot_authenticate_with_a_valid_token():
    clock, provider, store, svc = identity()
    token = provider.issue_token("sub-a", AUD)
    principal = svc.authenticate(token, ctx(clock))
    svc.delete_account(principal, ctx(clock))
    assert store.outbox == [("account.deletion_requested", principal.principal_id)]
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(token, ctx(clock))
    assert err.value.code == "account_deleted"
    clock.advance(1)
    fresh = svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    assert fresh.principal_id != principal.principal_id and fresh.deleted_at is None
    with pytest.raises(Unauthenticated):
        svc.authenticate(token, ctx(clock))  # the pre-deletion token still cannot reach anything


def test_guest_transfer_is_atomic_single_use_and_needs_both_proofs():
    clock, provider, store, svc = identity()
    guest, token = svc.create_guest()
    store.owned["report_1"] = guest.principal_id
    assert svc.authenticate(token, ctx(clock)).principal_id == guest.principal_id
    account = svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    with pytest.raises(Unauthenticated):
        svc.transfer_guest(guest, token)  # a guest cannot be the receiving account
    assert svc.transfer_guest(account, token) == guest.principal_id
    assert store.owned["report_1"] == account.principal_id
    with pytest.raises(Unauthenticated):
        svc.authenticate(token, ctx(clock))  # old guest capability retired
    with pytest.raises((Conflict, Unauthenticated, Exception)):
        svc.transfer_guest(account, token)


def test_expired_or_forged_guest_capabilities_fail():
    clock, provider, store, svc = identity()
    _, token = svc.create_guest()
    with pytest.raises(Unauthenticated):
        svc.authenticate("guest_forged", ctx(clock))
    clock.advance(31 * 86400)
    with pytest.raises(Unauthenticated):
        svc.authenticate(token, ctx(clock))
