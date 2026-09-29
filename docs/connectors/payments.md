# PaymentProvider and NativePurchaseClient

[Connector index](README.md) · [T19](../roadmap/06-agent-backlog.md#t19) · [Commerce state machines](../roadmap/14-payments-entitlements-and-commerce.md) · [Apple](../roadmap/12-apple-platform-and-app-store.md) · [Android](../roadmap/13-android-and-google-play.md) · [ADR-006](../adr/ADR-006-payments.md).

## Do not force three different APIs into one checkout function

The backend port exposes capabilities: `create_web_checkout`, `verify_purchase`, `verify_and_normalize_event`, `retrieve_authoritative_purchase`, `complete_store_purchase`, `request_refund_if_supported` and `reconcile`. Each capability returns internal transaction observations and typed errors. A provider profile declares supported product types, signature/token scheme, environment semantics, acknowledgement/consumption behavior and reconciliation limits. Unsupported operations fail explicitly.

The native client port exposes `list_products`, `begin_purchase`, `observe_transaction_updates`, `recover_pending_transactions` and `finish_after_server_grant`. It returns store proofs/states to the application API. It never grants credits, accepts an arbitrary price or stores a server verification secret. Apple client finish and Google server consumption are distinct operations, not interchangeable names.

## Provider adapters

**Web:** The production-disabled `StripePaymentProvider` is implemented under `src/princess_app/adapters/stripe/` using the reviewed backend `httpx` lock rather than the Stripe SDK. It creates hosted Checkout from the server catalog, binds the opaque account/product/environment to Checkout and PaymentIntent metadata, uses the internal intent as Stripe's idempotency key, verifies `Stripe-Signature` over the unmodified raw body, normalizes relevant events to PaymentIntent references, performs authoritative PaymentIntent lookup and bounded reconciliation, and maps failures to typed/redacted port errors. PR #36 adds full PaymentIntent refund requests behind a separate explicit refund-approval capability; merely constructing the disabled adapter does not enable refunds. A success redirect is informational and the adapter never grants credits. Production/sandbox composition remains disabled until the pricing/account/processor gates clear.

**Apple:** PR #36 adds a production-disabled `AppleAppStorePaymentProvider` under `src/princess_app/adapters/apple/`. It verifies ES256 JWS material and the presented x5c certificate chain against configured Apple trust roots, validates bundle/product/Sandbox-or-Production/appAccountToken binding, verifies App Store Server Notifications V2 including nested signed transaction information, performs authoritative Get Transaction Info lookup, and backfills missed events through bounded Notification History before re-reading current transaction state. Apple remains `CLIENT_FINISH`: the native client finishes only after the durable server grant. Production composition and retained Apple sandbox/TestFlight evidence remain gated.

**Google Play:** PR #36 adds a production-disabled `GooglePlayPaymentProvider` under `src/princess_app/adapters/google/`. It uses server-side service-account OAuth and ProductPurchaseV2 for authoritative token state, binds package/product/obfuscatedExternalAccountId, authenticates Pub/Sub RTDN bearer JWTs before decoding notification data, and treats RTDN only as a change signal. Consumables use server consume after durable grant; non-consumables use acknowledgement. Voided Purchases provides bounded refund/chargeback backfill and each token is re-read through ProductPurchaseV2 before ledger application. Production composition and retained license-test/internal-track evidence remain gated.

## Normalized observation fields

At minimum: provider, environment, external transaction identity, related purchase/event references, internal account-binding proof result, product/quantity, observed state, purchase/effective/refund times where supplied, verification metadata, and allowed completion/reconciliation actions. Preserve unknown fields as unknown. Keep protected provider evidence separately from the application DTO and redact logs.

Application ledger application is atomic and idempotent: unique financial grant, credit-lot origin policy, explicit reservation/fulfilment, compensating refunds. Provider event dedupe alone is insufficient because several distinct notifications may refer to one financial transaction. Store deadline monitoring and retry queues are part of T19, not a client callback convenience.

## Tests and rollout

Run common cases across fakes: repeated proof, separate events about one purchase, wrong environment/product/account, pending→purchased, refund→delayed success event, grant-before-finish crash, consume timeout, duplicate checkout clicks, concurrent last-credit reservation and repeated restore. Verify no double grant and no lost account-backed report. Test actual Apple/Play sandboxes and signed mobile binaries before store release.

Regional steering, alternative billing, tax, price, refund terms and cross-platform consumable portability remain owner/store-policy gates. A RevenueCat or other aggregator comparison may change adapter internals through an ADR; it must not replace the application's source-of-truth ledger without an explicit migration and reconciliation design. Sources E01–E05/E08/E11/E18 in [22](../roadmap/22-research-and-source-refresh.md).
