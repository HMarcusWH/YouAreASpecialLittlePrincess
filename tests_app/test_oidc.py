"""OIDC verifier: issuer/audience/time/algorithm confusion and key rotation."""
from __future__ import annotations

import json
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from princess_app.adapters.fakes import FakeClock
from princess_app.adapters.oidc import OidcIdentityProvider
from princess_app.ports.base import CallContext, Environment, InvalidInput, ProviderMode, Unauthenticated, Unsupported

ISS = "https://idp.example.invalid/"
AUD = "princess-api"


def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(private, kid, alg="RS256"):
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()) if alg.startswith("RS")
                      else jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    return {**data, "kid": kid, "alg": alg, "use": "sig"}


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
    provider = OidcIdentityProvider(issuer=ISS, jwks_source=source, clock=clock, environment=Environment.STAGING,
                                    mode=ProviderMode.SANDBOX)
    return clock, key, source, provider


def token(clock, key, kid="k1", alg="RS256", **overrides):
    now = int(clock.now().timestamp())
    claims = {"iss": ISS, "aud": AUD, "sub": "user-1", "iat": now, "exp": now + 600, "sid": "s1", **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def ctx(clock):
    return CallContext("corr-1", Environment.STAGING, clock.now() + timedelta(seconds=30))


def test_valid_token_maps_only_supplied_claims(setup):
    clock, key, _, provider = setup
    identity = provider.verify_credential(token(clock, key), AUD, ctx(clock))
    assert identity.binding_key == (ISS, "user-1") and identity.session_id == "s1"
    assert identity.email is None and identity.email_verified is None and identity.auth_time is not None


@pytest.mark.parametrize("overrides,code", [
    ({"aud": "someone-else"}, "wrong_audience"),
    ({"iss": "https://evil.invalid/"}, "wrong_issuer"),
    ({"exp": 1}, "expired"),
    ({"sub": None}, "invalid_token"),
])
def test_claim_rejections(setup, overrides, code):
    clock, key, _, provider = setup
    with pytest.raises(Unauthenticated) as err:
        provider.verify_credential(token(clock, key, **overrides), AUD, ctx(clock))
    assert err.value.code == code


def test_not_before_and_future_issued_at_are_rejected(setup):
    clock, key, _, provider = setup
    future = int(clock.now().timestamp()) + 3600
    for overrides in ({"nbf": future}, {"iat": future}):
        with pytest.raises(Unauthenticated) as err:
            provider.verify_credential(token(clock, key, **overrides), AUD, ctx(clock))
        assert err.value.code == "not_yet_valid"


def test_algorithm_confusion_and_none_are_rejected(setup):
    clock, key, _, provider = setup
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    now = int(clock.now().timestamp())
    claims = {"iss": ISS, "aud": AUD, "sub": "u", "iat": now, "exp": now + 60}
    forged_hs = jwt.encode(claims, public_pem.decode()[:40], algorithm="HS256", headers={"kid": "k1"})
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "k1"})
    for bad in (forged_hs, unsigned, "not.a.jwt"):
        with pytest.raises(Unauthenticated):
            provider.verify_credential(bad, AUD, ctx(clock))


def test_token_supplied_key_urls_are_never_followed(setup):
    clock, _, source, provider = setup
    attacker = rsa_key()
    now = int(clock.now().timestamp())
    evil = jwt.encode({"iss": ISS, "aud": AUD, "sub": "u", "iat": now, "exp": now + 60}, attacker, algorithm="RS256",
                      headers={"kid": "k1", "jku": "https://evil.invalid/jwks.json"})
    with pytest.raises(Unauthenticated):
        provider.verify_credential(evil, AUD, ctx(clock))
    assert source.calls == 1  # only the configured source was consulted


def test_key_rotation_refreshes_once_and_throttles(setup):
    clock, key, source, provider = setup
    provider.verify_credential(token(clock, key), AUD, ctx(clock))
    rotated = rsa_key()
    source.keys = [jwk(key, "k1"), jwk(rotated, "k2")]
    clock.advance(61)
    assert provider.verify_credential(token(clock, rotated, kid="k2"), AUD, ctx(clock)).subject == "user-1"
    calls = source.calls
    for _ in range(5):
        with pytest.raises(Unauthenticated):
            provider.verify_credential(token(clock, rotated, kid="unknown"), AUD, ctx(clock))
    assert source.calls == calls  # unknown kids cannot force a refresh storm


def test_symmetric_keys_in_jwks_are_ignored():
    clock = FakeClock()
    source = Jwks({"kty": "oct", "kid": "k1", "k": "c2VjcmV0", "alg": "HS256"})
    provider = OidcIdentityProvider(issuer=ISS, jwks_source=source, clock=clock, environment=Environment.STAGING,
                                    mode=ProviderMode.SANDBOX)
    now = int(clock.now().timestamp())
    forged = jwt.encode({"iss": ISS, "aud": AUD, "sub": "u", "iat": now, "exp": now + 60}, "secret",
                        algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(Unauthenticated):
        provider.verify_credential(forged, AUD, ctx(clock))


def test_es256_keys_and_mode_rules_and_unsupported_operations():
    clock = FakeClock()
    key = ec.generate_private_key(ec.SECP256R1())
    provider = OidcIdentityProvider(issuer=ISS, jwks_source=Jwks(jwk(key, "e1", "ES256")), clock=clock,
                                    environment=Environment.STAGING, mode=ProviderMode.SANDBOX)
    assert provider.verify_credential(token(clock, key, kid="e1", alg="ES256"), AUD, ctx(clock)).subject == "user-1"
    with pytest.raises(Unsupported):
        provider.revoke_session("s1", ctx(clock))
    with pytest.raises(InvalidInput):
        OidcIdentityProvider(issuer=ISS, jwks_source=Jwks(), clock=clock, environment=Environment.PRODUCTION,
                             mode=ProviderMode.SANDBOX)
    with pytest.raises(ValueError):
        OidcIdentityProvider(issuer=ISS, jwks_source=Jwks(), clock=clock, environment=Environment.STAGING,
                             mode=ProviderMode.SANDBOX, allowed_algorithms=frozenset({"HS256"}))
