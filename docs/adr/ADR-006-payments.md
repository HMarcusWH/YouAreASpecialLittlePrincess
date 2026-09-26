# ADR-006 — Internal ledger, three verified payment adapters

[Index](README.md) · [Commerce](../roadmap/14-payments-entitlements-and-commerce.md) · [Payment ports](../connectors/payments.md).

Status: IMPLEMENTATION_DEFAULT for an internal ledger and native platform billing. Web Stripe and direct server verification are defaults to implement after capability/account checks; production catalog and terms remain pending.

Use StoreKit for baseline iOS digital purchases, Play Billing for baseline Android digital purchases and a hosted web checkout adapter. Initial consumable analysis credits are a product hypothesis, not approved price/SKU terms. Preserve credit origin/storefront and configurable spend eligibility; do not assume unrestricted cross-platform consumable portability for a non-game service.

Compare RevenueCat against direct StoreKit/Play server integration during T19/T29: consumable semantics, verification/notification support, account linking, refunds, recovery, lock-in, costs and SDK data use. An aggregator may simplify adapters but does not automatically own the internal credit/fulfilment source of truth.

Acceptance: one verified financial grant, account binding, prompt native finish/consume after durable credit delivery, reservation/fulfilment idempotency, ambiguous timeout handling, repeated restore, refunds and deletion races. Real purchases, alternative billing, steering and price/tax/refund rules require dated owner/storefront approval. Apple Pay/Google Pay wallet support does not replace native digital billing.
