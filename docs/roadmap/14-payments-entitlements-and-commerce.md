# 14 — Cross-platform commerce, credits and Premium fulfilment

[Index](00-index.md) · [Payment connectors](../connectors/payments.md) · [Premium](03-premium-openai.md) · [Apple](12-apple-platform-and-app-store.md) · [Android](13-android-and-google-play.md) · [ADR-006](../adr/ADR-006-payments.md).

## Three payment rails, one business ledger

Web checkout, StoreKit and Play Billing send verified provider events to one internal accounting/entitlement system. They do not define our account, report or canonical facts. Initial product design is a repeatable one-time analysis credit, not an automatic subscription. Final SKU, quantity, price, tax, refund and storefront terms require owner approval. Build fakes and sandbox adapters first.

Do not confuse Apple Pay/Google Pay wallets with StoreKit/Play Billing. Do not assume all regional external-payment exceptions apply globally. Native storefront presentation, external links, price messaging and cross-platform credit portability are configurable only through an approved, dated policy record. Saved account-backed reports should be available across our clients subject to lawful entitlement; fungible cross-store consumable spending for this non-game service needs its own review.

## Data model and invariants

Planned entities extend [01](01-data-architecture.md): catalog product and provider SKU mapping; purchase intent; provider transaction; verified event inbox; immutable ledger entry; credit lot; credit reservation; fulfilment; provider attempt; compensating refund/revocation entry. Keep test/production environments part of uniqueness and access boundaries.

Use unique `(provider, environment, external_transaction_identity)` for a financial grant, unique operation/dedupe keys for application fulfilment, and server-owned product/quantity mappings. Store amounts in integer minor currency units; credits are integer units. A read balance is derived from ledger/grant/reservation states, not a client-writable counter. Use row locks or conditional updates so two devices cannot reserve the final credit simultaneously.

Require an authenticated internal account before consumable purchase. Bind store transaction material using provider-supported opaque account identifiers plus server-side verification. Never transfer purchases by matching an email address. Anonymous Free history may migrate through a separately proven guest-to-account ownership transition.

## Separate the state machines

```text
Provider purchase: pending → purchased → completion/consumption; refund/revocation later
Credit lot:        granted → available ↔ reserved → spent; compensating adjustment if needed
Premium job:       authorized → queued → running → validating → published or failure
Provider attempt:  not_sent → sent → success / refused / failed / ambiguous
```

These are conceptual states to formalize in T19/T15 DTOs, not one overloaded enum. Store transaction completion is not Premium completion. A generation timeout is not evidence the store purchase failed. A refund is not a deletion of accounting history.

## Transactional fulfilment algorithm

1. Verify the purchase on the server and resolve the approved catalog mapping, environment and principal. Reject pending, wrong-app, wrong-product, bad-signature and cross-account claims.
2. In one transaction insert the deduplicated provider transaction and immutable credit grant. If already present, return the existing result without granting again. Queue provider finish/consume/acknowledgement and user-notification work in an outbox.
3. Complete the platform purchase promptly after durable grant. Apple client finish must be recoverable; Play consumables use consumption, other types their acknowledgement path. Never wait for the AI job to finish before completing a purchased credit.
4. When the user requests Premium, authorize the report revision, evidence suitability and current third-party-processing permission. Atomically reserve the eligible credit and create one durable fulfilment/job keyed to the intended operation.
5. A leased Premium worker creates bounded provider attempts. Disable hidden SDK retries; ambiguous network outcomes use the documented capped retry/reconciliation policy. Provider execution is not exactly-once.
6. Validate output and recheck report version, lease token, permissions and deletion epoch. Atomically publish the saved overlay and mark the reservation spent. A second worker cannot publish or spend again.
7. On terminal failure, release the reservation or issue an explicit compensating credit per approved policy. Never secretly substitute a template and call it successful paid AI. Free remains intact.

## Recovery and event processing

Signature verification precedes event normalization. Persist raw-body hash and minimal encrypted audit references as needed, not public logs. Webhook inbox ingestion and ledger application are separate idempotent stages. Duplicate event IDs and distinct events about the same transaction both converge on one financial grant. Do not use browser redirects, mobile callbacks or arrival order as final authority.

Reconciliation covers missing webhooks, client death, grant-before-finish crashes, consume-before-response ambiguity, delayed refunds, chargebacks/voided purchases, account deletion and abandoned pending payments. Provider transaction lookup updates observed state with ordering/version rules. Show a supportable pending state when truth is unknown; do not retry by charging again.

Refund policy distinguishes unspent credits, reserved/running jobs and already delivered reports. Use compensating entries, suspend affected unspent lots and prevent new spend where required; preserve legal accounting records under separate retention. Decide access to already delivered Premium content explicitly, without deleting unrelated Free data or fabricating a negative balance workaround. Deleted accounts cannot be resurrected by a late store notification.

## Restore and portability

A restore/reconciliation operation may rediscover a verified purchase; it must never grant it twice. Store-native restore supports the product types the platform actually restores. Consumable balances and generated report history come from our account ledger. App reinstall, another device or a different client fetches that ledger after identity verification. Never interpret absence from `currentEntitlements` or a post-consumption Play query as proof the user never bought credits.

Preserve origin storefront/product/policy on each credit lot. Spend eligibility can be platform-restricted without duplicating accounting logic. Do not promise blanket transferable credits before Apple/Google policy and owner terms are cleared.

## Tests, operations and boundaries

T19 tests all adapters with fake signed/test events and sandbox evidence before activation. Required scenarios: duplicate/reordered events, duplicate clicks across devices, pending→purchased, refund before fulfilment, refund after spend, malformed proof, wrong environment, account binding mismatch, crash at every transactional boundary, lost notification, provider outage, stale lease, deletion during generation and restore repeated many times. Assert one financial grant and at most one published business result, not exactly one external request.

Emit redacted transaction IDs, state transitions and cost totals to restricted audit; keep purchase proofs out of analytics. Alert on pending completion age, unmatched provider events, inconsistent balances, duplicate grant attempts, long reservations and refund divergence. Price/spend ceilings are configuration with named approval; token-cost estimates alone do not establish unit economics.

T19 is a backend task independent of native UI completion. T20 integrates web paywall/fulfilment; T30/T31 integrate native purchasing; T32/T33 verify actual store products and release behavior. [21](21-release-readiness-checklists.md) blocks public commerce until these match the approved scope.
