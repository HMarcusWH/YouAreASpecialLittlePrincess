"""Bounded HTTPS JWKS retrieval for the reviewed Supabase Auth profile.

The URL is derived only from the configured issuer. Token-controlled URLs are
never followed, redirects are refused, response bytes/key counts are bounded,
and provider/network failures cross the adapter boundary as typed safe errors.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from ...ports.base import InvalidInput, PermanentFailure, RateLimited, TransientUnavailable

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_KEYS = 64


def supabase_jwks_url(issuer: str) -> str:
    """Return the one allowed JWKS endpoint for an explicitly configured issuer."""
    if not isinstance(issuer, str) or not issuer or len(issuer) > 512:
        raise InvalidInput("invalid_identity_issuer")
    parts = urlsplit(issuer)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise InvalidInput("invalid_identity_issuer")
    return issuer.rstrip("/") + "/.well-known/jwks.json"


class SupabaseJwksSource:
    """Callable JWKS source suitable for :class:`SupabaseIdentityProvider`.

    This source deliberately does not cache keys. The verifier owns bounded key
    refresh semantics, so there is one cache/rotation policy rather than two.
    """

    def __init__(
        self,
        issuer: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_keys: int = DEFAULT_MAX_KEYS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = supabase_jwks_url(issuer)
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not 0 < float(timeout_s) <= 30:
            raise InvalidInput("invalid_identity_jwks_timeout")
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 1024 * 1024:
            raise InvalidInput("invalid_identity_jwks_limit")
        if type(max_keys) is not int or not 1 <= max_keys <= 256:
            raise InvalidInput("invalid_identity_jwks_key_limit")
        self._timeout_s = float(timeout_s)
        self._max_bytes = max_bytes
        self._max_keys = max_keys
        self._transport = transport

    def __call__(self) -> Mapping[str, object]:
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout_s,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", self.url, headers={"Accept": "application/json"}) as response:
                    status = response.status_code
                    if status == 429:
                        raise RateLimited("identity_jwks_rate_limited")
                    if 500 <= status <= 599:
                        raise TransientUnavailable("identity_jwks_unavailable")
                    if 300 <= status <= 399:
                        raise PermanentFailure("identity_jwks_redirect_refused")
                    if status != 200:
                        raise PermanentFailure("identity_jwks_http_error")

                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise PermanentFailure("identity_jwks_too_large")
                        chunks.append(chunk)
        except (RateLimited, TransientUnavailable, PermanentFailure):
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            raise TransientUnavailable("identity_jwks_unavailable") from None

        try:
            document = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, ValueError):
            raise PermanentFailure("identity_jwks_invalid") from None
        if not isinstance(document, dict):
            raise PermanentFailure("identity_jwks_invalid")
        keys = document.get("keys")
        if not isinstance(keys, list) or len(keys) > self._max_keys:
            raise PermanentFailure("identity_jwks_invalid")
        return document
