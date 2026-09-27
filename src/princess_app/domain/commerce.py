"""Commerce domain rules shared by every payment rail (T19).

* The catalog is server-owned: an internal product maps to one store product
  per rail and a whole number of credits. No prices live here; prices, tax,
  refunds and storefronts are owner gates (``price_account_terms_before_charges``).
* A grant needs an authoritative PURCHASED observation from this deployment's
  environment, for a catalog product on that rail, attested for the claimed
  account. Anything else is refused with a reason and grants nothing.
* Credit lots keep their origin rail. Which client platforms may spend a lot
  is a policy record; the default allows only the origin platform because
  cross-store consumable portability is not approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ..ports.base import Environment, InvalidInput, require_opaque_id
from ..ports.payments import AccountBinding, CatalogProduct, PaymentRail, PurchaseState, TransactionObservation

CATALOG_VERSION = "catalog-draft/1"
PREMIUM_SINGLE = "premium_single"

# Draft catalog: one Premium analysis credit per purchase. Store product IDs are
# placeholders until the owner registers real products in each store.
CATALOG: tuple[CatalogProduct, ...] = (
    CatalogProduct(PREMIUM_SINGLE, PaymentRail.STRIPE, "price_premium_single_draft", 1),
    CatalogProduct(PREMIUM_SINGLE, PaymentRail.APPLE_APP_STORE, "se.princess.premium.single.draft", 1),
    CatalogProduct(PREMIUM_SINGLE, PaymentRail.GOOGLE_PLAY, "premium_single_draft", 1),
)


class Platform(str, Enum):
    WEB = "web"
    IOS = "ios"
    ANDROID = "android"


ORIGIN_PLATFORM: Mapping[PaymentRail, Platform] = MappingProxyType({
    PaymentRail.STRIPE: Platform.WEB,
    PaymentRail.APPLE_APP_STORE: Platform.IOS,
    PaymentRail.GOOGLE_PLAY: Platform.ANDROID,
})

# Spend eligibility by origin rail. Default: origin platform only, pending an
# approved, dated portability policy record.
DEFAULT_SPEND_POLICY: Mapping[PaymentRail, frozenset[Platform]] = MappingProxyType(
    {rail: frozenset({platform}) for rail, platform in ORIGIN_PLATFORM.items()})


def spendable_rails(platform: Platform, policy: Mapping[PaymentRail, frozenset[Platform]] = DEFAULT_SPEND_POLICY
                    ) -> tuple[PaymentRail, ...]:
    return tuple(rail for rail, platforms in policy.items() if platform in platforms)


def catalog_entry(product_id: str, rail: PaymentRail,
                  catalog: tuple[CatalogProduct, ...] = CATALOG) -> CatalogProduct | None:
    return next((p for p in catalog if p.product_id == product_id and p.rail is rail), None)


class GrantDecision(str, Enum):
    GRANT = "GRANT"
    PENDING = "PENDING"            # not yet paid: nothing granted, check again later
    REFUND = "REFUND"              # compensate an existing grant
    REJECT = "REJECT"


@dataclass(frozen=True)
class Assessment:
    decision: GrantDecision
    reason: str
    product: CatalogProduct | None = None


def assess(observation: TransactionObservation, *, environment: Environment,
           catalog: tuple[CatalogProduct, ...] = CATALOG) -> Assessment:
    """Decide what one authoritative observation may do to the ledger."""
    if observation.environment is not environment:
        return Assessment(GrantDecision.REJECT, "wrong_environment")
    if observation.state in (PurchaseState.REFUNDED, PurchaseState.REVOKED):
        return Assessment(GrantDecision.REFUND, observation.state.value.lower())
    if observation.state is PurchaseState.PENDING:
        return Assessment(GrantDecision.PENDING, "payment_pending")
    if observation.state is not PurchaseState.PURCHASED:
        return Assessment(GrantDecision.REJECT, f"state_{observation.state.value.lower()}")
    if observation.account_binding is not AccountBinding.MATCHED:
        return Assessment(GrantDecision.REJECT, "account_binding_" + observation.account_binding.value.lower())
    product = catalog_entry(observation.product_id, observation.rail, catalog)
    if product is None:
        return Assessment(GrantDecision.REJECT, "unknown_product")
    return Assessment(GrantDecision.GRANT, "purchased", product)


def premium_operation_key(owner_id: str, report_id: str, revision: int, locale: str, policy_id: str) -> str:
    """One intended Premium deliverable: retries of the same request converge."""
    for value, name in ((owner_id, "owner_id"), (report_id, "report_id"), (policy_id, "policy_id")):
        require_opaque_id(value, name)
    if type(revision) is not int or revision < 1:
        raise InvalidInput("invalid_revision")
    return f"premium:{owner_id}:{report_id}:{revision}:{locale}:{policy_id}"


__all__ = ["Assessment", "CATALOG", "CATALOG_VERSION", "DEFAULT_SPEND_POLICY", "GrantDecision", "ORIGIN_PLATFORM",
           "PREMIUM_SINGLE", "Platform", "assess", "catalog_entry", "premium_operation_key", "spendable_rails"]
