# 13 — Android and Google Play implementation

[Index](00-index.md) · [Mobile](11-mobile-architecture.md) · [Commerce](14-payments-entitlements-and-commerce.md) · [Android release checklist](../release/android.md) · [Primary sources](22-research-and-source-refresh.md).

## Work ownership

T29 builds the shared native foundation, T31 implements Android behavior, T19 owns server verification/ledger, T33 prepares Play release evidence and T25 authorizes rollout. Owner approvals cover the developer account/entity, Play signing setup, package name, payment/merchant configuration, service accounts and production release access.

Record package/application ID, environment variants, Play app record, product IDs, signing-certificate fingerprints, API service-account permissions and Pub/Sub topic/subscription configuration privately. Separate sandbox/license-test activity from production ledger rows. Never ship Developer API credentials or Pub/Sub authentication secrets in the app.

## Native client requirements

Use the system photo picker/camera path with narrow permissions, deny/revoke controls, rotation/crop/format parity and explicit decoded-pixel bounds. Handle process death, activity recreation, connectivity changes and background limits without issuing a duplicate analysis or purchase. Use secure credential storage, safe temporary-file sharing through approved content URIs, TalkBack/text scaling, keyboard/focus support, back navigation and adaptive phone/tablet layouts.

Use verified Android App Links and `assetlinks.json` tied to the correct package and release signing certificate. Validate every incoming route and fetch current server permissions. Register FCM installation tokens with environment and principal binding. Play Integrity signals can harden paid/abuse-prone calls with server nonce/request binding; define unavailable/unrecognized/device-integrity outcomes and fallback policy rather than silently turning it into the sole authorization system.

## Play Billing client and server flow

Use the current supported Play Billing API through the tested native adapter. Query product details from Play and render its localized price. Support one-time repeatable consumables for analysis credits as the initial product hypothesis; subscriptions require a separate scoped decision. Google Pay is not a substitute for Play Billing for the native digital product.

After purchase updates or foreground reconciliation, submit the purchase token and minimal context to the backend. Backend verification checks package, product/quantity, environment/test state where exposed, purchase state and account association. Deduplicate by provider/environment/purchase token, not order ID. Grant only on authoritative `PURCHASED`, never `PENDING` (E04/E05).

Atomically create the unique ledger grant, then consume an eligible consumable through the server purchase API. Consumption both enables repurchase and fulfills the platform acknowledgement obligation for that consumable; non-consumables/subscriptions use their appropriate acknowledgement path. Do not blindly acknowledge and consume every product as two mandatory steps. Schedule immediate completion/retry and alert well before the platform's acknowledgement deadline; the deadline is not a safe wait time for model generation.

A consumed Play purchase is not an unspent app credit. Recover account-backed credit balances and saved reports from our ledger. Foreground queries, notification reconciliation and idempotent server claims must survive app reinstall, pending completion and lost client callbacks without minting duplicate grants.

## Developer API and RTDN

Implement the Google Play Developer API adapter with least privilege and exact endpoint/version mappings for the chosen product model. RTDN arrives via Cloud Pub/Sub; authenticate the delivery envelope/token and audience, persist/deduplicate the message and query Play for authoritative state. RTDN is a change signal, not the complete purchase ledger. A Pub/Sub acknowledgement means the event was safely accepted for processing, not that the user's credit was consumed.

Handle replay, out-of-order delivery, backfill, invalid tokens, voided/refunded purchases and API outages. A verified refund changes a compensating ledger state; it does not delete the original accounting event or the user's unrelated Free analysis.

## Play policy and privacy work

Native digital purchase behavior defaults to Play Billing. Regional alternative-billing/external-offer programmes require eligibility, enrollment, fresh terms and a separately approved storefront configuration; agents must not route all users to web checkout based on a remembered exception.

Complete Data Safety and app-access declarations from an actual SDK/data-flow inventory. Provide in-app account deletion and a public web deletion-request path, with the exact current policy checked at release. Implement a report-content feedback mechanism and review the AI-generated-content policy where Premium applies (E13). Public sharing needs reporting/revocation controls and accurate content/age ratings; a private analysis is not consent to public publication.

Target API level, Play Billing library deadlines, native-library compatibility/page-size requirements and required testing rules are version-sensitive. T33 records the currently applicable versions/deadlines with source and account evidence before submission. Do not pin a stale target API requirement in prose and call the app compliant.

## Build/testing/release

Build signed Android App Bundles with Play App Signing and protected upload-key custody. Record release artifact hash, versionCode/versionName, exact Gradle/JDK/SDK and native library matrix. Development APK smoke is not production AAB acceptance. Test internal distribution, Play internal/closed tracks, license testers, Billing test responses and real supported devices. Account-specific production-access testing can impose minimum testers/duration; verify whether it applies to the owner's actual account. Do not fabricate tester participation or promise that elapsed days guarantee approval.

T33 assembles prelaunch/device reports, ANR/crash and accessibility results, billing lifecycle evidence, app access for reviewers, store listing/localization/screenshots, content rating, Data Safety, privacy/support/deletion URLs and current policy attestations. T25 authorizes staged rollout with monitoring and halt criteria.

## Required negative tests

Pending and cancelled purchases; token reused under a second account; invalid package/product; duplicate RTDN; consume timeout after durable grant; app killed before verification; delayed notification after refund; offline foreground restore; expired credentials; revoked photo permission; stale App Link signatures; push token bound to old principal; denial by integrity service; deleted report reopened from a notification. Test platform failure without breaking deterministic Free.
