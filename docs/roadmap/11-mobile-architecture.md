> Implemented native maintenance: [mobile README](../../apps/mobile/README.md), [lifecycle/private state](../architecture/mobile-lifecycle.md), [setup](../development/local-setup.md) and [test evidence boundaries](../development/testing.md). This chapter retains architecture and completion requirements.

# 11 — Native mobile architecture and shared-client strategy

[Index](00-index.md) · [Apple](12-apple-platform-and-app-store.md) · [Android](13-android-and-google-play.md) · [Commerce](14-payments-entitlements-and-commerce.md) · [ADR-005](../adr/ADR-005-mobile-framework.md).

## Implementation default and scope

Build an Expo/React Native application with Expo Router, native screens and platform adapters. This is not a webview skin. Share generated TypeScript DTOs/API client, query/state helpers, report formatting, chart specifications, localization keys and design tokens with web. Do not try to share browser DOM, CSS print layout, camera permissions or payment SDK objects across runtimes.

Target the complete phone journey plus adaptive iPad/Android-tablet layouts; exact minimum OS/device support must be recorded and tested at T29. Apple Watch, tvOS, macOS-specific clients, Wear OS and Android TV are not implied deliverables. A change to the supported device matrix is explicit, not a silent store exclusion.

Use development builds for native purchase libraries and platform capabilities; Expo Go alone is not an IAP test environment (source E06 in [22](22-research-and-source-refresh.md)). T29 pinned Expo 57.0.25 / RN 0.86.3 / Router 57.0.23 / expo-iap 5.6.3 and the checked-in lockfile; `apps/mobile/scripts/check-compatibility.mjs` verifies exact installed versions and license metadata. EAS is a build-service candidate, not a requirement to send signing keys or customer data to a new processor without approval. Local Xcode/Gradle builds remain documented.

## Module layout (implemented by T29/T30A)

```text
apps/mobile/app/                  Expo Router screens and the link intent filter (+native-intent)
apps/mobile/src/bootstrap/        createServices composition (no React Native imports), native wiring, React provider
apps/mobile/src/config/           build-variant runtime configuration validation
apps/mobile/src/session/          secure-store credential, hydration, guest/dev sign-in, transfer, sign-out/deletion
apps/mobile/src/work/             journal, resumable capture workflow, foreground runner, derivative bounds
apps/mobile/src/features/         commerce, Premium, exports, history, feedback, comparison, push, preferences
apps/mobile/src/platform/         port contracts, fakes, links, Expo adapters (capture, files, share, push, IAP, identity)
apps/mobile/src/ui/               Dossier renderer, evidence drawing, Premium overlay, crop view, primitives, tokens
packages/contracts/               generated shared DTOs
packages/api-client/              transport-neutral client, runtime guards, portable SHA-256, strict URI parser
packages/report-core/             formatting, charts, shared EN/SV report copy, dossier reading model
packages/design-tokens/           shared values; platform-specific rendering
```

No reviewed config plugins exist yet; native configuration is expressed through `app.config.ts` and installed module plugins. Build variants (`development`/`staging`/`store`) differ by identifier, scheme and backend; the app name stays constant because CNG derives the Xcode workspace from it.

## Mobile-first execution amendment (2026-10-03)

T30A carries the shared native client against `DONE` capability tasks (T01–T04, T09, T15, T18, T27, T28), fakes and the development API, and adds only the native-facing API contracts it consumes: `GET /v1/analyses` (run discovery after reinstall/second device), `DELETE /v1/reports/{id}` (report-scoped deletion), `GET /v1/reports/{id}/source-image` (retained input through the live OWNER projection), `GET /v1/consent-notices` (exact notice text/version and draft status) and `POST /v1/comparisons` (unsaved same-owner T18 comparison). T30/T31 keep the platform qualification: signed devices, StoreKit/Play sandboxes, push delivery, verified links and accessibility on the device matrix. They no longer wait for web Premium T20. A mobile-scoped release candidate is recorded separately and is not T25 multi-platform signoff.

Implemented behaviour, with Node tests and the development-API journey (`tools/run_mobile_journey.sh`) as evidence; the standalone Android handoff APK additionally runs the picker-to-Dossier path with force-stop recovery on one API-36 emulator (`tools/run_android_handoff_journey.sh`, see [testing](../development/testing.md#standalone-android-packaged-ui)):

- **Session:** one versioned credential record in secure storage; verified hydration (offline launch stays unverified until an authenticated call succeeds); private guest sessions; development sign-in only in development builds against local/test backends; guest transfer proven by both credentials; local sign-out, application sign-out-everywhere and asynchronous account deletion kept distinct; serialized credential changes and epoch fencing; a 401 forgets only the credential that was rejected; exit hooks purge the outgoing principal's journal, private files and push binding.
- **Capture to report:** system picker without broad media permission; camera permission only on capture; metadata-free re-encode bounded to the intake policy; rotate/crop review where every later coordinate refers to the uploaded derivative. A journal entry records the intent and digest before any network call; each step (reserve, PUT, complete, grant by request ID, start with dedupe, poll) is idempotent server-side except reservation, whose lost response costs one recorded slot. Lost responses and process death at every transition converge on one capture, grant and run.
- **Reading:** the Dossier renders the saved projection (server First Reveal, every Free fact with evidence class and availability, notices, actions with reasons) and stored evidence (baseline traces drawn from stored points with text alternatives; spacing and slant observation tables). The retained source image is downloaded with the bearer credential through the report-scoped route and evidence is overlaid only when the stored frame matches it exactly.
- **Paid states:** offers join the server catalog with store-localized prices; the store transaction is finished only after the server reports a durable grant (Play consumption stays server-side); pending, cancelled and unknown outcomes never ask to pay twice; a purchase requires an account first. Premium shows only the saved validated overlay, its evidence class, support and omissions, and needs the server's PURCHASE action, an account, a retained image and report-scoped third-party AI permission.
- **Runtime caveat:** React Native's global `URL` is a regex approximation that accepts malformed input and loses custom-scheme hosts. Upload-origin, configuration, deep-link and auth-callback checks use the shared strict `parseUri` instead.

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

T29 builds the shared shell, fake platform ports, secure transport, navigation, capture prototype and compatibility matrix. T30A builds the shared client capabilities against the established contracts and fakes. T30/T31 qualify the complete Apple/Android journeys on signed devices and store sandboxes. This split lets native work proceed without pretending that a development-API journey is a qualified paid app.

Acceptance requires real-device capture, interruptions, account switching, deep-link cold/warm start, accessibility text scaling/screen readers, sandbox purchase recovery, push denial, offline re-entry, tablet layout and signed release-build smoke. JavaScript tests alone are not native acceptance. Signed release artifacts and store evidence are owned by T32/T33.
