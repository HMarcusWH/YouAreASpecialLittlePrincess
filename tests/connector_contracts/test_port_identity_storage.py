"""IdentityProvider and ObjectStore contract cases."""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from port_harness import ctx

from princess_app.adapters.fakes import FakeClock, FakeIdentityProvider, FakeObjectStore
from princess_app.ports import identity as identity_port
from princess_app.ports import storage
from princess_app.ports.base import Conflict, InvalidInput, NotFound, Unauthenticated, Unsupported

AUD = "princess-api"


def idp():
    clock = FakeClock()
    return clock, FakeIdentityProvider(clock=clock)


def test_valid_token_yields_identity_without_invented_attributes():
    clock, provider = idp()
    token = provider.issue_token("user-1", AUD, session_id="s1")
    identity = provider.verify_credential(token, AUD, ctx(clock))
    assert identity.binding_key == (provider.issuer, "user-1")
    assert identity.email is None and identity.email_verified is None  # unknown, not False
    assert identity.auth_time is None  # token issuance never invents reauthentication freshness
    assert provider.profile.supports(identity_port.VERIFY_CREDENTIAL)
    assert identity_port.VERIFY_ID_TOKEN == identity_port.VERIFY_CREDENTIAL  # source-compat alias


@pytest.mark.parametrize("case,code", [
    ("expired", "expired"), ("wrong_audience", "wrong_audience"), ("rotated", "unknown_signing_key"),
    ("revoked", "session_revoked"), ("garbage", "malformed_or_unknown_token"), ("deleted", "account_deleted"),
])
def test_identity_rejections(case, code):
    clock, provider = idp()
    token = provider.issue_token("user-1", AUD if case != "wrong_audience" else "other-aud", ttl_s=60,
                                 session_id="s1")
    if case == "expired":
        clock.advance(61)
    elif case == "rotated":
        provider.rotate_keys()
    elif case == "revoked":
        provider.revoke_session("s1", ctx(clock))
    elif case == "garbage":
        token = "fakeid.kid-1.tok_999999"
    elif case == "deleted":
        provider.delete_provider_account(provider.issuer, "user-1", ctx(clock))
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token, AUD, ctx(clock))
    assert err.value.code == code


def test_provider_deletion_requires_matching_issuer():
    clock, provider = idp()
    token = provider.issue_token("user-1", AUD)
    with pytest.raises(InvalidInput):
        provider.delete_provider_account("https://other-issuer.invalid", "user-1", ctx(clock))
    assert provider.verify_credential(token, AUD, ctx(clock)).subject == "user-1"


def test_unverified_email_is_reported_as_supplied():
    clock, provider = idp()
    token = provider.issue_token("user-1", AUD, email="a@example.invalid", email_verified=False)
    assert provider.verify_credential(token, AUD, ctx(clock)).email_verified is False

def test_fake_auth_time_is_explicit_and_cannot_be_after_token_issuance():
    clock, provider = idp()
    authenticated = provider.issue_token("user-1", AUD, auth_time=clock.now())
    assert provider.verify_credential(authenticated, AUD, ctx(clock)).auth_time == clock.now()
    future = provider.issue_token("user-1", AUD, auth_time=clock.now() + timedelta(seconds=1))
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(future, AUD, ctx(clock))
    assert err.value.code == "invalid_auth_time"



def store(**kw):
    clock = FakeClock()
    return clock, FakeObjectStore(clock=clock, **kw)


POLICY = storage.UploadPolicy(frozenset({"image/png", "image/jpeg"}), max_bytes=1024, expires_in_s=300)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_upload_promote_read_roundtrip_and_duplicate_completion():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    assert "sig=" not in repr(ticket)
    s.client_put(ticket, b"png-bytes")
    stored = s.promote_verified_input(ticket.upload_id, sha(b"png-bytes"), ctx(clock))
    assert s.read_object(stored, ctx(clock)) == b"png-bytes"
    assert s.promote_verified_input(ticket.upload_id, sha(b"png-bytes"), ctx(clock)) == stored


def test_overwrite_between_inspect_and_promote_is_a_conflict():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"original")
    inspected = s.inspect_upload(ticket.upload_id, ctx(clock))
    assert inspected.present and inspected.provider_sha256 is None  # no provider checksum capability
    s.client_put(ticket, b"swapped!")  # bearer ticket still valid
    with pytest.raises(Conflict):
        s.promote_verified_input(ticket.upload_id, sha(b"original"), ctx(clock))


def test_promoted_bytes_are_immutable_after_later_overwrite():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"original")
    stored = s.promote_verified_input(ticket.upload_id, sha(b"original"), ctx(clock))
    s.client_put(ticket, b"changed")
    assert s.read_object(stored, ctx(clock)) == b"original"
    with pytest.raises(Conflict):
        s.promote_verified_input(ticket.upload_id, sha(b"changed"), ctx(clock))


def test_partial_upload_and_expired_ticket_and_oversize():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"complete-bytes", truncate_to=4)
    with pytest.raises(Conflict):
        s.promote_verified_input(ticket.upload_id, sha(b"complete-bytes"), ctx(clock))
    s.client_put(ticket, b"x" * 2048)  # provider does not enforce size at upload
    with pytest.raises(InvalidInput):
        s.promote_verified_input(ticket.upload_id, sha(b"x" * 2048), ctx(clock))
    clock.advance(301)
    with pytest.raises(Unauthenticated):
        s.client_put(ticket, b"late")


def test_promotion_requires_immutable_copy_capabilities():
    clock, s = store(capabilities={storage.PRESIGNED_PUT})
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"bytes")
    with pytest.raises(Unsupported):
        s.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))


def test_size_enforced_at_upload_only_when_capability_says_so():
    clock, s = store(capabilities={storage.PRESIGNED_PUT, storage.ENFORCE_MAX_BYTES_AT_UPLOAD,
                                   storage.SERVER_SIDE_COPY, storage.IMMUTABLE_VERSIONS})
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    with pytest.raises(InvalidInput):
        s.client_put(ticket, b"x" * 2048)


def test_missing_upload_and_disallowed_media():
    clock, s = store()
    with pytest.raises(InvalidInput):
        s.issue_upload_ticket("asset_1", "image/gif", POLICY, ctx(clock))
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    with pytest.raises(NotFound):
        s.promote_verified_input(ticket.upload_id, sha(b""), ctx(clock))


def test_delayed_delete_is_not_reported_complete_early():
    clock, s = store(delete_delay_s=60)
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"bytes")
    stored = s.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))
    derived = s.write_derivative("asset_1_thumb", stored, b"thumb", "image/png", ctx(clock))
    receipt = s.delete_asset_versions("asset_1", ctx(clock))
    assert receipt.versions_deleted == 1 and not receipt.complete
    assert s.verify_deletion("asset_1", ctx(clock)) is False
    assert s.read_object(stored, ctx(clock)) == b"bytes"  # still physically present
    clock.advance(61)
    assert s.verify_deletion("asset_1", ctx(clock)) is True
    with pytest.raises(NotFound):
        s.read_object(stored, ctx(clock))
    # Derivatives are separate assets; deletion must name them explicitly.
    assert s.read_object(derived, ctx(clock)) == b"thumb"


def test_download_ticket_is_redacted_and_bounded():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"bytes")
    stored = s.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))
    download = s.issue_download_ticket(stored, 60, ctx(clock))
    assert "sig" not in repr(download)
    with pytest.raises(InvalidInput):
        s.issue_download_ticket(stored, 86400, ctx(clock))


def test_expired_slot_cannot_be_promoted_but_a_promoted_retry_converges():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"bytes")
    clock.advance(301)
    with pytest.raises(Conflict):
        s.promote_verified_input(ticket.upload_id, sha(b"bytes"), ctx(clock))
    clock2, s2 = store()
    t2 = s2.issue_upload_ticket("asset_2", "image/png", POLICY, ctx(clock2))
    s2.client_put(t2, b"bytes")
    stored = s2.promote_verified_input(t2.upload_id, sha(b"bytes"), ctx(clock2))
    clock2.advance(301)
    assert s2.promote_verified_input(t2.upload_id, sha(b"bytes"), ctx(clock2)) == stored


def test_deletion_revokes_open_upload_slots():
    clock, s = store()
    ticket = s.issue_upload_ticket("asset_1", "image/png", POLICY, ctx(clock))
    s.client_put(ticket, b"bytes")
    s.delete_asset_versions("asset_1", ctx(clock))
    with pytest.raises(NotFound):
        s.client_put(ticket, b"again")
    with pytest.raises(NotFound):
        s.promote_verified_input(ticket.upload_id, sha(b"again"), ctx(clock))
    assert s.verify_deletion("asset_1", ctx(clock)) is True
    open_ticket = s.issue_upload_ticket("asset_2", "image/png", POLICY, ctx(clock))
    assert open_ticket and s.verify_deletion("asset_2", ctx(clock)) is False  # an open slot is not deleted


def test_report_exports_are_stored_without_a_parent_asset():
    clock, s = store()
    export = s.write_derivative("export_1", None, b"%PDF-1.7", "application/pdf", ctx(clock))
    assert export.sha256 == sha(b"%PDF-1.7") and s.read_object(export, ctx(clock)) == b"%PDF-1.7"
    with pytest.raises(Conflict):
        s.write_derivative("export_1", None, b"other", "application/pdf", ctx(clock))
    s.delete_asset_versions("export_1", ctx(clock))
    assert s.verify_deletion("export_1", ctx(clock))
