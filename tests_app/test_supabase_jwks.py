from __future__ import annotations

import httpx
import pytest

from princess_app.adapters.supabase.jwks import SupabaseJwksSource, supabase_jwks_url
from princess_app.ports.base import InvalidInput, PermanentFailure, RateLimited, TransientUnavailable

ISSUER = "https://project.supabase.invalid/auth/v1"
JWKS = {"keys": [{"kty": "RSA", "kid": "k1", "use": "sig"}]}


def test_source_uses_only_fixed_issuer_jwks_endpoint_and_no_redirects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(200, json=JWKS)

    source = SupabaseJwksSource(ISSUER, transport=httpx.MockTransport(handler))
    assert source() == JWKS
    assert seen == {
        "url": "https://project.supabase.invalid/auth/v1/.well-known/jwks.json",
        "accept": "application/json",
    }


@pytest.mark.parametrize(
    "issuer",
    [
        "",
        "http://project.supabase.invalid/auth/v1",
        "https://user@project.supabase.invalid/auth/v1",
        "https://project.supabase.invalid/auth/v1?next=https://evil.invalid",
        "https://project.supabase.invalid/auth/v1#fragment",
    ],
)
def test_jwks_url_rejects_untrusted_issuer_shapes(issuer):
    with pytest.raises(InvalidInput) as err:
        supabase_jwks_url(issuer)
    assert err.value.code == "invalid_identity_issuer"


def test_redirect_is_refused_instead_of_followed():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.invalid/jwks.json"})

    with pytest.raises(PermanentFailure) as err:
        SupabaseJwksSource(ISSUER, transport=httpx.MockTransport(handler))()
    assert err.value.code == "identity_jwks_redirect_refused"
    assert calls == ["https://project.supabase.invalid/auth/v1/.well-known/jwks.json"]


@pytest.mark.parametrize(
    "response,error_type,code",
    [
        (httpx.Response(429), RateLimited, "identity_jwks_rate_limited"),
        (httpx.Response(503), TransientUnavailable, "identity_jwks_unavailable"),
        (httpx.Response(403), PermanentFailure, "identity_jwks_http_error"),
    ],
)
def test_http_failures_are_typed_and_redacted(response, error_type, code):
    def handler(_: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(error_type) as err:
        SupabaseJwksSource(ISSUER, transport=httpx.MockTransport(handler))()
    assert err.value.code == code
    assert str(err.value) == code


def test_transport_failure_is_retryable_without_provider_detail_leak():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret upstream detail", request=request)

    with pytest.raises(TransientUnavailable) as err:
        SupabaseJwksSource(ISSUER, transport=httpx.MockTransport(handler))()
    assert err.value.code == "identity_jwks_unavailable"
    assert "secret" not in str(err.value)


@pytest.mark.parametrize(
    "body,max_bytes,code",
    [
        (b"not-json", 256 * 1024, "identity_jwks_invalid"),
        (b'{"wrong":[]}', 256 * 1024, "identity_jwks_invalid"),
        (b'{"keys":' + b"[]" + b"," + b'"pad":"' + b"x" * 2048 + b'"}', 1024, "identity_jwks_too_large"),
    ],
)
def test_jwks_body_is_bounded_and_shape_checked(body, max_bytes, code):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with pytest.raises(PermanentFailure) as err:
        SupabaseJwksSource(
            ISSUER,
            max_bytes=max_bytes,
            transport=httpx.MockTransport(handler),
        )()
    assert err.value.code == code


def test_key_count_is_bounded():
    document = {"keys": [{"kid": str(i)} for i in range(3)]}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=document)

    with pytest.raises(PermanentFailure) as err:
        SupabaseJwksSource(
            ISSUER,
            max_keys=2,
            transport=httpx.MockTransport(handler),
        )()
    assert err.value.code == "identity_jwks_invalid"
