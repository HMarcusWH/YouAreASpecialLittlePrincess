# T29 native compatibility matrix

Status: **provider-independent foundation implemented; gated native evidence remains**.

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

The package manifest is exact-pinned and `pnpm-lock.yaml` is authoritative for the full graph. `pnpm --filter @princess/mobile compat:check` verifies exact installed versions and package license metadata.

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

| Capability | T29 implementation | Authority boundary |
|---|---|---|
| Navigation | Expo Router native stack | Route selection never grants report access |
| Design | accepted `design-tokens/1.0` | Shared semantics; native primitives, no DOM/WebView |
| Capture | image picker/camera + image-manipulator | Produces local derivative metadata only; server verifies/authorizes/analyzes |
| HEIC/HEIF | picker input can be re-encoded to JPEG derivative | Does not expand backend accepted media authority |
| Secure session | expo-secure-store adapter | Credential material only; report/image payloads excluded |
| Purchase | typed NativePurchaseClient + expo-iap module compatibility | Client never mints credits; T19 server verification/ledger remains authority |
| Deep links | allowlisted route resolver + Expo linking module | Link selects resource; server authorization still required |
| Files/share | typed share port + Expo module compatibility | Authorized exports only; temporary-file cleanup required |
| Push | typed registration port + Expo notifications compatibility | Opaque references only; no handwriting/results/balances |
| Abuse | typed attestation fake/port | Risk signal only, never authorization |

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

- denied camera permission does not fabricate a capture;
- client purchase states never grant application credit;
- finish requires server-grant proof in the fake contract;
- malformed/foreign-scheme deep links fail closed;
- logout/account switch clears push/session state;
- late prior-account responses are discarded by SessionEpoch;
- authorized-file sharing exposes explicit cleanup;
- abuse attestation unavailable remains unavailable rather than authorizing.

T30/T31 add real process death, physical-device camera/HEIC, sandbox purchase, push, link association, screen-reader/text-scale and signed-build lifecycle evidence.

## Permanent validation workflow

`.github/workflows/native.yml` is the retained T29 validation surface. It runs exact package/license checks, Expo compatibility, mobile typecheck/unit/config checks, Android CNG + debug APK compilation, and iOS CNG + CocoaPods + simulator compilation. PR #32 is the first qualification of that permanent workflow.

## Permanent workflow qualification

PR #32 exact-head native run **36545832751** passed all three retained jobs:

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
