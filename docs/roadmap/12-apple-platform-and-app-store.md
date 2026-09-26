# 12 — Apple platform and App Store implementation

[Index](00-index.md) · [Mobile](11-mobile-architecture.md) · [Commerce](14-payments-entitlements-and-commerce.md) · [Apple release checklist](../release/apple.md) · [Primary sources](22-research-and-source-refresh.md).

## Work ownership and production gates

T29 establishes the native foundation; T30 implements Apple behavior; T19 owns backend transaction verification and ledger; T32 assembles App Store readiness; T25 authorizes staged publication. Coding agents do not create or approve developer accounts, banking/tax agreements, production products, signing credentials or store release without owner authorization.

Record legal seller identity, Apple team ID, bundle IDs per environment, App Store app ID, signing owner, privacy/support URLs, product catalog and review contact in a private operational register. No signing key, App Store Connect API key, APNs key, session token or real customer transaction payload belongs in this repo.

## Native capabilities

Implement camera and system photo selection with purpose strings, limited/denied states, orientation and HEIC conversion acceptance. Use platform secure credential storage and a documented backup/accessibility policy. Support iPhone and agreed iPad layouts, dynamic text, VoiceOver, reduced motion, safe areas, keyboard and file/share sheets. Auth uses the chosen OIDC provider; include Sign in with Apple where required by the current login policy and implement private-relay/account-linking cases. In-app account deletion is a first-class settings flow, not a support-email substitute (E09).

Configure Associated Domains and serve the approved `apple-app-site-association` document for Universal Links. Separate production/test domains and bundle IDs; restrict path handling. Establish APNs capabilities and token registration through the [push adapter](../connectors/push.md). App Attest/DeviceCheck is a risk signal for sensitive operations, not proof of account identity or an excuse to deny all unsupported devices; define a fallback and replay-resistant server challenge policy.

## StoreKit purchase client

Use StoreKit 2 semantics behind the native purchase port. Fetch store product metadata and show localized price/currency; never calculate a storefront price from a web price. Use account association (`appAccountToken` where supported) with opaque stable IDs. Listen for transaction updates from app startup, not only while a paywall is visible. Handle success, cancellation, unverified, pending/Ask to Buy, interrupted and restored/reconciled states.

Send transaction material to T19's backend verification route. Validate signature/trust chain, bundle/app identity, product allowlist, environment, transaction identifiers and account binding before a ledger grant. Use maintained official verification tooling where practical rather than handwritten JWS cryptography. A client verification success alone does not become our purchase ledger.

Finish a consumable transaction only after the backend durably records its idempotent credit grant. Do **not** wait for the potentially slow Premium analysis to finish. Retry completion safely after crashes; duplicate transaction delivery must not create duplicate credits. Product type, quantity and allowed scope come from the server catalog, not client claims.

## Server purchase lifecycle

Implement App Store Server Notifications V2 ingestion, signed payload verification, environment separation, durable notification inbox and App Store Server API reconciliation. Validate nested signed transaction information too. Reconcile missed/reordered notifications and refunds/revocations; do not let arrival order reverse a newer authoritative state.

Consumables require careful recovery: StoreKit `currentEntitlements` does not represent consumable balances (E03). Recover our remaining credits and generated reports from our account ledger. Transaction history endpoints can assist reconciliation, subject to their actual platform/version coverage; they are not a fresh entitlement grant each time. Never promise that a standard Restore Purchases action recreates spent consumable credits.

Cross-platform access to saved reports is the design goal. Shared consumable credit spending for this non-game product must be reviewed against actual storefront rules; preserve purchase origin and restrict spending if the approved product policy requires it. Apple Pay is not the StoreKit purchase mechanism for these digital reports.

## Privacy and store review

Audit SDK data behavior, privacy manifests, required-reason API declarations, App Privacy labels, consent screens, image transmission to the Premium provider, retention/deletion and support access. Do not add advertising/tracking identifiers or session replay by default. Required SDK/API versions and store submission rules are rechecked when producing the release candidate, not frozen forever from this document.

Marketing must accurately describe deterministic measurements and labelled playful/AI interpretation. An entertainment disclaimer does not justify false device/health/scientific claims. Store approval is not guaranteed by passing our tests. In-app report-content feedback and support escalation must be accessible. Do not reward App Store/TestFlight participation with unreviewed incentives; corpus recruitment and store testing have different terms.

## Build, beta and release evidence

Pin Xcode/SDK, Expo/RN/native module versions and build configuration after the compatibility spike. Use separate development, preview and store profiles. TestFlight/store binaries need the proper signing/distribution configuration; an uploaded IPA is not a released app. Exercise StoreKit local fixtures, Apple sandbox and TestFlight with server test data separated from production.

T32 produces signed artifact digests, build/version IDs, actual device matrix, purchase/refund/recovery test evidence, screenshots/localized metadata, age rating, privacy/support/deletion URLs, reviewer access instructions, working backend endpoints, product review status and known limitations. Record review rejection/remediation explicitly. T25—not an unattended build script—approves the release/phase switch.

## Required negative tests

Wrong bundle/product/environment; invalid certificate/signature; replayed transaction/notification; transaction bound to another principal; app killed before/after grant and before finish; purchase succeeds while model provider is down; refund after credit spend; private-relay account recovery; stale Universal Link; denied photo/push permission; logout while report response arrives; deletion during generation; restore without any restorable products. Free remains usable during billing or model outages.
