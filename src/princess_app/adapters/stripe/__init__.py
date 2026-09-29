"""Stripe HTTPS adapter for PaymentProvider (T19), production-disabled by composition.

Uses the already-reviewed backend httpx dependency rather than the Stripe SDK.
The application owns catalog, ledger, grants and idempotency semantics. Stripe
is only an observed payment rail:

* hosted Checkout creation uses the server catalog and the internal intent as
  Stripe's idempotency key;
* webhook signatures are verified over the unmodified raw body before JSON
  parsing;
* events only name transactions to reconcile; PaymentIntent lookup is the
  authoritative purchase observation;
* provider/account/product/environment data are normalized into the existing
  PaymentProvider DTOs and never grant credits here.

Constructing the adapter requires activation_approved=True. No production
composition sets that flag today; tests use it only with an in-process
httpx.MockTransport. Price/catalog terms and processor approval remain
external gates.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlencode, urlsplit

import httpx

from ...ports import payments as port
from ...ports.base import (
    AmbiguousOutcome,
    CallContext,
    CapabilityProfile,
    Clock,
    Conflict,
    Environment,
    InvalidInput,
    NotFound,
    PermanentFailure,
    ProviderMode,
    RateLimited,
    TransientUnavailable,
    Unauthenticated,
    Unsupported,
    check_mode_allowed,
    require_opaque_id,
    require_utc,
)

DEFAULT_BASE_URL = "https://api.stripe.com/v1"
DEFAULT_SIGNATURE_TOLERANCE_S = 300
_MAX_RECONCILE_PAGES = 10
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9_]{3,255}$")

_CHECKOUT_EVENT_TYPES = frozenset({
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
})
_PAYMENT_INTENT_EVENT_TYPES = frozenset({
    "payment_intent.succeeded",
    "payment_intent.processing",
    "payment_intent.payment_failed",
    "payment_intent.canceled",
})
_CHARGE_EVENT_TYPES = frozenset({"charge.refunded"})
_RELEVANT_EVENT_TYPES = _CHECKOUT_EVENT_TYPES | _PAYMENT_INTENT_EVENT_TYPES | _CHARGE_EVENT_TYPES

_PENDING = frozenset({"processing", "requires_action", "requires_confirmation", "requires_capture"})
_FAILED = frozenset({"requires_payment_method"})


class StripePaymentProvider:
    port_name = port.PORT
    rail = port.PaymentRail.STRIPE

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        api_version: str,
        success_url: str,
        cancel_url: str,
        catalog: Sequence[port.CatalogProduct],
        clock: Clock,
        environment: Environment,
        mode: ProviderMode,
        activation_approved: bool = False,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 20.0,
        signature_tolerance_s: int = DEFAULT_SIGNATURE_TOLERANCE_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if mode is ProviderMode.FAKE:
            raise InvalidInput("real_adapter_cannot_be_fake")
        if not activation_approved:
            raise Unsupported("payment_provider_activation_not_approved")
        if not api_key or not webhook_secret or not api_version:
            raise InvalidInput("stripe_adapter_misconfigured")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise InvalidInput("stripe_timeout_invalid")
        if type(signature_tolerance_s) is not int or signature_tolerance_s <= 0:
            raise InvalidInput("stripe_signature_tolerance_invalid")
        if not _https_url(base_url) and transport is None:
            raise InvalidInput("provider_base_url_must_be_https")
        if not _https_url(success_url) or not _https_url(cancel_url):
            raise InvalidInput("checkout_redirect_must_be_https")

        stripe_catalog = [p for p in catalog if p.rail is port.PaymentRail.STRIPE]
        if not stripe_catalog:
            raise InvalidInput("stripe_catalog_empty")
        self._products = {p.product_id: p for p in stripe_catalog}
        self._clock = clock
        self._secret = webhook_secret.encode("utf-8")
        self._success_url = success_url
        self._cancel_url = cancel_url
        self._timeout_s = float(timeout_s)
        self._signature_tolerance_s = signature_tolerance_s
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {api_key}", "Stripe-Version": api_version},
        )
        self.profile = CapabilityProfile(
            port=port.PORT,
            provider="stripe-http",
            mode=mode,
            capabilities=frozenset({
                port.WEB_CHECKOUT,
                port.SIGNED_EVENTS,
                port.AUTHORITATIVE_LOOKUP,
                port.RECONCILE,
            }),
        )

    def __repr__(self) -> str:
        return f"StripePaymentProvider(mode={self.profile.mode.value}, environment={self.environment.value})"

    def create_web_checkout(
        self,
        intent_ref: str,
        product: port.CatalogProduct,
        account_ref: str,
        ctx: CallContext,
    ) -> port.CheckoutSession:
        self.profile.require(port.WEB_CHECKOUT)
        self._check_context(ctx)
        require_opaque_id(intent_ref, "intent_ref")
        require_opaque_id(account_ref, "account_ref")
        expected = self._products.get(product.product_id)
        if expected is None or expected != product:
            raise InvalidInput("product_not_on_rail")
        metadata = {
            "internal_product_id": product.product_id,
            "store_product_id": product.store_product_id,
            "account_ref": account_ref,
            "environment": self.environment.value,
            "intent_ref": intent_ref,
        }
        data: list[tuple[str, str]] = [
            ("mode", "payment"),
            ("line_items[0][price]", product.store_product_id),
            ("line_items[0][quantity]", "1"),
            ("client_reference_id", account_ref),
            ("success_url", self._success_url),
            ("cancel_url", self._cancel_url),
        ]
        for key, value in metadata.items():
            data.append((f"metadata[{key}]", value))
            data.append((f"payment_intent_data[metadata][{key}]", value))
        payload = self._request_json(
            "POST",
            "/checkout/sessions",
            ctx,
            data=data,
            headers={"Idempotency-Key": intent_ref},
            mutating=True,
        )
        self._check_livemode(payload)
        session_ref = _provider_id(payload.get("id"), "cs_", "stripe_checkout_invalid")
        redirect_url = payload.get("url")
        expires_at = _timestamp(payload.get("expires_at"), "stripe_checkout_invalid")
        if not isinstance(redirect_url, str) or not _https_url(redirect_url):
            raise PermanentFailure("stripe_checkout_invalid")
        return port.CheckoutSession(session_ref, redirect_url, expires_at)

    def verify_purchase(
        self,
        proof: str,
        expected_account_ref: str,
        ctx: CallContext,
    ) -> port.TransactionObservation:
        self.profile.require(port.VERIFY_PROOF)
        raise Unsupported("capability_not_supported", detail="stripe-http:verify_proof")

    def verify_and_normalize_event(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        ctx: CallContext,
    ) -> port.NormalizedEvent:
        self.profile.require(port.SIGNED_EVENTS)
        self._check_context(ctx)
        if not isinstance(raw_body, bytes):
            raise InvalidInput("stripe_event_body_invalid")
        timestamp, signatures = self._signature_parts(_header(headers, "stripe-signature"))
        signed = str(timestamp).encode("ascii") + b"." + raw_body
        expected = hmac.new(self._secret, signed, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, signature) for signature in signatures):
            raise Unauthenticated("bad_signature")
        if abs(self._clock.now().timestamp() - timestamp) > self._signature_tolerance_s:
            raise Unauthenticated("stale_signature")
        try:
            payload = json.loads(raw_body)
        except ValueError:
            raise InvalidInput("malformed_event") from None
        if not isinstance(payload, dict):
            raise InvalidInput("malformed_event")
        event_id = _provider_id(payload.get("id"), "evt_", "malformed_event")
        event_type = payload.get("type")
        if not isinstance(event_type, str) or not 0 < len(event_type) <= 128:
            raise InvalidInput("malformed_event")
        self._check_livemode(payload)
        created = _timestamp(payload.get("created"), "malformed_event")
        obj = ((payload.get("data") or {}).get("object") if isinstance(payload.get("data"), dict) else None)
        if not isinstance(obj, dict):
            raise InvalidInput("malformed_event")
        transaction_refs = self._event_refs(event_type, obj)
        event_environment = self._event_environment(event_type, obj)
        return port.NormalizedEvent(
            self.rail,
            event_environment,
            event_id,
            event_type,
            transaction_refs,
            created,
        )

    def retrieve_authoritative_purchase(
        self,
        transaction_ref: str,
        expected_account_ref: str,
        ctx: CallContext,
    ) -> port.TransactionObservation:
        self.profile.require(port.AUTHORITATIVE_LOOKUP)
        self._check_context(ctx)
        ref = _provider_id(transaction_ref, "pi_", "invalid_transaction_ref")
        payload = self._request_json(
            "GET",
            f"/payment_intents/{quote(ref, safe='')}",
            ctx,
            params=[("expand[]", "latest_charge")],
        )
        return self._observation(payload, expected_account_ref)

    def complete_store_purchase(
        self,
        transaction_ref: str,
        action: port.CompletionAction,
        ctx: CallContext,
    ) -> None:
        if action is port.CompletionAction.SERVER_CONSUME:
            self.profile.require(port.SERVER_CONSUME)
        elif action is port.CompletionAction.SERVER_ACKNOWLEDGE:
            self.profile.require(port.SERVER_ACKNOWLEDGE)
        else:
            raise Unsupported("not_a_server_completion", detail=action.value)

    def request_refund_if_supported(self, transaction_ref: str, ctx: CallContext) -> None:
        self.profile.require(port.REFUND_REQUEST)
        raise Unsupported("capability_not_supported", detail="stripe-http:refund_request")

    def reconcile(self, since: datetime, ctx: CallContext) -> Sequence[port.TransactionObservation]:
        self.profile.require(port.RECONCILE)
        self._check_context(ctx)
        require_utc(since, "since")
        observations: list[port.TransactionObservation] = []
        starting_after: str | None = None
        for _ in range(_MAX_RECONCILE_PAGES):
            params: list[tuple[str, str]] = [
                ("created[gte]", str(int(since.timestamp()))),
                ("limit", "100"),
                ("expand[]", "data.latest_charge"),
            ]
            if starting_after is not None:
                params.append(("starting_after", starting_after))
            payload = self._request_json("GET", "/payment_intents", ctx, params=params)
            data = payload.get("data")
            if not isinstance(data, list):
                raise PermanentFailure("stripe_response_invalid")
            page = [self._observation(item, "") for item in data if isinstance(item, dict)]
            if len(page) != len(data):
                raise PermanentFailure("stripe_response_invalid")
            observations.extend(page)
            if payload.get("has_more") is not True:
                return observations
            if not data:
                raise PermanentFailure("stripe_response_invalid")
            starting_after = _provider_id(data[-1].get("id"), "pi_", "stripe_response_invalid")
        raise PermanentFailure("stripe_reconcile_page_limit")

    def close(self) -> None:
        self._client.close()

    def _observation(self, payload: Mapping[str, Any], expected_account_ref: str) -> port.TransactionObservation:
        if payload.get("object") != "payment_intent":
            raise PermanentFailure("stripe_response_invalid")
        self._check_livemode(payload)
        ref = _provider_id(payload.get("id"), "pi_", "stripe_response_invalid")
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}
        raw_product = metadata.get("internal_product_id")
        raw_store_product = metadata.get("store_product_id")
        product_id = raw_product if isinstance(raw_product, str) and _opaque(raw_product) else "unknown_product"
        product = self._products.get(product_id)
        if product is not None and raw_store_product != product.store_product_id:
            product_id = "unknown_product"

        account_ref = metadata.get("account_ref")
        if not isinstance(account_ref, str) or not _opaque(account_ref):
            account_ref = None
        if account_ref is None:
            binding = port.AccountBinding.UNKNOWN
        elif expected_account_ref and account_ref == expected_account_ref:
            binding = port.AccountBinding.MATCHED
        elif expected_account_ref:
            binding = port.AccountBinding.MISMATCHED
        else:
            binding = port.AccountBinding.UNKNOWN

        environment = _metadata_environment(metadata.get("environment"))
        status = payload.get("status")
        state = self._state(status, payload.get("latest_charge"))
        created = _optional_timestamp(payload.get("created"))
        return port.TransactionObservation(
            rail=self.rail,
            environment=environment,
            transaction_ref=ref,
            product_id=product_id,
            quantity=1,
            state=state,
            account_binding=binding,
            completion_action=port.CompletionAction.NONE,
            purchased_at=created if state is port.PurchaseState.PURCHASED else None,
            refunded_at=None,
            completed=True,
            account_ref=account_ref,
        )

    def _state(self, status: Any, latest_charge: Any) -> port.PurchaseState:
        if isinstance(latest_charge, Mapping):
            amount = latest_charge.get("amount")
            refunded = latest_charge.get("amount_refunded")
            if latest_charge.get("refunded") is True:
                return port.PurchaseState.REFUNDED
            if type(amount) is int and type(refunded) is int and 0 < refunded < amount:
                return port.PurchaseState.UNKNOWN
            if type(amount) is int and amount > 0 and refunded == amount:
                return port.PurchaseState.REFUNDED
        if status == "succeeded":
            return port.PurchaseState.PURCHASED
        if status in _PENDING:
            return port.PurchaseState.PENDING
        if status in _FAILED:
            return port.PurchaseState.FAILED
        if status == "canceled":
            return port.PurchaseState.CANCELLED
        return port.PurchaseState.UNKNOWN

    def _event_refs(self, event_type: str, obj: Mapping[str, Any]) -> tuple[str, ...]:
        if event_type not in _RELEVANT_EVENT_TYPES:
            return ()
        raw: Any
        if event_type in _CHECKOUT_EVENT_TYPES:
            if obj.get("object") != "checkout.session":
                raise InvalidInput("malformed_event")
            raw = obj.get("payment_intent")
        elif event_type in _PAYMENT_INTENT_EVENT_TYPES:
            if obj.get("object") != "payment_intent":
                raise InvalidInput("malformed_event")
            raw = obj.get("id")
        else:
            if obj.get("object") != "charge":
                raise InvalidInput("malformed_event")
            raw = obj.get("payment_intent")
        if isinstance(raw, Mapping):
            raw = raw.get("id")
        if raw is None and event_type == "checkout.session.expired":
            return ()
        return (_provider_id(raw, "pi_", "malformed_event"),)

    def _event_environment(self, event_type: str, obj: Mapping[str, Any]) -> Environment:
        if event_type not in _RELEVANT_EVENT_TYPES:
            return self.environment
        metadata = obj.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("environment") is not None:
            return _metadata_environment(metadata.get("environment"))
        if event_type in _CHARGE_EVENT_TYPES:
            return self.environment
        return Environment.LOCAL

    def _signature_parts(self, header: str | None) -> tuple[int, tuple[str, ...]]:
        if not header:
            raise Unauthenticated("bad_signature")
        timestamp: int | None = None
        signatures: list[str] = []
        for part in header.split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            if key == "t" and value.isdigit():
                timestamp = int(value)
            elif key == "v1" and re.fullmatch(r"[0-9a-fA-F]{64}", value):
                signatures.append(value.lower())
        if timestamp is None or not signatures:
            raise Unauthenticated("bad_signature")
        return timestamp, tuple(signatures)

    def _check_context(self, ctx: CallContext) -> None:
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)

    def _check_livemode(self, payload: Mapping[str, Any]) -> None:
        livemode = payload.get("livemode")
        if type(livemode) is not bool:
            raise PermanentFailure("stripe_response_invalid")
        expected = self.profile.mode is ProviderMode.LIVE
        if livemode is not expected:
            raise InvalidInput("stripe_mode_mismatch")

    def _request_json(
        self,
        method: str,
        path: str,
        ctx: CallContext,
        *,
        data: Sequence[tuple[str, str]] | None = None,
        params: Sequence[tuple[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
        mutating: bool = False,
    ) -> dict[str, Any]:
        self._check_context(ctx)
        budget = max(0.1, min(self._timeout_s, ctx.remaining(self._clock) / timedelta(seconds=1)))
        timeout = httpx.Timeout(budget, connect=min(5.0, budget))
        request_headers = dict(headers or {})
        content = None
        if data is not None:
            content = urlencode(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        try:
            response = self._client.request(
                method, path, content=content, params=params, headers=request_headers, timeout=timeout
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TransientUnavailable("provider_unreachable") from None
        except (httpx.TimeoutException, httpx.TransportError):
            if mutating:
                raise AmbiguousOutcome("provider_outcome_unknown") from None
            raise TransientUnavailable("provider_unavailable") from None
        self._raise_http(response)
        try:
            payload = response.json()
        except ValueError:
            if mutating:
                raise AmbiguousOutcome("provider_response_unreadable") from None
            raise TransientUnavailable("provider_response_unreadable") from None
        if not isinstance(payload, dict):
            raise PermanentFailure("stripe_response_invalid")
        return payload

    @staticmethod
    def _raise_http(response: httpx.Response) -> None:
        status = response.status_code
        if status == 429:
            retry = response.headers.get("retry-after")
            raise RateLimited(
                "provider_rate_limited",
                retry_after_s=float(retry) if retry and retry.replace(".", "", 1).isdigit() else None,
            )
        if status in (500, 502, 503, 504):
            raise TransientUnavailable("provider_unavailable")
        if status in (401, 403):
            raise PermanentFailure("provider_credentials_rejected")
        if status == 404:
            raise NotFound("provider_object_not_found")
        if status == 409:
            raise Conflict("provider_conflict")
        if not 200 <= status < 300:
            raise PermanentFailure("provider_rejected_request", detail=str(status))


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value
    return None


def _https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None


def _provider_id(value: Any, prefix: str, code: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or not _PROVIDER_ID.fullmatch(value):
        raise InvalidInput(code)
    return value


def _timestamp(value: Any, code: str) -> datetime:
    if type(value) is not int or value < 0:
        raise InvalidInput(code)
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise InvalidInput(code) from None


def _optional_timestamp(value: Any) -> datetime | None:
    if type(value) is not int or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _metadata_environment(value: Any) -> Environment:
    try:
        return Environment.parse(value)
    except InvalidInput:
        return Environment.LOCAL


def _opaque(value: str) -> bool:
    try:
        require_opaque_id(value, "provider_metadata")
    except InvalidInput:
        return False
    return True


__all__ = ["DEFAULT_BASE_URL", "DEFAULT_SIGNATURE_TOLERANCE_S", "StripePaymentProvider"]
