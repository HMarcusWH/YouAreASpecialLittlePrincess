# 11 — Native mobile architecture and shared-client strategy

[Index](00-index.md) · [Apple](12-apple-platform-and-app-store.md) · [Android](13-android-and-google-play.md) · [Commerce](14-payments-entitlements-and-commerce.md) · [ADR-005](../adr/ADR-005-mobile-framework.md).

## Implementation default and scope

Build an Expo/React Native application with Expo Router, native screens and platform adapters. This is not a webview skin. Share generated TypeScript DTOs/API client, query/state helpers, report formatting, chart specifications, localization keys and design tokens with web. Do not try to share browser DOM, CSS print layout, camera permissions or payment SDK objects across runtimes.

Target the complete phone journey plus adaptive iPad/Android-tablet layouts; exact minimum OS/device support must be recorded and tested at T29. Apple Watch, tvOS, macOS-specific clients, Wear OS and Android TV are not implied deliverables. A change to the supported device matrix is explicit, not a silent store exclusion.

Use development builds for native purchase libraries and platform capabilities; Expo Go alone is not an IAP test environment (source E06 in [22](22-research-and-source-refresh.md)). T29 performs a compatibility spike for the exact Expo/RN/Router/native IAP versions, records licenses and bridge support, then locks them. EAS is a build-service candidate, not a requirement to send signing keys or customer data to a new processor without approval. Local Xcode/Gradle builds remain documented.

## Planned module layout

```text
apps/mobile/app/                  routes and native navigation
apps/mobile/src/features/         capture, reports, history, commerce, sharing, settings
apps/mobile/src/platform/         camera, secure-session, purchases, links, files, notifications
apps/mobile/src/bootstrap/        API transport and provider composition
apps/mobile/plugins/              reviewed native configuration plugins
packages/contracts/               generated shared DTOs
packages/api-client/              transport-neutral application API client
packages/report-core/             semantic presentation/formatting
packages/design-tokens/           shared values; platform-specific rendering
```

Choose Expo configuration/prebuild ownership explicitly: generated native projects should not also accumulate unexplained hand-edits. Native changes belong in tested config plugins or an explicitly adopted committed-native workflow. Record the choice in ADR-005. Rebuild development/store binaries when native modules or entitlements change.

## Native boundary interfaces

`CaptureClient` returns a local asset handle, decoded dimensions, orientation metadata and a proposed crop—not an analysis result. `SecureSessionStore` stores credential material in platform secure storage; image/report payloads do not belong in key-value credential stores. `NativePurchaseClient` exposes store products, purchase state, verified transaction material and finish/recovery operations; it never mints application credits. `DeepLinkRouter` turns validated links into an app route after server authorization. `PushRegistration` manages installation token/environment binding. `FileShareClient` downloads an authorized export to a bounded temporary file and invokes the native share sheet.

Interfaces and all failures have fakes so route tests need no store account. T30/T31 add real bridges and physical-device verification.

## Capture and upload lifecycle

Use system photo pickers/limited-library access where feasible and request camera permission only on capture. Handle denied, restricted, limited, revoked and unavailable-camera states. Avoid requesting broad media/storage permissions for a one-photo workflow. Strip unnecessary metadata from the approved derivative, but preserve the original-to-analysis transform record on the backend.

Photographs from iPhones may use HEIC/HEIF and orientation metadata. T04/T29 must choose and test a supported native-to-raster conversion path with explicit loss/quality limits; do not advertise generic photo support while only accepting a narrow JPEG happy path. Bound decoded pixels, bytes and compression. Crop/orientation changes create a new capture revision and digest. A crop boundary is not automatically a page boundary.

Stage local captures in app-private temporary storage with an expiry/cleanup policy. Begin uploads through server-issued asset authorization. Persist minimal upload/job references so process death, reconnect or token renewal can resume without duplicate business work. Mobile OS background time is not guaranteed: do not claim an upload or Premium job will complete locally after suspension. Server jobs are durable; the client reconciles on foreground.

## Identity, report cache and offline behavior

Use external user-agent OAuth/PKCE through the managed identity adapter, not embedded password scraping. Separate provider identities from internal account IDs; link accounts only with proof of both identities, not matching email text. Bind purchases to an authenticated account before allowing consumable checkout. Recovery must handle Apple's private relay addresses and another device signing into the same account.

No offline inference in v1. Optional offline viewing is limited to already-authorized cached projections under an explicit retention policy; disable by default until logout/account switch, deletion and expiry tests exist. Do not cache handwriting images into shared photo storage without a user action. A stored report cannot remain accessible indefinitely after revoked permissions merely because the app is offline.

## Push, deep links and native sharing

Push carries generic notification type and opaque object reference, not handwriting, report conclusions, private URLs or credit balances. Fetch authorized current state after opening. Token rotation, reinstall, environment mismatch and sign-out all update device bindings. Universal Links/App Links use verified domain association; retain a safe web fallback. A link selects a resource, never grants access by itself.

Native share/file sheets use the same disclosure preview and export projection as web. A successful sheet callback does not prove publication. Clean temporary files, handle cancelled sharing and never add private handwriting to an analytics event.

## Billing and lifecycle requirements

Read [14](14-payments-entitlements-and-commerce.md) before implementing paywalls. Store completion and credit issuance must survive app death; backend verification/reconciliation is authoritative. Show pending, cancelled, verifying, granted, generation-running, failure and refund states distinctly. Restore UI supports restorable store purchases; consumed credits and saved report history recover from the account-backed application ledger, without minting credits again.

Do not present Stripe web checkout in a native paywall by default. Alternative payment/steering rules are region-specific production decisions. The initial architecture uses StoreKit/Play Billing for native digital purchases.

## Delivery plan

T29 builds the shared shell, fake platform ports, secure transport, navigation, capture prototype and compatibility matrix. T30/T31 integrate the complete Apple/Android journeys once API/report/commerce/sharing contracts exist. This split lets native scaffolding begin early without pretending that a shell is a finished paid app.

Acceptance requires real-device capture, interruptions, account switching, deep-link cold/warm start, accessibility text scaling/screen readers, sandbox purchase recovery, push denial, offline re-entry, tablet layout and signed release-build smoke. JavaScript tests alone are not native acceptance. Signed release artifacts and store evidence are owned by T32/T33.
