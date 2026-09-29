# PaymentProvider and NativePurchaseClient

[Connector index](README.md) · [T19](../roadmap/06-agent-backlog.md#t19) · [Commerce state machines](../roadmap/14-payments-entitlements-and-commerce.md) · [Apple](../roadmap/12-apple-platform-and-app-store.md) · [Android](../roadmap/13-android-and-google-play.md) · [ADR-006](../adr/ADR-006-payments.md).

## Do not force three different APIs into one checkout function

The backend port exposes capabilities: `create_web_checkout`, `verify_purchase`, `verify_and_normalize_event`, `retrieve_authoritative_purchase`, `complete_store_purchase`, `request_refund_if_supported` and `reconcile`. Each capability returns internal transaction observations and typed errors. A provider profile declares supported product types, signature/token scheme, environment semantics, acknowledgement/consumption behavior and reconciliation limits. Unsupported operations fail explicitly.

The native client port exposes `list_products`, `begin_purchase`, `observe_transaction_updates`, `recover_pending_transactions` and `finish_after_server_grant`. It returns store proofs/states to the application API. It never grants credits, accepts an arbitrary price or stores a server verification secret. Apple client finish and Google server consumption are distinct operations, not interchangeable names.

## Provider adapters

**Web:** The production-disabled `StripePaymentProvider` is implemented under `src/princess_app/adapters/stripe/` using the reviewed backend `httpx` lock rather than the Stripe SDK. It creates hosted Checkout from the server catalog, binds the opaque account/product/environment to Checkout and PaymentIntent metadata, uses the internal intent as Stripe's idempotency key, verifies `Stripe-Signature` over the unmodified raw body, normalizes relevant events to PaymentIntent references, performs authoritative PaymentIntent lookup and bounded reconciliation, and maps failures to typed/redacted port errors. A success redirect is informational and the adapter never grants credits. Production/sandbox composition remains disabled until the pricing/account/processor gates clear; real Stripe refund requests and retained sandbox evidence remain outstanding.

**Apple:** verify signed transaction and notification material through supported server verification tooling; validate trust, app/bundle/product/environment/account identifiers. The transaction identity is stable across replay. App Store Server Notifications V2 and Server API reconciliation feed the same ledger. Finish a consumable after its durable credit grant, not after model completion. Current-entitlement restore does not reconstruct our consumable balance.

**Google Play:** verify purchase tokens server-side, bind package/product/account and grant only authoritative PURCHASED state. Use purchase tokens rather than order IDs as the primary dedupe reference. Consume consumable purchases after durable grant; use the applicable acknowledgement path for other product types. Authenticate Pub/Sub RTDN delivery, then query Play; a notification is not final purchase truth.

## Normalized observation fields

At minimum: provider, environment, external transaction identity, related purchase/event references, internal account-binding proof result, product/quantity, observed state, purchase/effective/refund times where supplied, verification metadata, and allowed completion/reconciliation actions. Preserve unknown fields as unknown. Keep protected provider evidence separately from the application DTO and redact logs.

Application ledger application is atomic and idempotent: unique financial grant, credit-lot origin policy, explicit reservation/fulfilment, compensating refunds. Provider event dedupe alone is insufficient because several distinct notifications may refer to one financial transaction. Store deadline monitoring and retry queues are part of T19, not a client callback convenience.

## Tests and rollout

Run common cases across fakes: repeated proof, separate events about one purchase, wrong environment/product/account, pending→purchased, refund→delayed success event, grant-before-finish crash, consume timeout, duplicate checkout clicks, concurrent last-credit reservation and repeated restore. Verify no double grant and no lost account-backed report. Test actual Apple/Play sandboxes and signed mobile binaries before store release.

Regional steering, alternative billing, tax, price, refund terms and cross-platform consumable portability remain owner/store-policy gates. A RevenueCat or other aggregator comparison may change adapter internals through an ADR; it must not replace the application's source-of-truth ledger without an explicit migration and reconciliation design. Sources E01–E05/E08/E11/E18 in [22](../roadmap/22-research-and-source-refresh.md).
