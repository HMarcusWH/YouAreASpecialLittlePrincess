"""Apple App Store server verification adapter (T19), production-disabled.

Verifies StoreKit/App Store JWS material against a configured Apple trust
anchor set, binds bundle/product/environment/appAccountToken, and uses Get
Transaction Info for authoritative state. It never grants credits itself.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

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

PRODUCTION_BASE_URL = "https://api.storekit.apple.com"
SANDBOX_BASE_URL = "https://api.storekit-sandbox.apple.com"
AUDIENCE = "appstoreconnect-v1"
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


class AppleAppStorePaymentProvider:
    port_name = port.PORT
    rail = port.PaymentRail.APPLE_APP_STORE

    def __init__(
        self,
        *,
        bundle_id: str,
        issuer_id: str,
        key_id: str,
        private_key_pem: str | bytes,
        trusted_root_certificates: Sequence[str | bytes],
        catalog: Sequence[port.CatalogProduct],
        clock: Clock,
        environment: Environment,
        mode: ProviderMode,
        activation_approved: bool = False,
        base_url: str | None = None,
        timeout_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if mode is ProviderMode.FAKE:
            raise InvalidInput("real_adapter_cannot_be_fake")
        if not activation_approved:
            raise Unsupported("payment_provider_activation_not_approved")
        if not all(isinstance(v, str) and v for v in (bundle_id, issuer_id, key_id)):
            raise InvalidInput("apple_adapter_misconfigured")
        if not private_key_pem or not trusted_root_certificates:
            raise InvalidInput("apple_adapter_misconfigured")
        self.bundle_id = bundle_id
        self._issuer_id = issuer_id
        self._key_id = key_id
        self._private_key_pem = private_key_pem
        self._clock = clock
        self._timeout_s = float(timeout_s)
        self._roots = tuple(_load_certificate(value) for value in trusted_root_certificates)
        if not self._roots:
            raise InvalidInput("apple_trust_roots_empty")
        apple_catalog = [p for p in catalog if p.rail is self.rail]
        if not apple_catalog:
            raise InvalidInput("apple_catalog_empty")
        self._products = {p.store_product_id: p for p in apple_catalog}
        self._mode = mode
        default_base = PRODUCTION_BASE_URL if mode is ProviderMode.LIVE else SANDBOX_BASE_URL
        target = (base_url or default_base).rstrip("/")
        if not target.startswith("https://") and transport is None:
            raise InvalidInput("provider_base_url_must_be_https")
        self._client = httpx.Client(base_url=target, transport=transport, follow_redirects=False)
        self.profile = CapabilityProfile(
            port=port.PORT,
            provider="apple-app-store-server",
            mode=mode,
            capabilities=frozenset({
                port.VERIFY_PROOF, port.SIGNED_EVENTS, port.AUTHORITATIVE_LOOKUP, port.RECONCILE,
            }),
        )

    def __repr__(self) -> str:
        return f"AppleAppStorePaymentProvider(mode={self.profile.mode.value}, environment={self.environment.value})"

    def create_web_checkout(self, intent_ref: str, product: port.CatalogProduct, account_ref: str,
                            ctx: CallContext) -> port.CheckoutSession:
        raise Unsupported("capability_not_supported", detail="apple:web_checkout")

    def verify_purchase(self, proof: str, expected_account_ref: str,
                        ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.VERIFY_PROOF)
        self._check_context(ctx)
        payload = self._verify_jws(proof)
        return self._observation(payload, expected_account_ref)

    def verify_and_normalize_event(self, raw_body: bytes, headers: Mapping[str, str],
                                   ctx: CallContext) -> port.NormalizedEvent:
        self.profile.require(port.SIGNED_EVENTS)
        self._check_context(ctx)
        try:
            envelope = json.loads(raw_body)
        except (UnicodeDecodeError, ValueError):
            raise InvalidInput("apple_notification_malformed") from None
        if not isinstance(envelope, Mapping) or not isinstance(envelope.get("signedPayload"), str):
            raise InvalidInput("apple_notification_malformed")
        payload = self._verify_jws(envelope["signedPayload"])
        event_id = _provider_id(payload.get("notificationUUID"), "apple_notification_malformed")
        event_type = payload.get("notificationType")
        if not isinstance(event_type, str) or not event_type or len(event_type) > 128:
            raise InvalidInput("apple_notification_malformed")
        signed_date = _millis(payload.get("signedDate"), "apple_notification_malformed")
        data = payload.get("data")
        refs: tuple[str, ...] = ()
        if isinstance(data, Mapping):
            if data.get("bundleId") not in (None, self.bundle_id):
                raise InvalidInput("apple_bundle_mismatch")
            self._require_provider_environment(data.get("environment"))
            nested = data.get("signedTransactionInfo")
            if nested is not None:
                if not isinstance(nested, str):
                    raise InvalidInput("apple_notification_malformed")
                txn = self._verify_jws(nested)
                self._validate_transaction_identity(txn)
                refs = (_provider_id(txn.get("transactionId"), "apple_transaction_invalid"),)
        return port.NormalizedEvent(
            rail=self.rail,
            environment=self.environment,
            event_id=event_id,
            event_type=event_type,
            transaction_refs=refs,
            occurred_at=signed_date,
        )

    def retrieve_authoritative_purchase(self, transaction_ref: str, expected_account_ref: str,
                                        ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.AUTHORITATIVE_LOOKUP)
        self._check_context(ctx)
        ref = _provider_id(transaction_ref, "apple_transaction_invalid")
        response = self._request("GET", f"/inApps/v1/transactions/{quote(ref, safe='')}", ctx)
        payload = self._json(response)
        signed = payload.get("signedTransactionInfo")
        if not isinstance(signed, str):
            raise PermanentFailure("apple_transaction_response_invalid")
        txn = self._verify_jws(signed)
        if txn.get("transactionId") != ref:
            raise PermanentFailure("apple_transaction_response_invalid")
        return self._observation(txn, expected_account_ref)

    def complete_store_purchase(self, transaction_ref: str, action: port.CompletionAction,
                                ctx: CallContext) -> None:
        raise Unsupported("not_a_server_completion", detail=action.value)

    def request_refund_if_supported(self, transaction_ref: str, ctx: CallContext) -> None:
        raise Unsupported("capability_not_supported", detail="apple:refund_request")

    def reconcile(self, since: datetime, ctx: CallContext) -> Sequence[port.TransactionObservation]:
        self.profile.require(port.RECONCILE)
        self._check_context(ctx)
        require_utc(since, "since")
        now = self._clock.now()
        if since >= now:
            return ()
        max_age = timedelta(days=180 if self.profile.mode is ProviderMode.LIVE else 30)
        if now - since > max_age:
            raise InvalidInput("apple_reconcile_window_exceeded")
        body = {
            "startDate": int(since.timestamp() * 1000),
            "endDate": int(now.timestamp() * 1000),
            "onlyFailures": False,
        }
        refs: list[str] = []
        seen: set[str] = set()
        token: str | None = None
        for _ in range(25):
            response = self._request(
                "POST",
                "/inApps/v1/notifications/history",
                ctx,
                json=body,
                params={"paginationToken": token} if token else None,
            )
            payload = self._json(response)
            history = payload.get("notificationHistory")
            if not isinstance(history, list):
                raise PermanentFailure("apple_history_response_invalid")
            for item in history:
                if not isinstance(item, Mapping) or not isinstance(item.get("signedPayload"), str):
                    raise PermanentFailure("apple_history_response_invalid")
                outer = self._verify_jws(item["signedPayload"])
                data = outer.get("data")
                nested = data.get("signedTransactionInfo") if isinstance(data, Mapping) else None
                if nested is None:
                    continue
                if not isinstance(nested, str):
                    raise PermanentFailure("apple_history_response_invalid")
                txn = self._verify_jws(nested)
                self._validate_transaction_identity(txn)
                ref = _provider_id(txn.get("transactionId"), "apple_transaction_invalid")
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
                    if len(refs) > 500:
                        raise PermanentFailure("apple_reconcile_ref_limit")
            if payload.get("hasMore") is not True:
                return tuple(self.retrieve_authoritative_purchase(ref, "", ctx) for ref in refs)
            token = payload.get("paginationToken")
            if not isinstance(token, str) or not token:
                raise PermanentFailure("apple_history_response_invalid")
        raise PermanentFailure("apple_reconcile_page_limit")

    def close(self) -> None:
        self._client.close()

    def _observation(self, payload: Mapping[str, Any], expected_account_ref: str) -> port.TransactionObservation:
        self._validate_transaction_identity(payload)
        ref = _provider_id(payload.get("transactionId"), "apple_transaction_invalid")
        original = payload.get("originalTransactionId")
        original_ref = _provider_id(original, "apple_transaction_invalid") if original is not None else None
        store_product = payload.get("productId")
        product = self._products.get(store_product) if isinstance(store_product, str) else None
        product_id = product.product_id if product is not None else "unknown_product"
        quantity = payload.get("quantity", 1)
        if type(quantity) is not int or not 1 <= quantity <= 100:
            raise InvalidInput("apple_transaction_invalid")
        account_ref = payload.get("appAccountToken")
        if account_ref is None:
            binding = port.AccountBinding.UNKNOWN
        elif isinstance(account_ref, str):
            require_opaque_id(account_ref, "account_ref")
            binding = (port.AccountBinding.MATCHED if expected_account_ref and account_ref == expected_account_ref
                       else port.AccountBinding.MISMATCHED if expected_account_ref else port.AccountBinding.UNKNOWN)
        else:
            raise InvalidInput("apple_transaction_invalid")
        purchased_at = _millis(payload.get("purchaseDate"), "apple_transaction_invalid")
        revoked_raw = payload.get("revocationDate")
        refunded_at = _millis(revoked_raw, "apple_transaction_invalid") if revoked_raw is not None else None
        state = port.PurchaseState.REVOKED if refunded_at is not None else port.PurchaseState.PURCHASED
        return port.TransactionObservation(
            rail=self.rail,
            environment=self.environment,
            transaction_ref=ref,
            product_id=product_id,
            quantity=quantity,
            state=state,
            account_binding=binding,
            completion_action=port.CompletionAction.CLIENT_FINISH,
            purchased_at=purchased_at,
            refunded_at=refunded_at,
            original_transaction_ref=original_ref,
            completed=None,
            account_ref=account_ref if isinstance(account_ref, str) else None,
        )

    def _validate_transaction_identity(self, payload: Mapping[str, Any]) -> None:
        if payload.get("bundleId") != self.bundle_id:
            raise InvalidInput("apple_bundle_mismatch")
        self._require_provider_environment(payload.get("environment"))
        _provider_id(payload.get("transactionId"), "apple_transaction_invalid")

    def _require_provider_environment(self, value: Any) -> None:
        expected = "Production" if self.profile.mode is ProviderMode.LIVE else "Sandbox"
        if value != expected:
            raise InvalidInput("apple_environment_mismatch")

    def _verify_jws(self, compact: str) -> Mapping[str, Any]:
        if not isinstance(compact, str) or compact.count(".") != 2:
            raise Unauthenticated("apple_jws_malformed")
        try:
            header = jwt.get_unverified_header(compact)
        except jwt.InvalidTokenError:
            raise Unauthenticated("apple_jws_malformed") from None
        if header.get("alg") != "ES256":
            raise Unauthenticated("apple_jws_algorithm")
        chain = header.get("x5c")
        if not isinstance(chain, list) or not chain or not all(isinstance(item, str) for item in chain):
            raise Unauthenticated("apple_jws_certificate_chain")
        try:
            certs = tuple(x509.load_der_x509_certificate(base64.b64decode(item, validate=True)) for item in chain)
        except (ValueError, TypeError):
            raise Unauthenticated("apple_jws_certificate_chain") from None
        self._verify_chain(certs)
        try:
            payload = jwt.decode(
                compact,
                certs[0].public_key(),
                algorithms=["ES256"],
                options={"verify_aud": False, "verify_exp": False, "verify_iat": False, "verify_nbf": False},
            )
        except jwt.InvalidTokenError:
            raise Unauthenticated("apple_jws_signature") from None
        if not isinstance(payload, Mapping):
            raise Unauthenticated("apple_jws_payload")
        return payload

    def _verify_chain(self, certs: Sequence[x509.Certificate]) -> None:
        now = self._clock.now()
        for cert in certs:
            if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
                raise Unauthenticated("apple_certificate_expired")
        try:
            leaf_constraints = certs[0].extensions.get_extension_for_class(x509.BasicConstraints).value
            if leaf_constraints.ca:
                raise Unauthenticated("apple_leaf_is_ca")
        except x509.ExtensionNotFound:
            pass
        for child, issuer in zip(certs, certs[1:]):
            _verify_issued_by(child, issuer)
        tail = certs[-1]
        for root in self._roots:
            if tail.fingerprint(hashes.SHA256()) == root.fingerprint(hashes.SHA256()):
                return
            try:
                _verify_issued_by(tail, root)
                return
            except Unauthenticated:
                continue
        raise Unauthenticated("apple_untrusted_chain")

    def _server_token(self) -> str:
        now = int(self._clock.now().timestamp())
        try:
            return jwt.encode(
                {"iss": self._issuer_id, "iat": now, "exp": now + 300, "aud": AUDIENCE, "bid": self.bundle_id},
                self._private_key_pem,
                algorithm="ES256",
                headers={"kid": self._key_id, "typ": "JWT"},
            )
        except Exception:
            raise PermanentFailure("apple_server_key_invalid") from None

    def _check_context(self, ctx: CallContext) -> None:
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)

    def _request(self, method: str, path: str, ctx: CallContext, **kwargs) -> httpx.Response:
        self._check_context(ctx)
        budget = max(0.1, min(self._timeout_s, ctx.remaining(self._clock) / timedelta(seconds=1)))
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._server_token()}"
        try:
            return self._client.request(
                method,
                path,
                headers=headers,
                timeout=httpx.Timeout(budget, connect=min(5.0, budget)),
                **kwargs,
            )
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


def _load_certificate(value: str | bytes) -> x509.Certificate:
    raw = value.encode() if isinstance(value, str) else value
    try:
        if b"-----BEGIN CERTIFICATE-----" in raw:
            return x509.load_pem_x509_certificate(raw)
        return x509.load_der_x509_certificate(raw)
    except ValueError:
        raise InvalidInput("apple_trust_root_invalid") from None


def _verify_issued_by(child: x509.Certificate, issuer: x509.Certificate) -> None:
    if child.issuer != issuer.subject:
        raise Unauthenticated("apple_certificate_chain")
    public_key = issuer.public_key()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(child.signature, child.tbs_certificate_bytes, padding.PKCS1v15(),
                              child.signature_hash_algorithm)
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(child.signature, child.tbs_certificate_bytes,
                              ec.ECDSA(child.signature_hash_algorithm))
        else:
            raise Unauthenticated("apple_certificate_key")
    except Unauthenticated:
        raise
    except Exception:
        raise Unauthenticated("apple_certificate_chain") from None


def _provider_id(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _PROVIDER_ID.fullmatch(value):
        raise InvalidInput(code)
    return value


def _millis(value: Any, code: str) -> datetime:
    if type(value) is not int or value < 0:
        raise InvalidInput(code)
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise InvalidInput(code) from None


__all__ = ["AppleAppStorePaymentProvider", "PRODUCTION_BASE_URL", "SANDBOX_BASE_URL"]
