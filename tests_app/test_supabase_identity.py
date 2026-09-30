"""Supabase Auth candidate: access-token profile and AMR freshness qualification."""
from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from princess_app.adapters.fakes import FakeClock, SequentialIds
from princess_app.adapters.supabase import SupabaseIdentityProvider
from princess_app.application.identity import IdentityService, InMemoryIdentityStore
from princess_app.ports import identity as identity_port
from princess_app.ports.base import CallContext, Environment, InvalidInput, ProviderMode, Unauthenticated, Unsupported

ISS = "https://project.supabase.invalid/auth/v1"
AUD = "authenticated"
ROLE = "authenticated"
SUB = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"


def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(private, kid, alg="RS256"):
    if alg.startswith("RS"):
        raw = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())
    else:
        raw = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key())
    return {**json.loads(raw), "kid": kid, "alg": alg, "use": "sig"}


class Jwks:
    def __init__(self, *keys):
        self.keys = list(keys)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"keys": self.keys}


@pytest.fixture
def setup():
    clock = FakeClock()
    key = rsa_key()
    source = Jwks(jwk(key, "k1"))
    provider = SupabaseIdentityProvider(
        issuer=ISS,
        audience=AUD,
        allowed_roles=frozenset({ROLE}),
        jwks_source=source,
        clock=clock,
        environment=Environment.STAGING,
        mode=ProviderMode.SANDBOX,
        stock_claims_profile=True,
    )
    return clock, key, source, provider


def token(clock, key, kid="k1", alg="RS256", **overrides):
    now = int(clock.now().timestamp())
    claims = {
        "iss": ISS,
        "aud": AUD,
        "sub": SUB,
        "iat": now,
        "exp": now + 600,
        "role": ROLE,
        "aal": "aal1",
        "session_id": SID,
        "is_anonymous": False,
        "amr": [{"method": "oauth", "timestamp": now - 60}],
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def ctx(clock, environment=Environment.STAGING):
    return CallContext("corr-1", environment, clock.now() + timedelta(seconds=30))


def test_stock_access_token_maps_minimal_identity_and_amr_freshness(setup):
    clock, key, _, provider = setup
    identity = provider.verify_credential(token(clock, key), ctx(clock))
    assert identity.binding_key == (ISS, SUB)
    assert identity.session_id == SID
    assert identity.expires_at > clock.now()
    assert identity.auth_time == clock.now() - timedelta(seconds=60)
    assert identity.email is None and identity.email_verified is None
    assert provider.profile.capabilities == frozenset({identity_port.VERIFY_CREDENTIAL})


@pytest.mark.parametrize("overrides,code", [
    ({"iss": "https://evil.invalid/auth/v1"}, "wrong_issuer"),
    ({"aud": "other"}, "wrong_audience"),
    ({"aud": [AUD]}, "wrong_audience"),
    ({"role": "service_role"}, "unapproved_role"),
    ({"aal": "aal3"}, "invalid_aal"),
    ({"is_anonymous": True}, "anonymous_identity_not_allowed"),
    ({"session_id": None}, "invalid_token"),
    ({"session_id": "not-a-uuid"}, "invalid_session_id"),
    ({"sub": "not-a-uuid"}, "invalid_subject"),
    ({"client_id": str(uuid4())}, "unsupported_credential_profile"),
])
def test_candidate_context_claims_fail_closed(setup, overrides, code):
    clock, key, _, provider = setup
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token(clock, key, **overrides), ctx(clock))
    assert err.value.code == code


def test_nbf_is_optional_but_validated_when_present(setup):
    clock, key, _, provider = setup
    assert provider.verify_credential(token(clock, key), ctx(clock)).subject == SUB
    future = int(clock.now().timestamp()) + 3600
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token(clock, key, nbf=future), ctx(clock))
    assert err.value.code == "not_yet_valid"
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token(clock, key, nbf="bad"), ctx(clock))
    assert err.value.code == "invalid_token_time"


def test_refresh_iat_does_not_advance_authentication_freshness(setup):
    clock, key, _, provider = setup
    original_auth = int(clock.now().timestamp()) - 120
    first = provider.verify_credential(
        token(clock, key, amr=[{"method": "oauth", "timestamp": original_auth}]),
        ctx(clock),
    )
    clock.advance(300)
    refreshed = provider.verify_credential(
        token(clock, key, iat=int(clock.now().timestamp()),
              amr=[{"method": "oauth", "timestamp": original_auth}]),
        ctx(clock),
    )
    assert first.auth_time == refreshed.auth_time
    assert refreshed.auth_time < clock.now()


@pytest.mark.parametrize("amr", [None, [], ["oauth"], ["future-method"], [{"method": "token_refresh", "timestamp": 1}]])
def test_missing_string_unknown_or_refresh_only_amr_does_not_invent_freshness(setup, amr):
    clock, key, _, provider = setup
    identity = provider.verify_credential(token(clock, key, amr=amr), ctx(clock))
    assert identity.auth_time is None


@pytest.mark.parametrize("amr", [
    "oauth",
    [None],
    [{"method": "", "timestamp": 1}],
    [{"method": "oauth", "timestamp": "bad"}],
])
def test_malformed_amr_is_rejected(setup, amr):
    clock, key, _, provider = setup
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token(clock, key, amr=amr), ctx(clock))
    assert err.value.code == "invalid_amr"


def test_future_or_post_iat_amr_timestamp_is_rejected(setup):
    clock, key, _, provider = setup
    now = int(clock.now().timestamp())
    for claims in (
        {"amr": [{"method": "oauth", "timestamp": now + 3600}]},
        {"iat": now - 120, "amr": [{"method": "oauth", "timestamp": now}]},
    ):
        with pytest.raises(Unauthenticated) as err:
            provider.verify_credential(token(clock, key, **claims), ctx(clock))
        assert err.value.code == "invalid_amr"


def test_new_authenticated_session_can_cross_princess_revocation_fence(setup):
    clock, key, _, provider = setup
    service = IdentityService(provider, InMemoryIdentityStore(), clock, SequentialIds())
    old_auth = int(clock.now().timestamp()) - 60
    old = token(clock, key, amr=[{"method": "oauth", "timestamp": old_auth}])
    principal = service.authenticate(old, ctx(clock))

    clock.advance(10)
    service.logout_everywhere(principal, ctx(clock))
    clock.advance(10)

    refreshed_same_session = token(
        clock, key, session_id=SID, amr=[{"method": "oauth", "timestamp": old_auth}],
    )
    with pytest.raises(Unauthenticated) as err:
        service.authenticate(refreshed_same_session, ctx(clock))
    assert err.value.code == "session_revoked"

    new_session = str(uuid4())
    newly_authenticated = token(
        clock,
        key,
        session_id=new_session,
        amr=[{"method": "oauth", "timestamp": int(clock.now().timestamp())}],
    )
    assert service.authenticate(newly_authenticated, ctx(clock)).principal_id == principal.principal_id


def test_deleted_binding_requires_new_authentication_not_refresh(setup):
    clock, key, _, provider = setup
    store = InMemoryIdentityStore()
    service = IdentityService(provider, store, clock, SequentialIds())
    old_auth = int(clock.now().timestamp()) - 60
    old = token(clock, key, amr=[{"method": "password", "timestamp": old_auth}])
    principal = service.authenticate(old, ctx(clock))
    clock.advance(10)
    service.delete_account(principal, ctx(clock))
    clock.advance(10)

    with pytest.raises(Unauthenticated) as err:
        service.authenticate(
            token(clock, key, amr=[{"method": "password", "timestamp": old_auth}]),
            ctx(clock),
        )
    assert err.value.code == "account_deleted"

    fresh = service.authenticate(
        token(
            clock,
            key,
            session_id=str(uuid4()),
            amr=[{"method": "password", "timestamp": int(clock.now().timestamp())}],
        ),
        ctx(clock),
    )
    assert fresh.principal_id != principal.principal_id and fresh.deleted_at is None


def test_algorithm_confusion_symmetric_keys_and_token_key_urls_are_rejected(setup):
    clock, key, source, provider = setup
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = int(clock.now().timestamp())
    claims = {
        "iss": ISS, "aud": AUD, "sub": SUB, "iat": now, "exp": now + 60,
        "role": ROLE, "aal": "aal1", "session_id": SID, "is_anonymous": False,
    }
    forged_hs = jwt.encode(claims, public_pem.decode()[:40], algorithm="HS256", headers={"kid": "k1"})
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "k1"})
    attacker = rsa_key()
    evil = jwt.encode(claims, attacker, algorithm="RS256",
                      headers={"kid": "k1", "jku": "https://evil.invalid/jwks.json"})
    for bad in (forged_hs, unsigned, evil, "not.a.jwt"):
        with pytest.raises(Unauthenticated):
            provider.verify_credential(bad, ctx(clock))
    assert source.calls == 1

    symmetric = Jwks({"kty": "oct", "kid": "sym", "k": "c2VjcmV0", "alg": "HS256"})
    symmetric_provider = SupabaseIdentityProvider(
        issuer=ISS, audience=AUD, allowed_roles=frozenset({ROLE}), jwks_source=symmetric,
        clock=clock, environment=Environment.STAGING, mode=ProviderMode.SANDBOX,
        stock_claims_profile=True,
    )
    with pytest.raises(Unauthenticated):
        symmetric_provider.verify_credential(
            jwt.encode(claims, "secret", algorithm="HS256", headers={"kid": "sym"}),
            ctx(clock),
        )


def test_key_rotation_refresh_is_bounded(setup):
    clock, key, source, provider = setup
    provider.verify_credential(token(clock, key), ctx(clock))
    rotated = rsa_key()
    source.keys = [jwk(key, "k1"), jwk(rotated, "k2")]
    clock.advance(61)
    assert provider.verify_credential(token(clock, rotated, kid="k2"), ctx(clock)).subject == SUB
    calls = source.calls
    for _ in range(5):
        with pytest.raises(Unauthenticated):
            provider.verify_credential(token(clock, rotated, kid="unknown"), ctx(clock))
    assert source.calls == calls


def test_es256_and_profile_gates_and_unsupported_operations():
    clock = FakeClock()
    key = ec.generate_private_key(ec.SECP256R1())
    provider = SupabaseIdentityProvider(
        issuer=ISS,
        audience=AUD,
        allowed_roles=frozenset({ROLE}),
        jwks_source=Jwks(jwk(key, "e1", "ES256")),
        clock=clock,
        environment=Environment.STAGING,
        mode=ProviderMode.SANDBOX,
        stock_claims_profile=True,
    )
    assert provider.verify_credential(token(clock, key, kid="e1", alg="ES256"), ctx(clock)).subject == SUB

    with pytest.raises(Unsupported):
        provider.revoke_session(SID, ctx(clock))
    with pytest.raises(Unsupported):
        provider.delete_provider_account(ISS, SUB, ctx(clock))
    with pytest.raises(Unsupported) as err:
        SupabaseIdentityProvider(
            issuer=ISS, audience=AUD, allowed_roles=frozenset({ROLE}), jwks_source=Jwks(),
            clock=clock, environment=Environment.STAGING, mode=ProviderMode.SANDBOX,
            stock_claims_profile=False,
        )
    assert err.value.code == "supabase_custom_claim_profile_not_qualified"
    with pytest.raises(ValueError):
        SupabaseIdentityProvider(
            issuer=ISS, audience=AUD, allowed_roles=frozenset({ROLE}), jwks_source=Jwks(),
            clock=clock, environment=Environment.STAGING, mode=ProviderMode.SANDBOX,
            stock_claims_profile=True, allowed_algorithms=frozenset({"HS256"}),
        )
    with pytest.raises(InvalidInput):
        SupabaseIdentityProvider(
            issuer=ISS, audience=AUD, allowed_roles=frozenset({ROLE}), jwks_source=Jwks(),
            clock=clock, environment=Environment.PRODUCTION, mode=ProviderMode.SANDBOX,
            stock_claims_profile=True,
        )


def test_cross_environment_rejected_before_jwks_read(setup):
    clock, key, source, provider = setup
    with pytest.raises(InvalidInput):
        provider.verify_credential(token(clock, key), ctx(clock, Environment.PRODUCTION))
    assert source.calls == 0
