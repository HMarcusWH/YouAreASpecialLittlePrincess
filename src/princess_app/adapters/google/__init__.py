"""Google Play server purchase/RTDN adapter (T19), production-disabled.

Uses ProductPurchaseV2 as authoritative purchase state, purchase tokens as the
financial identity, authenticated Pub/Sub push as a change signal, and the
legacy one-time-product consume/acknowledge endpoints only after the internal
ledger has durably granted the credit.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlencode

import httpx
import jwt

from ...ports import payments as port
from ...ports.base import (
    CallContext,
    CapabilityProfile,
    Clock,
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

DEFAULT_BASE_URL = "https://androidpublisher.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
PUBSUB_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{1,512}$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{2,255}$")
JwksSource = Callable[[], Mapping[str, Any]]


class GooglePlayPaymentProvider:
    port_name = port.PORT
    rail = port.PaymentRail.GOOGLE_PLAY

    def __init__(
        self,
        *,
        package_name: str,
        service_account: Mapping[str, Any],
        pubsub_audience: str,
        pubsub_service_account_email: str,
        catalog: Sequence[port.CatalogProduct],
        clock: Clock,
        environment: Environment,
        mode: ProviderMode,
        activation_approved: bool = False,
        base_url: str = DEFAULT_BASE_URL,
        token_url: str = DEFAULT_TOKEN_URL,
        jwks_url: str = DEFAULT_JWKS_URL,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        pubsub_jwks_source: JwksSource | None = None,
    ) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if mode is ProviderMode.FAKE:
            raise InvalidInput("real_adapter_cannot_be_fake")
        if not activation_approved:
            raise Unsupported("payment_provider_activation_not_approved")
        if not isinstance(package_name, str) or not _PACKAGE.fullmatch(package_name):
            raise InvalidInput("google_package_invalid")
        if not isinstance(pubsub_audience, str) or not pubsub_audience:
            raise InvalidInput("google_pubsub_audience_invalid")
        if not isinstance(pubsub_service_account_email, str) or "@" not in pubsub_service_account_email:
            raise InvalidInput("google_pubsub_identity_invalid")
        required = ("client_email", "private_key", "private_key_id")
        if not isinstance(service_account, Mapping) or not all(isinstance(service_account.get(k), str)
                                                               and service_account.get(k) for k in required):
            raise InvalidInput("google_service_account_invalid")
        if not base_url.startswith("https://") and transport is None:
            raise InvalidInput("provider_base_url_must_be_https")
        if not token_url.startswith("https://") and transport is None:
            raise InvalidInput("provider_token_url_must_be_https")
        google_catalog = [p for p in catalog if p.rail is self.rail]
        if not google_catalog:
            raise InvalidInput("google_catalog_empty")
        self.package_name = package_name
        self._products = {p.store_product_id: p for p in google_catalog}
        self._service_account = dict(service_account)
        self._pubsub_audience = pubsub_audience
        self._pubsub_email = pubsub_service_account_email
        self._clock = clock
        self._mode = mode
        self._timeout_s = float(timeout_s)
        self._token_url = token_url
        self._jwks_url = jwks_url
        self._jwks_source = pubsub_jwks_source
        self._client = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, follow_redirects=False)
        self._access_token: str | None = None
        self._access_token_expiry: datetime | None = None
        self._pubsub_keys: dict[str, jwt.PyJWK] = {}
        self.profile = CapabilityProfile(
            port=port.PORT,
            provider="google-play-http",
            mode=mode,
            capabilities=frozenset({
                port.VERIFY_PROOF,
                port.SIGNED_EVENTS,
                port.AUTHORITATIVE_LOOKUP,
                port.SERVER_CONSUME,
                port.SERVER_ACKNOWLEDGE,
                port.RECONCILE,
            }),
        )

    def __repr__(self) -> str:
        return f"GooglePlayPaymentProvider(mode={self.profile.mode.value}, environment={self.environment.value})"

    def create_web_checkout(self, intent_ref: str, product: port.CatalogProduct, account_ref: str,
                            ctx: CallContext) -> port.CheckoutSession:
        raise Unsupported("capability_not_supported", detail="google_play:web_checkout")

    def verify_purchase(self, proof: str, expected_account_ref: str,
                        ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.VERIFY_PROOF)
        return self.retrieve_authoritative_purchase(proof, expected_account_ref, ctx)

    def verify_and_normalize_event(self, raw_body: bytes, headers: Mapping[str, str],
                                   ctx: CallContext) -> port.NormalizedEvent:
        self.profile.require(port.SIGNED_EVENTS)
        self._check_context(ctx)
        self._verify_pubsub(headers)
        try:
            envelope = json.loads(raw_body)
        except (UnicodeDecodeError, ValueError):
            raise InvalidInput("google_rtdn_malformed") from None
        if not isinstance(envelope, Mapping):
            raise InvalidInput("google_rtdn_malformed")
        message = envelope.get("message")
        if not isinstance(message, Mapping):
            raise InvalidInput("google_rtdn_malformed")
        message_id = message.get("messageId") or message.get("message_id")
        if not isinstance(message_id, str) or not message_id or len(message_id) > 256:
            raise InvalidInput("google_rtdn_malformed")
        encoded = message.get("data")
        if not isinstance(encoded, str):
            raise InvalidInput("google_rtdn_malformed")
        try:
            notification = json.loads(base64.b64decode(encoded, validate=True))
        except (ValueError, TypeError, json.JSONDecodeError):
            raise InvalidInput("google_rtdn_malformed") from None
        if not isinstance(notification, Mapping) or notification.get("packageName") != self.package_name:
            raise InvalidInput("google_package_mismatch")
        occurred = _millis(notification.get("eventTimeMillis"), "google_rtdn_malformed")
        refs: tuple[str, ...] = ()
        event_type = "google.rtdn"
        one_time = notification.get("oneTimeProductNotification")
        voided = notification.get("voidedPurchaseNotification")
        if isinstance(one_time, Mapping):
            token = _purchase_token(one_time.get("purchaseToken"))
            sku = one_time.get("sku")
            if not isinstance(sku, str) or sku not in self._products:
                raise InvalidInput("google_product_unknown")
            kind = one_time.get("notificationType")
            if type(kind) is not int:
                raise InvalidInput("google_rtdn_malformed")
            refs, event_type = (token,), f"one_time_product:{kind}"
        elif isinstance(voided, Mapping):
            refs = (_purchase_token(voided.get("purchaseToken")),)
            event_type = "voided_purchase"
        elif notification.get("testNotification") is not None:
            event_type = "test_notification"
        return port.NormalizedEvent(
            rail=self.rail,
            environment=self.environment,
            event_id=message_id,
            event_type=event_type,
            transaction_refs=refs,
            occurred_at=occurred,
        )

    def retrieve_authoritative_purchase(self, transaction_ref: str, expected_account_ref: str,
                                        ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.AUTHORITATIVE_LOOKUP)
        self._check_context(ctx)
        token = _purchase_token(transaction_ref)
        payload = self._api_json(
            "GET",
            f"/androidpublisher/v3/applications/{quote(self.package_name, safe='')}"
            f"/purchases/productsv2/tokens/{quote(token, safe='')}",
            ctx,
        )
        return self._observation(payload, token, expected_account_ref)

    def complete_store_purchase(self, transaction_ref: str, action: port.CompletionAction,
                                ctx: CallContext) -> None:
        if action is port.CompletionAction.SERVER_CONSUME:
            self.profile.require(port.SERVER_CONSUME)
        elif action is port.CompletionAction.SERVER_ACKNOWLEDGE:
            self.profile.require(port.SERVER_ACKNOWLEDGE)
        else:
            raise Unsupported("not_a_server_completion", detail=action.value)
        token = _purchase_token(transaction_ref)
        current = self.retrieve_authoritative_purchase(token, "", ctx)
        product = next((p for p in self._products.values() if p.product_id == current.product_id), None)
        if product is None:
            raise InvalidInput("google_product_unknown")
        suffix = "consume" if action is port.CompletionAction.SERVER_CONSUME else "acknowledge"
        path = (
            f"/androidpublisher/v3/applications/{quote(self.package_name, safe='')}"
            f"/purchases/products/{quote(product.store_product_id, safe='')}/tokens/{quote(token, safe='')}:{suffix}"
        )
        self._api_empty("POST", path, ctx)

    def request_refund_if_supported(self, transaction_ref: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="google_play:refund_request")

    def reconcile(self, since: datetime, ctx: CallContext) -> Sequence[port.TransactionObservation]:
        self.profile.require(port.RECONCILE)
        self._check_context(ctx)
        require_utc(since, "since")
        now = self._clock.now()
        if since >= now:
            return ()
        if now - since > timedelta(days=30):
            raise InvalidInput("google_reconcile_window_exceeded")
        refs: list[str] = []
        seen: set[str] = set()
        page_token: str | None = None
        for _ in range(25):
            params = {
                "startTime": str(int(since.timestamp() * 1000)),
                "endTime": str(int(now.timestamp() * 1000)),
                "type": "0",
            }
            if page_token:
                params = {"token": page_token, "type": "0"}
            payload = self._api_json(
                "GET",
                f"/androidpublisher/v3/applications/{quote(self.package_name, safe='')}/purchases/voidedpurchases",
                ctx,
                params=params,
            )
            rows = payload.get("voidedPurchases", [])
            if not isinstance(rows, list):
                raise PermanentFailure("google_voided_response_invalid")
            for row in rows:
                if not isinstance(row, Mapping):
                    raise PermanentFailure("google_voided_response_invalid")
                ref = _purchase_token(row.get("purchaseToken"))
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
                    if len(refs) > 500:
                        raise PermanentFailure("google_reconcile_ref_limit")
            pagination = payload.get("tokenPagination")
            page_token = pagination.get("nextPageToken") if isinstance(pagination, Mapping) else None
            if not page_token:
                return tuple(self.retrieve_authoritative_purchase(ref, "", ctx) for ref in refs)
            if not isinstance(page_token, str):
                raise PermanentFailure("google_voided_response_invalid")
        raise PermanentFailure("google_reconcile_page_limit")

    def close(self) -> None:
        self._client.close()

    def _observation(self, payload: Mapping[str, Any], token: str,
                     expected_account_ref: str) -> port.TransactionObservation:
        self._require_purchase_environment(payload)
        state_context = payload.get("purchaseStateContext")
        state_name = state_context.get("purchaseState") if isinstance(state_context, Mapping) else None
        state = {
            "PURCHASED": port.PurchaseState.PURCHASED,
            "PENDING": port.PurchaseState.PENDING,
            "CANCELLED": port.PurchaseState.CANCELLED,
        }.get(state_name, port.PurchaseState.UNKNOWN)
        items = payload.get("productLineItem")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
            raise InvalidInput("google_purchase_shape_unsupported")
        item = items[0]
        store_product = item.get("productId")
        product = self._products.get(store_product) if isinstance(store_product, str) else None
        product_id = product.product_id if product is not None else "unknown_product"
        details = item.get("productOfferDetails")
        quantity = details.get("quantity", 1) if isinstance(details, Mapping) else 1
        refundable = details.get("refundableQuantity") if isinstance(details, Mapping) else None
        consumption = details.get("consumptionState") if isinstance(details, Mapping) else None
        if type(quantity) is not int or not 1 <= quantity <= 100:
            raise InvalidInput("google_purchase_shape_unsupported")
        if type(refundable) is int and 0 <= refundable < quantity and state is port.PurchaseState.PURCHASED:
            state = port.PurchaseState.REFUNDED if refundable == 0 else port.PurchaseState.UNKNOWN
        account_ref = payload.get("obfuscatedExternalAccountId")
        if account_ref is None:
            binding = port.AccountBinding.UNKNOWN
        elif isinstance(account_ref, str):
            require_opaque_id(account_ref, "account_ref")
            binding = (port.AccountBinding.MATCHED if expected_account_ref and account_ref == expected_account_ref
                       else port.AccountBinding.MISMATCHED if expected_account_ref else port.AccountBinding.UNKNOWN)
        else:
            raise InvalidInput("google_purchase_shape_unsupported")
        completed = (
            consumption == "CONSUMPTION_STATE_CONSUMED"
            or payload.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        )
        action = (port.CompletionAction.SERVER_CONSUME
                  if product is None or product.consumable else port.CompletionAction.SERVER_ACKNOWLEDGE)
        purchased_at = _rfc3339(payload.get("purchaseCompletionTime")) if state in (
            port.PurchaseState.PURCHASED, port.PurchaseState.REFUNDED) else None
        return port.TransactionObservation(
            rail=self.rail,
            environment=self.environment,
            transaction_ref=token,
            product_id=product_id,
            quantity=quantity,
            state=state,
            account_binding=binding,
            completion_action=action,
            purchased_at=purchased_at,
            refunded_at=None,
            completed=completed,
            account_ref=account_ref if isinstance(account_ref, str) else None,
        )

    def _require_purchase_environment(self, payload: Mapping[str, Any]) -> None:
        is_test = isinstance(payload.get("testPurchaseContext"), Mapping)
        if self.profile.mode is ProviderMode.SANDBOX and not is_test:
            raise InvalidInput("google_purchase_not_test")
        if self.profile.mode is ProviderMode.LIVE and is_test:
            raise InvalidInput("google_purchase_test_in_live")

    def _verify_pubsub(self, headers: Mapping[str, str]) -> None:
        raw = _header(headers, "authorization")
        if not raw or not raw.lower().startswith("bearer "):
            raise Unauthenticated("google_pubsub_auth_missing")
        token = raw.split(" ", 1)[1]
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise Unauthenticated("google_pubsub_token_invalid") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str):
            raise Unauthenticated("google_pubsub_token_invalid")
        key = self._pubsub_key(kid)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._pubsub_audience,
                options={"verify_exp": False, "verify_iat": False},
            )
        except jwt.InvalidTokenError:
            raise Unauthenticated("google_pubsub_token_invalid") from None
        if claims.get("iss") not in PUBSUB_ISSUERS or claims.get("email") != self._pubsub_email:
            raise Unauthenticated("google_pubsub_identity_mismatch")
        if claims.get("email_verified") is not True:
            raise Unauthenticated("google_pubsub_identity_mismatch")
        now = self._clock.now()
        exp = _jwt_time(claims.get("exp"))
        iat = _jwt_time(claims.get("iat"))
        if exp is None or now >= exp or iat is None or iat > now + timedelta(seconds=30):
            raise Unauthenticated("google_pubsub_token_expired")

    def _pubsub_key(self, kid: str) -> jwt.PyJWK:
        if kid not in self._pubsub_keys:
            source = self._jwks_source or self._fetch_jwks
            try:
                document = source()
            except Exception:
                raise TransientUnavailable("google_pubsub_keys_unavailable") from None
            keys: dict[str, jwt.PyJWK] = {}
            for raw in document.get("keys", []) if isinstance(document, Mapping) else []:
                if not isinstance(raw, Mapping) or raw.get("kid") is None:
                    continue
                try:
                    key = jwt.PyJWK(dict(raw))
                except jwt.PyJWKError:
                    continue
                if key.algorithm_name == "RS256":
                    keys[str(raw["kid"])] = key
            self._pubsub_keys = keys
        key = self._pubsub_keys.get(kid)
        if key is None:
            raise Unauthenticated("google_pubsub_signing_key_unknown")
        return key

    def _fetch_jwks(self) -> Mapping[str, Any]:
        response = self._client.get(self._jwks_url, timeout=self._timeout_s)
        if response.status_code != 200:
            raise TransientUnavailable("google_pubsub_keys_unavailable")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise TransientUnavailable("google_pubsub_keys_unavailable")
        return payload

    def _access(self, ctx: CallContext) -> str:
        if self._access_token is not None and self._access_token_expiry is not None:
            if self._clock.now() + timedelta(seconds=30) < self._access_token_expiry:
                return self._access_token
        now = int(self._clock.now().timestamp())
        assertion = jwt.encode(
            {
                "iss": self._service_account["client_email"],
                "scope": ANDROID_PUBLISHER_SCOPE,
                "aud": self._token_url,
                "iat": now,
                "exp": now + 3600,
            },
            self._service_account["private_key"],
            algorithm="RS256",
            headers={"kid": self._service_account["private_key_id"], "typ": "JWT"},
        )
        response = self._raw_request(
            "POST",
            self._token_url,
            ctx,
            content=urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = self._json(response)
        token = payload.get("access_token")
        expires = payload.get("expires_in", 3600)
        if not isinstance(token, str) or not token or type(expires) is not int or expires <= 0:
            raise PermanentFailure("google_oauth_response_invalid")
        self._access_token = token
        self._access_token_expiry = self._clock.now() + timedelta(seconds=min(expires, 3600))
        return token

    def _api_json(self, method: str, path: str, ctx: CallContext, **kwargs) -> Mapping[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._access(ctx)}"
        response = self._raw_request(method, path, ctx, headers=headers, **kwargs)
        return self._json(response)

    def _api_empty(self, method: str, path: str, ctx: CallContext) -> None:
        response = self._raw_request(
            method, path, ctx, headers={"Authorization": f"Bearer {self._access(ctx)}"}
        )
        if response.status_code in (200, 204):
            return
        self._json(response)

    def _raw_request(self, method: str, path: str, ctx: CallContext, **kwargs) -> httpx.Response:
        self._check_context(ctx)
        budget = max(0.1, min(self._timeout_s, ctx.remaining(self._clock) / timedelta(seconds=1)))
        try:
            return self._client.request(method, path, timeout=httpx.Timeout(budget, connect=min(5.0, budget)), **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TransientUnavailable("provider_unreachable") from None
        except (httpx.TimeoutException, httpx.TransportError):
            raise TransientUnavailable("provider_unavailable") from None

    @staticmethod
    def _json(response: httpx.Response) -> Mapping[str, Any]:
        if response.status_code == 429:
            raise RateLimited("provider_rate_limited")
        if response.status_code in (500, 502, 503, 504):
            raise TransientUnavailable("provider_unavailable")
        if response.status_code in (401, 403):
            raise PermanentFailure("provider_credentials_rejected")
        if response.status_code == 404:
            raise NotFound("provider_object_not_found")
        if not 200 <= response.status_code < 300:
            raise PermanentFailure("provider_rejected_request", detail=str(response.status_code))
        try:
            payload = response.json()
        except ValueError:
            raise TransientUnavailable("provider_response_unreadable") from None
        if not isinstance(payload, Mapping):
            raise PermanentFailure("provider_response_unreadable")
        return payload

    def _check_context(self, ctx: CallContext) -> None:
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)


def _purchase_token(value: Any) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InvalidInput("google_purchase_token_invalid")
    return value


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value
    return None


def _millis(value: Any, code: str) -> datetime:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or value < 0:
        raise InvalidInput(code)
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise InvalidInput(code) from None


def _rfc3339(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _jwt_time(value: Any) -> datetime | None:
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


__all__ = ["GooglePlayPaymentProvider"]
