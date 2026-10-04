# T29 native compatibility matrix

Status: **provider-independent foundation (T29) and shared client capabilities (T30A) implemented; gated native evidence remains**.

This report records executed T29 compatibility evidence. It is not App Store/Play approval, production signing approval, processor approval or a claim that the T30/T31 client journeys are complete.

## Exact pinned baseline

| Component | Exact version |
|---|---:|
| Expo | 57.0.25 |
| React Native | 0.86.3 |
| React | 19.2.3 |
| Expo Router | 57.0.23 |
| expo-iap | 5.6.3 |
| OpenIAP Android dependency observed in prebuild | 3.5.2 |
| expo-dev-client | 57.0.19 |
| expo-secure-store | 57.0.4 |
| expo-image-picker | 57.0.20 |
| expo-image-manipulator | 57.0.20 |
| expo-file-system | 57.0.7 |
| expo-sharing | 57.0.22 |
| expo-linking | 57.0.11 |
| expo-notifications | 57.0.21 |
| react-native-screens | 4.26.2 |
| react-native-safe-area-context | 5.7.0 |
| react-native-reanimated | 4.5.1 |
| react-native-worklets | 0.10.1 |
| Node | repository 22.22.x line |
| pnpm | 10.33.0 |

The package manifest is exact-pinned and `pnpm-lock.yaml` is authoritative for the full graph. `pnpm --filter @princess/mobile compat:check` verifies exact installed versions and package license metadata. The retained CI also runs `expo install --check` with `EXPO_OFFLINE=1`, so this supplemental Expo compatibility check is evaluated against the exact installed SDK package rather than a mutable remote recommendation table.

SDK 58 was beta when the spike began; T29 therefore selected the stable SDK 57 line. The compatibility target is intentionally versioned, not “latest”.

## Build ownership and device matrix

- Native project ownership: **Expo Continuous Native Generation / prebuild plus reviewed config plugins**.
- Generated `apps/mobile/ios/` and `apps/mobile/android/` are build artifacts and remain uncommitted.
- Native changes must be represented in `app.config.ts` / reviewed plugins or the ownership ADR must change explicitly.
- Local Xcode/Gradle builds remain supported; EAS is optional and is not approved here as a processor/signing custodian.
- Minimum iOS target: **16.4**.
- Minimum Android: **API 24**, compile/target **API 36**.
- Layout scope: iPhone + iPad; Android phone + tablet; portrait/landscape adaptation. Watches/TV/desktop-native clients are excluded.

## Capability boundary

| Capability | Implementation (T29 foundation, T30A client) | Authority boundary |
|---|---|---|
| Navigation | Expo Router native stack; `+native-intent` passes every system URL through the allowlist | Route selection never grants report access |
| Design | accepted `design-tokens/1.0`; platform serif/monospace fallbacks | Shared semantics; native primitives, no DOM/WebView |
| Capture | system camera/Photo Picker + image-manipulator; no broad media permission requested | Produces a bounded private derivative only; server verifies/authorizes/analyzes |
| HEIC/HEIF | picker asks for a compatible representation; re-encoded to JPEG (PNG kept as PNG) | Does not expand backend accepted media authority; device verification pending |
| Identity transport | external-user-agent adapter via expo-web-browser; request/callback checks use the strict shared `parseUri` | No embedded password/provider secret; provider sign-in/refresh not wired (T17 gate) |
| Secure session | expo-secure-store adapter holding one versioned credential record | Credential material only; report/image payloads excluded |
| Work journal | app-private JSON document of IDs/digests; capture files in private cache | No image bytes, report bodies, purchase proofs or credentials |
| Purchase | expo-iap StoreKit/Play adapter; app finishes Apple transactions only after a durable server grant; Play consumption stays server-side | Client never mints credits; T19 server verification/ledger remains authority; sandbox unexercised |
| Deep links | allowlisted scheme + verified-host resolver (Universal/App Links configured from `INKTROSPECT_LINK_HOSTS`) | Link selects resource; server authorization still required |
| Files/share | bearer download of API files into private cache with size/type sniffing; expo-sharing; cleanup after the sheet closes | Authorized exports only; downloaded copies cannot be recalled |
| Push | expo-notifications device token registered with the API per principal; opens route by opaque reference | Opaque references only; no handwriting/results/balances |
| Abuse | typed attestation fake/port | Risk signal only, never authorization |

React Native's global `URL` is a regex approximation (it accepts malformed input and reports an empty host and `/` path for custom schemes). Security-relevant parsing never uses it.

## Build variants and permissions (T30A)

`app.config.ts` reads `INKTROSPECT_APP_VARIANT` (`development`/`staging`/`store`), `INKTROSPECT_API_BASE`, `INKTROSPECT_BACKEND_ENV`, `INKTROSPECT_UPLOAD_ORIGINS` and `INKTROSPECT_LINK_HOSTS`; `src/config/runtime.ts` re-validates at launch (store: HTTPS + production backend, no development identity). Variants differ by bundle/package identifier (`se.inktrospect.development`, `.staging`, `se.inktrospect`) and scheme; the app name stays `Inktrospect` because CNG derives the Xcode workspace the native CI builds from it.

Android blocks `RECORD_AUDIO` and the Android 13+ media permissions (`READ_MEDIA_*`); the picker library's legacy storage pair (maxSdkVersion 32) is kept because its camera path requires `WRITE_EXTERNAL_STORAGE` on Android 7–9. iOS sets no photo-library usage description (PHPicker needs none) and allows local networking only in development builds.

Local T30A evidence on branch `claude/determined-volta-42hu9a` (not exact-head CI): an Android CNG prebuild merged the blocked permissions as `tools:node="remove"` and generated the App Links intent filter with `autoVerify`; Metro exports compiled the whole app to Hermes bytecode for Android and iOS with no fake or test helper in the bundle. No APK/IPA was built in that environment (no Android SDK or Xcode); the Native foundation workflow remains the compile qualification.

## Executed Android evidence

GitHub Actions run **36512024914** passed:

- exact SDK compatibility check;
- mobile TypeScript compile;
- native platform/session unit tests;
- public Expo config generation;
- clean Android CNG/prebuild;
- `./gradlew :app:assembleDebug --no-daemon`.

The log shows `expo-iap 5.6.3` compiled and OpenIAP `3.5.2` was inserted by the plugin. Android build properties were `minSdkVersion 24`, `compileSdkVersion 36`, `targetSdkVersion 36`. Gradle ended with **BUILD SUCCESSFUL**.

This is compile/prebuild compatibility evidence. The debug APK uses the build environment's development/debug signing context; it is **not** production signing evidence and does not prove a physical-device store transaction.

## Negative/lifecycle evidence

Node-side native tests cover:

- denied or unavailable camera permission does not fabricate a capture;
- client purchase states never grant application credit;
- an emitted store proof cannot finish until the fake records the authoritative server-grant transition; the fake does not perform server verification or mint credits;
- malformed/foreign-scheme deep links fail closed;
- logout/account switch clears push/session state;
- late prior-account responses are discarded by SessionEpoch;
- authorized-file sharing exposes explicit cleanup;
- provider-neutral external-user-agent identity requests contain no embedded client secret, and returned callbacks must match the requested scheme/host/port/path plus state;
- abuse attestation unavailable remains unavailable rather than authorizing;
- exact compatibility validation rejects unsupported native dependency/version drift.

T30A adds Node tests for session, workflow recovery, runner, controllers, configuration, links and copy, plus the development-API journey (`tools/run_mobile_journey.sh`). T30/T31 add real process death, physical-device camera/HEIC, sandbox purchase, push, link association, screen-reader/text-scale and signed-build lifecycle evidence.

## Permanent validation workflow

`.github/workflows/native.yml` is the retained T29 validation surface. It runs exact package/license checks, Expo compatibility, mobile typecheck/unit/config checks, Android CNG + debug APK compilation, and iOS CNG + CocoaPods + simulator compilation. The Android job hashes every qualified development APK. On a push to `main` it also renames and retains that merged-main APK for 14 days as a GitHub Actions artifact; pull-request runs do not publish a handoff artifact because their `GITHUB_SHA` is a synthetic merge candidate. Retention does not change debug/development signing status. PR #32 is the first qualification of the permanent build workflow.

## Permanent workflow qualification

PR #32 native run **36545832751** passed all three retained jobs on its then-current PR merge ref, whose branch head was `abcc2514ca4029f305c9f899cbf8754400fa2c4f`. This is retained qualification evidence for that native state; it is **not** exact-head evidence for later commits. Each later PR head must carry its own workflow evidence before being described as fully green:

- **static:** frozen install, exact version/license check, Expo compatibility, TypeScript, unit tests and public config;
- **android-development:** clean CNG/prebuild + debug APK compile with native modules; APK SHA-256 `6802b2e6b3d7cdf09541cdb90d7c83422094e2953b63818ac1f7cb7d6ddc89fe`;
- **ios-simulator:** Xcode 26.6 / Swift 6.3 toolchain check, clean iOS CNG/prebuild, CocoaPods install and simulator `xcodebuild` with `CODE_SIGNING_ALLOWED=NO`; log ended `** BUILD SUCCEEDED **`.

The iOS build graph includes `ExpoIap` / OpenIAP alongside the capture, secure-store, notifications, linking, sharing and other selected native modules. This is strong compile/integration evidence on both platforms but still not a signed physical-device store transaction.

## Remaining gates

T29 remains **IN_PROGRESS** because its task contract requires development builds to exercise real native modules and signed-development references. Expo Go is explicitly insufficient for IAP.

Remaining external evidence:

1. **native_signing_accounts** — real signed development/device build and store/IAP exercise.
2. **processor_retention_contracts** — approved live composition for identity/push/abuse/provider processing where an external processor is involved.

No coding agent may fabricate those approvals.

## Rollback

Changing a native module, plugin, entitlement or minimum OS requires rebuilding native binaries. OTA JavaScript delivery must never be used to bypass an incompatible native binary/store review requirement.
