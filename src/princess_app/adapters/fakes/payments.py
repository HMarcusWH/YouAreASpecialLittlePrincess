"""Fake payment rails (Stripe-like web, Apple-like, Google-like) and a fake
native store client.

The fake keeps its own authoritative "provider world" so tests can create
pending purchases, refunds, duplicated/reordered signed events and
timeouts after acceptance. It only reports observations; it never grants.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping, Sequence

from ...ports import payments as port
from ...ports.base import (
    CallContext,
    Conflict,
    Environment,
    InvalidInput,
    NotFound,
    Unauthenticated,
    Unsupported,
)
from .base import FakeAdapter, SequentialIds

_DEFAULT_CAPS = {
    port.PaymentRail.STRIPE: frozenset({port.WEB_CHECKOUT, port.SIGNED_EVENTS, port.AUTHORITATIVE_LOOKUP,
                                        port.REFUND_REQUEST, port.RECONCILE}),
    port.PaymentRail.APPLE_APP_STORE: frozenset({port.VERIFY_PROOF, port.SIGNED_EVENTS,
                                                 port.AUTHORITATIVE_LOOKUP, port.RECONCILE}),
    port.PaymentRail.GOOGLE_PLAY: frozenset({port.VERIFY_PROOF, port.SIGNED_EVENTS, port.AUTHORITATIVE_LOOKUP,
                                             port.SERVER_CONSUME, port.SERVER_ACKNOWLEDGE, port.RECONCILE}),
}
_COMPLETION = {
    port.PaymentRail.STRIPE: port.CompletionAction.NONE,
    port.PaymentRail.APPLE_APP_STORE: port.CompletionAction.CLIENT_FINISH,
    port.PaymentRail.GOOGLE_PLAY: port.CompletionAction.SERVER_CONSUME,
}
EVENT_TOLERANCE_S = 300


@dataclass
class _Txn:
    ref: str
    store_product_id: str
    account_ref: str
    environment: Environment
    state: port.PurchaseState
    quantity: int
    updated_at: datetime
    purchased_at: datetime | None = None
    refunded_at: datetime | None = None
    completed: bool = False
    session_ref: str | None = None


class FakePaymentProvider(FakeAdapter):
    port_name = port.PORT

    def __init__(self, rail: port.PaymentRail, *, catalog: Sequence[port.CatalogProduct] = (),
                 webhook_secret: bytes = b"fake-webhook-secret", **kwargs) -> None:
        self.rail = rail
        self.provider = f"fake-{rail.value}"
        self.default_capabilities = _DEFAULT_CAPS[rail]
        super().__init__(**kwargs)
        self._secret = webhook_secret
        self._ids = SequentialIds()
        self._txns: dict[str, _Txn] = {}
        self._sessions: dict[str, str] = {}
        self._intents: dict[str, tuple[port.CheckoutSession, tuple[str, str]]] = {}
        self._products = {p.store_product_id: p for p in catalog if p.rail is rail}

    # --- simulated provider world ----------------------------------------
    def simulate_purchase(self, account_ref: str, store_product_id: str, *, pending: bool = False,
                          environment: Environment | None = None, quantity: int = 1) -> str:
        """A store purchase happened; returns the proof the client would receive."""
        ref = self._ids.new_id("txn" if self.rail is not port.PaymentRail.GOOGLE_PLAY else "ptok")
        now = self.clock.now()
        state = port.PurchaseState.PENDING if pending else port.PurchaseState.PURCHASED
        self._txns[ref] = _Txn(ref, store_product_id, account_ref, environment or self.environment, state,
                               quantity, now, None if pending else now)
        return self._proof_for(ref)

    def simulate_checkout_paid(self, session_ref: str) -> str:
        ref = self._sessions.get(session_ref)
        if ref is None:
            raise NotFound("session_not_found")
        txn = self._txns[ref]
        txn.state, txn.purchased_at, txn.updated_at = port.PurchaseState.PURCHASED, self.clock.now(), self.clock.now()
        return ref

    def simulate_settle_pending(self, ref: str, *, success: bool = True) -> None:
        txn = self._txns[ref]
        txn.state = port.PurchaseState.PURCHASED if success else port.PurchaseState.CANCELLED
        txn.purchased_at = self.clock.now() if success else None
        txn.updated_at = self.clock.now()

    def simulate_refund(self, ref: str) -> None:
        txn = self._txns[ref]
        txn.state, txn.refunded_at, txn.updated_at = port.PurchaseState.REFUNDED, self.clock.now(), self.clock.now()

    def signed_event(self, event_type: str, refs: Sequence[str], *, event_id: str | None = None,
                     environment: Environment | None = None, signed_at: datetime | None = None,
                     secret: bytes | None = None) -> tuple[bytes, dict[str, str]]:
        body = json.dumps({"id": event_id or self._ids.new_id("evt"), "type": event_type,
                           "environment": (environment or self.environment).value,
                           "transactions": list(refs)}, sort_keys=True).encode()
        ts = str(int((signed_at or self.clock.now()).timestamp()))
        mac = hmac.new(secret or self._secret, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        return body, {"x-fake-signature": f"t={ts},v1={mac}"}

    def transaction_ref_from_proof(self, proof: str) -> str:
        return self._parse_proof(proof)

    # --- port -----------------------------------------------------------
    def create_web_checkout(self, intent_ref: str, product: port.CatalogProduct, account_ref: str,
                            ctx: CallContext) -> port.CheckoutSession:
        self.profile.require(port.WEB_CHECKOUT)
        if product.rail is not self.rail:
            raise InvalidInput("product_not_on_rail")

        def effect() -> port.CheckoutSession:
            existing = self._intents.get(intent_ref)
            if existing is not None:
                session, bound = existing
                if bound != (account_ref, product.product_id):
                    raise Conflict("intent_reused_for_different_request")
                return session  # same intent (retry/double click) -> same chargeable session
            session_ref = self._ids.new_id("cs")
            ref = self._ids.new_id("pi")
            now = self.clock.now()
            self._txns[ref] = _Txn(ref, product.store_product_id, account_ref, self.environment,
                                   port.PurchaseState.PENDING, 1, now, session_ref=session_ref)
            self._sessions[session_ref] = ref
            session = port.CheckoutSession(session_ref, f"https://checkout.fake.invalid/{session_ref}",
                                           now + timedelta(minutes=30))
            self._intents[intent_ref] = (session, (account_ref, product.product_id))
            return session

        return self._run("create_web_checkout", ctx, effect)

    def verify_purchase(self, proof: str, expected_account_ref: str, ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.VERIFY_PROOF)
        return self._run("verify_purchase", ctx,
                         lambda: self._observe(self._txns[self._parse_proof(proof)], expected_account_ref))

    def verify_and_normalize_event(self, raw_body: bytes, headers: Mapping[str, str],
                                   ctx: CallContext) -> port.NormalizedEvent:
        self.profile.require(port.SIGNED_EVENTS)

        def effect() -> port.NormalizedEvent:
            header = headers.get("x-fake-signature", "")
            fields = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
            ts, mac = fields.get("t", ""), fields.get("v1", "")
            expected = hmac.new(self._secret, ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
            if not ts.isdigit() or not hmac.compare_digest(mac, expected):
                raise Unauthenticated("bad_signature")
            if abs(self.clock.now().timestamp() - int(ts)) > EVENT_TOLERANCE_S:
                raise Unauthenticated("stale_signature")
            try:
                payload = json.loads(raw_body)
            except ValueError:
                raise InvalidInput("malformed_event") from None
            refs = payload.get("transactions") if isinstance(payload, dict) else None
            if (not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r for r in refs)
                    or not isinstance(payload.get("id"), str) or not isinstance(payload.get("type"), str)
                    or not isinstance(payload.get("environment"), str)):
                raise InvalidInput("malformed_event")
            env = Environment.parse(payload["environment"])
            refs, event_id, event_type = tuple(refs), payload["id"], payload["type"]
            return port.NormalizedEvent(self.rail, env, event_id, event_type, refs, self.clock.now())

        return self._run("verify_and_normalize_event", ctx, effect)

    def retrieve_authoritative_purchase(self, transaction_ref: str, expected_account_ref: str,
                                        ctx: CallContext) -> port.TransactionObservation:
        self.profile.require(port.AUTHORITATIVE_LOOKUP)

        def effect() -> port.TransactionObservation:
            txn = self._txns.get(transaction_ref)
            if txn is None:
                raise NotFound("transaction_not_found")
            return self._observe(txn, expected_account_ref)

        return self._run("retrieve_authoritative_purchase", ctx, effect)

    def complete_store_purchase(self, transaction_ref: str, action: port.CompletionAction,
                                ctx: CallContext) -> None:
        if action is port.CompletionAction.SERVER_CONSUME:
            self.profile.require(port.SERVER_CONSUME)
        elif action is port.CompletionAction.SERVER_ACKNOWLEDGE:
            self.profile.require(port.SERVER_ACKNOWLEDGE)
        else:
            raise Unsupported("not_a_server_completion", detail=action.value)

        def effect() -> None:
            txn = self._txns.get(transaction_ref)
            if txn is None:
                raise NotFound("transaction_not_found")
            if txn.state is not port.PurchaseState.PURCHASED:
                raise Conflict("not_purchased")
            txn.completed = True  # idempotent

        self._run("complete_store_purchase", ctx, effect)

    def request_refund_if_supported(self, transaction_ref: str, ctx: CallContext) -> None:
        self.profile.require(port.REFUND_REQUEST)

        def effect() -> None:
            if transaction_ref not in self._txns:
                raise NotFound("transaction_not_found")
            self.simulate_refund(transaction_ref)

        self._run("request_refund_if_supported", ctx, effect)

    def reconcile(self, since: datetime, ctx: CallContext) -> Sequence[port.TransactionObservation]:
        self.profile.require(port.RECONCILE)
        return self._run("reconcile", ctx, lambda: [
            self._observe(t, t.account_ref) for t in sorted(self._txns.values(), key=lambda t: t.ref)
            if t.updated_at >= since])

    # --- internals --------------------------------------------------------
    def _proof_for(self, ref: str) -> str:
        mac = hmac.new(self._secret, b"proof:" + ref.encode(), hashlib.sha256).hexdigest()[:24]
        return f"fakeproof.{ref}.{mac}"

    def _parse_proof(self, proof: str) -> str:
        parts = proof.split(".") if isinstance(proof, str) else []
        if len(parts) != 3 or parts[0] != "fakeproof" or parts[1] not in self._txns:
            raise Unauthenticated("invalid_proof")
        if not hmac.compare_digest(self._proof_for(parts[1]), proof):
            raise Unauthenticated("invalid_proof")
        return parts[1]

    def _observe(self, txn: _Txn, expected_account_ref: str) -> port.TransactionObservation:
        product = self._products.get(txn.store_product_id)
        binding = (port.AccountBinding.MATCHED if txn.account_ref == expected_account_ref
                   else port.AccountBinding.MISMATCHED)
        action = _COMPLETION[self.rail]
        if action is port.CompletionAction.SERVER_CONSUME and product is not None and not product.consumable:
            action = port.CompletionAction.SERVER_ACKNOWLEDGE
        return port.TransactionObservation(
            rail=self.rail, environment=txn.environment, transaction_ref=txn.ref,
            product_id=product.product_id if product else "unknown_product", quantity=txn.quantity,
            state=txn.state, account_binding=binding, completion_action=action,
            purchased_at=txn.purchased_at, refunded_at=txn.refunded_at, completed=txn.completed,
            account_ref=txn.account_ref)


class FakeNativePurchaseClient:
    """Simulates a native store client on top of a fake Apple/Google rail."""

    def __init__(self, provider: FakePaymentProvider, account_ref: str) -> None:
        if provider.rail is port.PaymentRail.STRIPE:
            raise InvalidInput("native_client_needs_store_rail")
        self.provider = provider
        self.account_ref = account_ref
        self.unfinished: dict[str, port.StoreProof] = {}
        self.finished: set[str] = set()
        self._listeners: list[Callable[[port.StoreProof], None]] = []

    def observe_transaction_updates(self, listener: Callable[[port.StoreProof], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def settle_pending(self, proof: port.StoreProof, *, success: bool = True) -> None:
        """The store completes a pending purchase later; listeners get the update."""
        self.provider.simulate_settle_pending(self.provider.transaction_ref_from_proof(proof.proof), success=success)
        updated = port.StoreProof(proof.rail, proof.proof, proof.store_product_id, pending=False)
        self.unfinished[proof.proof] = updated
        for listener in list(self._listeners):
            listener(updated)

    def list_products(self, store_product_ids: Sequence[str]) -> Sequence[port.StoreListing]:
        return [port.StoreListing(pid, "9.99 SEK", pid in self.provider._products) for pid in store_product_ids]

    def begin_purchase(self, store_product_id: str, account_token: str,
                       *, pending: bool = False, cancel: bool = False) -> port.NativePurchaseOutcome:
        if cancel:
            return port.NativePurchaseOutcome("CANCELLED")
        proof = port.StoreProof(self.provider.rail,
                                self.provider.simulate_purchase(self.account_ref, store_product_id, pending=pending),
                                store_product_id, pending=pending)
        self.unfinished[proof.proof] = proof
        return port.NativePurchaseOutcome("PENDING" if pending else "PURCHASED", proof)

    def recover_pending_transactions(self) -> Sequence[port.StoreProof]:
        return list(self.unfinished.values())

    def finish_after_server_grant(self, proof: port.StoreProof) -> None:
        self.unfinished.pop(proof.proof, None)
        self.finished.add(proof.proof)
        if self.provider.rail is port.PaymentRail.APPLE_APP_STORE:
            self.provider._txns[self.provider.transaction_ref_from_proof(proof.proof)].completed = True
