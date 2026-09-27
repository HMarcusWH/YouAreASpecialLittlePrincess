"""PaymentProvider and NativePurchaseClient ports (docs/connectors/payments.md).

Adapters return normalized *observations* of provider state. An observation
is never a grant: the application ledger (T19) decides grants atomically and
idempotently from authoritative observations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol, Sequence

from .base import CallContext, CapabilityProfile, Environment, InvalidInput, require_opaque_id, require_utc

PORT = "PaymentProvider"
NATIVE_PORT = "NativePurchaseClient"

# Capability names.
WEB_CHECKOUT = "web_checkout"
VERIFY_PROOF = "verify_proof"
SIGNED_EVENTS = "signed_events"
AUTHORITATIVE_LOOKUP = "authoritative_lookup"
SERVER_CONSUME = "server_consume"
SERVER_ACKNOWLEDGE = "server_acknowledge"
REFUND_REQUEST = "refund_request"
RECONCILE = "reconcile"


class PaymentRail(str, Enum):
    STRIPE = "stripe"
    APPLE_APP_STORE = "apple_app_store"
    GOOGLE_PLAY = "google_play"


class PurchaseState(str, Enum):
    PENDING = "PENDING"
    PURCHASED = "PURCHASED"
    REFUNDED = "REFUNDED"
    REVOKED = "REVOKED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class AccountBinding(str, Enum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    UNKNOWN = "UNKNOWN"


class CompletionAction(str, Enum):
    SERVER_CONSUME = "SERVER_CONSUME"          # Google consumable
    SERVER_ACKNOWLEDGE = "SERVER_ACKNOWLEDGE"  # Google non-consumable
    CLIENT_FINISH = "CLIENT_FINISH"            # Apple: client finishes after server grant
    NONE = "NONE"                              # Stripe: nothing to complete


@dataclass(frozen=True)
class TransactionObservation:
    """Normalized provider state for one financial transaction.

    ``transaction_ref`` is the provider's stable dedupe identity (Stripe payment
    intent, Apple transaction ID, Google purchase token), stored privately.
    """

    rail: PaymentRail
    environment: Environment
    transaction_ref: str
    product_id: str
    quantity: int
    state: PurchaseState
    account_binding: AccountBinding
    completion_action: CompletionAction
    purchased_at: datetime | None = None
    refunded_at: datetime | None = None
    original_transaction_ref: str | None = None
    completed: bool | None = None  # consumed/acknowledged/finished, None when unknown

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_ref, str) or not 0 < len(self.transaction_ref) <= 512:
            raise InvalidInput("invalid_transaction_ref")
        require_opaque_id(self.product_id, "product_id")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 100:
            raise InvalidInput("invalid_quantity")
        for name in ("purchased_at", "refunded_at"):
            value = getattr(self, name)
            if value is not None:
                require_utc(value, name)

    def __repr__(self) -> str:
        return (f"TransactionObservation(rail={self.rail.value}, state={self.state.value}, "
                f"product_id={self.product_id!r})")


@dataclass(frozen=True)
class NormalizedEvent:
    """A verified provider notification. Delivery can be duplicated, reordered or
    missing; the event names transactions to reconcile, it is not a command."""

    rail: PaymentRail
    environment: Environment
    event_id: str
    event_type: str
    transaction_refs: tuple[str, ...]
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class CheckoutSession:
    provider_session_ref: str
    redirect_url: str
    expires_at: datetime

    def __repr__(self) -> str:
        return "CheckoutSession(<redacted>)"


@dataclass(frozen=True)
class CatalogProduct:
    product_id: str
    rail: PaymentRail
    store_product_id: str
    credits: int
    consumable: bool = True


class PaymentProvider(Protocol):
    profile: CapabilityProfile
    rail: PaymentRail

    def create_web_checkout(self, intent_ref: str, product: CatalogProduct, account_ref: str,
                            ctx: CallContext) -> CheckoutSession: ...

    def verify_purchase(self, proof: str, expected_account_ref: str,
                        ctx: CallContext) -> TransactionObservation:
        """Verify a client-submitted store proof server-side."""
        ...

    def verify_and_normalize_event(self, raw_body: bytes, headers: Mapping[str, str],
                                   ctx: CallContext) -> NormalizedEvent:
        """Verify the signature over the unmodified raw body before parsing."""
        ...

    def retrieve_authoritative_purchase(self, transaction_ref: str, expected_account_ref: str,
                                        ctx: CallContext) -> TransactionObservation: ...

    def complete_store_purchase(self, transaction_ref: str, action: CompletionAction,
                                ctx: CallContext) -> None:
        """Server-side consume/acknowledge after the durable grant."""
        ...

    def request_refund_if_supported(self, transaction_ref: str, ctx: CallContext) -> None: ...

    def reconcile(self, since: datetime, ctx: CallContext) -> Sequence[TransactionObservation]: ...


@dataclass(frozen=True)
class StoreProof:
    """What a native client hands to the API after a store purchase."""

    rail: PaymentRail
    proof: str
    store_product_id: str
    pending: bool = False

    def __repr__(self) -> str:
        return f"StoreProof(rail={self.rail.value}, store_product_id={self.store_product_id!r})"


@dataclass(frozen=True)
class StoreListing:
    store_product_id: str
    display_price: str
    available: bool = True


@dataclass(frozen=True)
class NativePurchaseOutcome:
    state: str  # PURCHASED | PENDING | CANCELLED | FAILED
    proof: StoreProof | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)


class NativePurchaseClient(Protocol):
    """Client-side store surface (implemented in apps/mobile for T30/T31).

    It returns store proofs to the application API. It never grants credits,
    accepts an arbitrary price or holds a server verification secret.
    """

    def list_products(self, store_product_ids: Sequence[str]) -> Sequence[StoreListing]: ...

    def begin_purchase(self, store_product_id: str, account_token: str) -> NativePurchaseOutcome: ...

    def recover_pending_transactions(self) -> Sequence[StoreProof]: ...

    def finish_after_server_grant(self, proof: StoreProof) -> None: ...
