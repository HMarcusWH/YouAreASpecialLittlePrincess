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
from princess_app.domain.permissions import (
    APPROVED_NOTICES,
    GRANT_SCOPES,
    NOTICE_COVERAGE,
    SUBJECT_WIDE,
    Decision,
    PermissionEvent,
    Scope,
    evaluate,
)
from princess_app.ports.base import CallContext, Conflict, Environment, InvalidInput, NotAuthorized, Unauthenticated
from princess_app.ports.identity import VerifiedIdentity

ROOT = Path(__file__).resolve().parents[1]
SPECIMEN = Scope("SPECIMEN", "capture_1")
OTHER_SPECIMEN = Scope("SPECIMEN", "capture_2")
NOTICE = "notice.consent-choices:1"


def service():
    clock = FakeClock()
    return clock, PermissionService(InMemoryPermissionStore(), clock, SequentialIds(), allow_draft_policy=True)


def record(svc, purpose, scope, decision, subject="writer_1"):
    return svc.record(subject_id=subject, actor_id=subject, purpose_id=purpose, scope=scope, decision=decision,
                      notice_version=NOTICE)


def test_grant_scopes_mirror_the_t03_registry():
    registry = json.loads((ROOT / "contracts" / "consent" / "v1" / "purposes.json").read_text())
    assert {p["purpose_id"]: frozenset(p["grant_scopes"]) for p in registry["purposes"]} == GRANT_SCOPES


def test_notice_coverage_mirrors_the_t03_registry():
    registry = json.loads((ROOT / "contracts" / "consent" / "v1" / "notices.json").read_text())
    purposes = json.loads((ROOT / "contracts" / "consent" / "v1" / "purposes.json").read_text())
    assert {f"{n['notice_id']}:{n['version']}": frozenset((p["purpose_id"], p["purpose_version"]) for p in n["purposes"])
            for n in registry["notices"]} == NOTICE_COVERAGE
    approved_purposes = {(p["purpose_id"], p["purpose_version"]) for p in purposes["purposes"]
                         if p["status"] == "APPROVED"}
    approved = {f"{n['notice_id']}:{n['version']}" for n in registry["notices"]
                if n["status"] == "APPROVED" and NOTICE_COVERAGE[f"{n['notice_id']}:{n['version']}"] <= approved_purposes}
    assert approved == APPROVED_NOTICES


def test_grants_under_draft_policy_or_foreign_notices_fail_closed():
    clock = FakeClock()
    store = InMemoryPermissionStore()
    production_like = PermissionService(store, clock, SequentialIds())
    production_like.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
                           decision=Decision.GRANT, notice_version=NOTICE)
    assert production_like.check("w", "service_processing", SPECIMEN).reason == "policy_not_approved"
    for notice in ("notice.pilot-collection:1", "notice_2026_09", "notice.consent-choices:2"):
        with pytest.raises(InvalidInput):
            production_like.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
                                   decision=Decision.GRANT, notice_version=notice)
    # Withdrawal is never blocked by notice bookkeeping.
    production_like.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SUBJECT_WIDE,
                           decision=Decision.WITHDRAW, notice_version="settings_screen")
    # A replayed grant carrying an uncovered notice never authorizes.
    forged = PermissionEvent("e9", "w2", "service_processing", 1, SPECIMEN, Decision.GRANT, clock.now(),
                             clock.now(), "w2", "notice.pilot-collection:1")
    assert evaluate([forged], subject_id="w2", purpose_id="service_processing", scope=SPECIMEN, at=clock.now(),
                    allow_draft_policy=True).reason == "notice_invalid"


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
               decision=Decision.GRANT, notice_version=NOTICE, effective_at=clock.now() + timedelta(hours=1))
    assert not svc.check("w", "product_analytics", SUBJECT_WIDE).allowed
    clock.advance(3601)
    assert svc.check("w", "product_analytics", SUBJECT_WIDE).allowed
    with pytest.raises(InvalidInput):
        svc.record(subject_id="w", actor_id="w", purpose_id="product_analytics", scope=SUBJECT_WIDE,
                   decision=Decision.GRANT, notice_version=NOTICE, effective_at=clock.now() - timedelta(seconds=1))


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


def test_logout_everywhere_requires_real_reauthentication_freshness():
    clock, provider, store, svc = identity()
    token = provider.issue_token("sub-a", AUD, ttl_s=3600)
    principal = svc.authenticate(token, ctx(clock))
    clock.advance(10)
    svc.logout_everywhere(principal, ctx(clock))

    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(token, ctx(clock))
    assert err.value.code == "session_revoked"

    # A newly issued token is not proof of a new authentication ceremony.
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    assert err.value.code == "session_revoked"

    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(provider.issue_token("sub-a", AUD, auth_time=clock.now() - timedelta(seconds=1)), ctx(clock))
    assert err.value.code == "session_revoked"

    clock.advance(1)
    fresh = provider.issue_token("sub-a", AUD, auth_time=clock.now())
    assert svc.authenticate(fresh, ctx(clock)).principal_id == principal.principal_id


def test_deleted_account_requires_real_reauthentication_before_fresh_rebind():
    clock, provider, store, svc = identity()
    token = provider.issue_token("sub-a", AUD)
    principal = svc.authenticate(token, ctx(clock))
    svc.delete_account(principal, ctx(clock))
    assert store.outbox == [("account.deletion_requested", principal.principal_id)]

    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(token, ctx(clock))
    assert err.value.code == "account_deleted"

    # Token refresh/issuance alone cannot resurrect the binding as a fresh account.
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    assert err.value.code == "account_deleted"

    clock.advance(1)
    fresh = svc.authenticate(provider.issue_token("sub-a", AUD, auth_time=clock.now()), ctx(clock))
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


def test_guest_logout_everywhere_retires_the_guest_capability():
    clock, provider, store, svc = identity()
    guest, token = svc.create_guest()
    svc.logout_everywhere(svc.authenticate(token, ctx(clock)), ctx(clock))
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate(token, ctx(clock))
    assert err.value.code == "session_revoked"


def test_concurrent_fresh_logins_after_deletion_converge_on_one_new_account():
    clock, provider, store, svc = identity()
    principal = svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    svc.delete_account(principal, ctx(clock))
    clock.advance(1)
    first = provider.issue_token("sub-a", AUD, auth_time=clock.now())
    second = provider.issue_token("sub-a", AUD, auth_time=clock.now())
    real_lookup = store.principal_for_binding
    # Simulate the race: the second request read the tombstone before the first rebound it.
    tombstone = store.principals[principal.principal_id]
    calls = {"n": 0}

    def racing_lookup(issuer, subject):
        calls["n"] += 1
        return tombstone if calls["n"] == 1 else real_lookup(issuer, subject)

    winner = svc.authenticate(first, ctx(clock))
    store.principal_for_binding = racing_lookup
    loser = svc.authenticate(second, ctx(clock))
    assert loser.principal_id == winner.principal_id != principal.principal_id


def test_identity_service_rejects_future_auth_time_before_rebinding_state(monkeypatch):
    clock, provider, store, svc = identity()
    principal = svc.authenticate(provider.issue_token("sub-a", AUD), ctx(clock))
    svc.delete_account(principal, ctx(clock))

    def impossible_freshness(_credential, expected_audience, _ctx):
        return VerifiedIdentity(
            issuer=provider.issuer,
            subject="sub-a",
            audience=expected_audience,
            expires_at=clock.now() + timedelta(hours=1),
            auth_time=clock.now() + timedelta(seconds=60),
        )

    monkeypatch.setattr(provider, "verify_credential", impossible_freshness)
    with pytest.raises(Unauthenticated) as err:
        svc.authenticate("signed-provider-credential", ctx(clock))
    assert err.value.code == "identity_auth_time_invalid"
    assert store.principal_for_binding(provider.issuer, "sub-a").principal_id == principal.principal_id


def test_replayed_requests_cannot_reverse_a_newer_decision():
    clock, svc = service()
    grant = svc.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
                       decision=Decision.GRANT, notice_version=NOTICE, request_id="req-grant-1")
    clock.advance(1)
    svc.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
               decision=Decision.WITHDRAW, notice_version=NOTICE, request_id="req-withdraw-1")
    clock.advance(1)
    replay = svc.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
                        decision=Decision.GRANT, notice_version=NOTICE, request_id="req-grant-1")
    assert replay == grant and svc.check("w", "service_processing", SPECIMEN).reason == "withdraw"
    with pytest.raises(Conflict):
        svc.record(subject_id="w", actor_id="w", purpose_id="service_processing", scope=SPECIMEN,
                   decision=Decision.DENY, notice_version=NOTICE, request_id="req-grant-1")
