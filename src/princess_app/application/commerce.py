"""One internal ledger for every payment rail, and metered Premium jobs (T19).

Flow (docs/roadmap/14-payments-entitlements-and-commerce.md):

1. A provider observation is verified server-side and assessed against the
   catalog, environment and attested account (``domain.commerce.assess``).
2. A grant inserts the unique financial transaction, the credit lot and the
   ledger entry in one transaction; a repeat of the same financial identity
   returns the existing grant. Completion (consume/acknowledge) follows the
   durable grant and is retried until confirmed; Apple finishes on the client.
3. A Premium request authorizes the report and third-party processing, then
   reserves one eligible credit and enqueues the job in one transaction keyed
   by the intended operation. Publication spends the reservation atomically;
   terminal failure releases it. Refunds are compensating entries.

Browser redirects, client flags and arrival order never grant anything.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Mapping, Protocol, Sequence

from ..domain import commerce as policy
from ..domain.commerce import GrantDecision, Platform
from ..domain.permissions import Scope
from ..ports.base import (
    CallContext,
    Clock,
    Environment,
    IdGenerator,
    InvalidInput,
    NotFound,
    PortError,
    Unsupported,
    require_opaque_id,
)
from ..ports.payments import (
    AccountBinding,
    CatalogProduct,
    CheckoutSession,
    CompletionAction,
    NormalizedEvent,
    PaymentProvider,
    PaymentRail,
    TransactionObservation,
)
from .permissions import PermissionService
from .premium.prompt import POLICY_ID
from .reports import ReportStore

AI_PURPOSE = "third_party_ai_processing"
SERVER_COMPLETIONS = (CompletionAction.SERVER_CONSUME, CompletionAction.SERVER_ACKNOWLEDGE)


@dataclass(frozen=True)
class GrantResult:
    txn_id: str
    lot_id: str | None
    created: bool
    completion_due: bool


@dataclass(frozen=True)
class Balance:
    available: int
    reserved: int


@dataclass(frozen=True)
class PremiumRequest:
    job_id: str
    reservation_id: str
    created: bool


@dataclass(frozen=True)
class PendingCompletion:
    txn_id: str
    rail: PaymentRail
    transaction_ref: str
    action: CompletionAction
    owner_id: str


class Ledger(Protocol):
    def account_ref(self, owner_id: str, at: datetime) -> str: ...

    def record_intent(self, owner_id: str, intent_ref: str, rail: PaymentRail, product_id: str,
                      at: datetime) -> None: ...

    def record_event(self, event: NormalizedEvent, body_sha256: str, at: datetime) -> bool:
        """Insert into the verified inbox; False if this event was already received."""
        ...

    def finish_event(self, event: NormalizedEvent, outcome: str, at: datetime) -> None: ...

    def owner_for_account(self, account_ref: str) -> str | None: ...

    def owner_for_transaction(self, rail: PaymentRail, environment: Environment, ref: str) -> str | None: ...

    def grant(self, owner_id: str, observation: TransactionObservation, product: CatalogProduct,
              at: datetime) -> GrantResult:
        """Raises NotFound("owner_deleted") for a deleted account."""
        ...

    def refund(self, owner_id: str, observation: TransactionObservation, at: datetime) -> str: ...

    def mark_completed(self, owner_id: str, txn_id: str, at: datetime) -> bool:
        """Record a confirmed consume/acknowledge in the owner's context."""
        ...

    def pending_completions(self, limit: int) -> list[PendingCompletion]: ...

    def balance(self, owner_id: str, rails: Sequence[PaymentRail]) -> Balance: ...

    def reserve_and_enqueue(self, owner_id: str, *, operation_key: str, rails: Sequence[PaymentRail],
                            report_id: str, revision: int, permission_epoch: int, platform: Platform,
                            job_id: str, reservation_id: str, at: datetime) -> PremiumRequest:
        """Atomically reserve one eligible credit and create the Premium job.
        Idempotent per ``operation_key``; NotAuthorized("no_eligible_credit")."""
        ...

    def premium_status(self, owner_id: str, job_id: str) -> tuple[str, str | None] | None: ...


@dataclass(frozen=True)
class ClaimResult:
    outcome: str
    finish_on_client: bool  # Apple: the client may finish the transaction now


class CommerceService:
    def __init__(self, *, ledger: Ledger, providers: Mapping[PaymentRail, PaymentProvider],
                 permissions: PermissionService, reports: Callable[[str], ReportStore], clock: Clock, ids: IdGenerator,
                 environment: Environment, catalog: tuple[CatalogProduct, ...] = policy.CATALOG,
                 spend_policy: Mapping[PaymentRail, frozenset[Platform]] = policy.DEFAULT_SPEND_POLICY) -> None:
        self._ledger = ledger
        self._providers = dict(providers)
        self._permissions = permissions
        self._reports = reports
        self._clock = clock
        self._ids = ids
        self._environment = Environment.parse(environment)
        self._catalog = catalog
        self._spend_policy = spend_policy

    # --- catalog and checkout ---------------------------------------------
    def catalog(self) -> list[dict]:
        """Products and the rails they can be bought on. Prices come from each
        store or checkout at purchase time and are owner-gated; none here."""
        by_product: dict[str, dict] = {}
        for entry in self._catalog:
            item = by_product.setdefault(entry.product_id, {"product_id": entry.product_id, "credits": entry.credits,
                                                            "rails": {}, "catalog_version": policy.CATALOG_VERSION})
            if entry.rail in self._providers:
                item["rails"][entry.rail.value] = entry.store_product_id
        return list(by_product.values())

    def _provider(self, rail: PaymentRail) -> PaymentProvider:
        provider = self._providers.get(rail)
        if provider is None:
            raise Unsupported("payment_rail_not_configured", detail=rail.value)
        return provider

    def payment_account(self, owner_id: str) -> str:
        """Opaque token native clients pass to the store (appAccountToken /
        obfuscated account ID) so provider evidence names the account."""
        return self._ledger.account_ref(owner_id, self._clock.now())

    def start_web_checkout(self, owner_id: str, product_id: str, intent_ref: str,
                           ctx: CallContext) -> CheckoutSession:
        require_opaque_id(intent_ref, "intent_ref")
        product = policy.catalog_entry(product_id, PaymentRail.STRIPE, self._catalog)
        if product is None:
            raise InvalidInput("unknown_product")
        account_ref = self._ledger.account_ref(owner_id, self._clock.now())
        self._ledger.record_intent(owner_id, intent_ref, PaymentRail.STRIPE, product_id, self._clock.now())
        return self._provider(PaymentRail.STRIPE).create_web_checkout(intent_ref, product, account_ref, ctx)

    # --- verification and grants -----------------------------------------
    def ingest_event(self, rail: PaymentRail, raw_body: bytes, headers: Mapping[str, str],
                     body_sha256: str, ctx: CallContext) -> list[str]:
        """Verify, record in the inbox, then reconcile each named transaction
        from the provider's authoritative state (the event is not the truth)."""
        provider = self._provider(rail)
        event = provider.verify_and_normalize_event(raw_body, headers, ctx)
        if event.environment is not self._environment:
            raise InvalidInput("wrong_environment")
        first = self._ledger.record_event(event, body_sha256, self._clock.now())
        outcomes = []
        for ref in event.transaction_refs:
            owner = self._ledger.owner_for_transaction(rail, event.environment, ref)
            expected = self._ledger.account_ref(owner, self._clock.now()) if owner else ""
            observation = provider.retrieve_authoritative_purchase(ref, expected, ctx)
            outcomes.append(self.apply(observation, ctx))
        summary = (",".join(outcomes)[:512] or "no_transactions") if first else "duplicate_delivery"
        self._ledger.finish_event(event, summary, self._clock.now())
        return outcomes

    def claim_store_purchase(self, owner_id: str, rail: PaymentRail, proof: str, ctx: CallContext) -> ClaimResult:
        """A native client hands over a store proof; the server verifies it."""
        if rail is PaymentRail.STRIPE:
            raise InvalidInput("web_purchases_use_checkout")
        account_ref = self._ledger.account_ref(owner_id, self._clock.now())
        observation = self._provider(rail).verify_purchase(proof, account_ref, ctx)
        outcome = self.apply(observation, ctx, claimed_by=owner_id)
        finish = (observation.completion_action is CompletionAction.CLIENT_FINISH
                  and outcome in ("granted", "already_granted"))
        return ClaimResult(outcome, finish)

    def apply(self, observation: TransactionObservation, ctx: CallContext, *, claimed_by: str | None = None) -> str:
        assessment = policy.assess(observation, environment=self._environment, catalog=self._catalog)
        owner = self._ledger.owner_for_transaction(observation.rail, observation.environment,
                                                   observation.transaction_ref)
        if owner is None and observation.account_ref is not None:
            owner = self._ledger.owner_for_account(observation.account_ref)
            if owner is not None and observation.account_binding is not AccountBinding.MATCHED:
                # The provider attested our token for this owner; the webhook path
                # could not name the owner before looking the purchase up.
                observation = replace(observation, account_binding=AccountBinding.MATCHED)
                assessment = policy.assess(observation, environment=self._environment, catalog=self._catalog)
        if claimed_by is not None and owner is not None and owner != claimed_by:
            return "account_mismatch"
        if assessment.decision is GrantDecision.REFUND:
            return self._ledger.refund(owner, observation, self._clock.now()) if owner else "refund_unmatched"
        if assessment.decision is not GrantDecision.GRANT:
            return assessment.reason
        if owner is None:
            return "account_unknown"
        try:
            result = self._ledger.grant(owner, observation, assessment.product, self._clock.now())
        except NotFound:
            return "owner_deleted"  # a late notification cannot resurrect a deleted account
        if result.completion_due:
            self._complete(owner, result.txn_id, observation.rail, observation.transaction_ref,
                           observation.completion_action, ctx)
        return "granted" if result.created else "already_granted"

    def _complete(self, owner_id: str, txn_id: str, rail: PaymentRail, ref: str, action: CompletionAction,
                  ctx: CallContext) -> bool:
        try:
            self._provider(rail).complete_store_purchase(ref, action, ctx)
        except PortError:
            return False  # durable grant stands; the completion worker retries
        return self._ledger.mark_completed(owner_id, txn_id, self._clock.now())

    def complete_pending(self, ctx: CallContext, limit: int = 50) -> int:
        """Retry server-side consume/acknowledge for grants not yet completed."""
        return sum(self._complete(p.owner_id, p.txn_id, p.rail, p.transaction_ref, p.action, ctx)
                   for p in self._ledger.pending_completions(limit))

    def reconcile(self, rail: PaymentRail, since: datetime, ctx: CallContext) -> list[str]:
        """Missed webhooks, delayed refunds and pending settlements converge here."""
        return [self.apply(observation, ctx) for observation in self._provider(rail).reconcile(since, ctx)]

    # --- credits and Premium ------------------------------------------------
    def balance(self, owner_id: str, platform: Platform) -> Balance:
        return self._ledger.balance(owner_id, policy.spendable_rails(platform, self._spend_policy))

    def request_premium(self, owner_id: str, report_id: str, platform: Platform) -> PremiumRequest:
        latest = self._reports(owner_id).latest(report_id)
        if latest is None or latest[0] != owner_id:
            raise NotFound("report_not_found")
        report = latest[1]
        if report.data["premium_overlay_id"] is not None:
            raise InvalidInput("premium_already_published")
        epoch = self._permissions.require(owner_id, AI_PURPOSE, Scope("REPORT", report_id))
        revision = report.data["revision"]
        key = policy.premium_operation_key(owner_id, report_id, revision, report.data["locale"], POLICY_ID)
        return self._ledger.reserve_and_enqueue(
            owner_id, operation_key=key, rails=policy.spendable_rails(platform, self._spend_policy),
            report_id=report_id, revision=revision, permission_epoch=epoch, platform=platform,
            job_id=self._ids.new_id("pjob"), reservation_id=self._ids.new_id("resv"), at=self._clock.now())

    def premium_status(self, owner_id: str, job_id: str) -> tuple[str, str | None]:
        status = self._ledger.premium_status(owner_id, job_id)
        if status is None:
            raise NotFound("job_not_found")
        return status


__all__ = ["AI_PURPOSE", "Balance", "ClaimResult", "CommerceService", "GrantResult", "Ledger", "PendingCompletion",
           "PremiumRequest"]
