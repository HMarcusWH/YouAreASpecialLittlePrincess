# T29 native compatibility matrix

Status: **implementation spike in progress**. This report is updated from executed build evidence; it is not signing, processor, App Store or Play approval.

## Selected stable baseline

- Expo SDK: **57 stable** (not the SDK 58 beta)
- React Native: **0.86.3**
- React: **19.2.3**
- Expo Router: **57.x**
- Node: repository **22.22.x** line
- Package manager: repository-pinned pnpm 10.33.0
- Native project ownership: **Continuous Native Generation / Expo prebuild + reviewed config plugins**. Generated `ios/` and `android/` directories are not committed.
- Minimum iOS: **16.4**
- Minimum Android: **7 / API 24**, compile/target SDK 36
- Device scope: iPhone + iPad and Android phone + tablet; watches/TV/desktop clients are out of scope.

Expo SDK 58 was still beta when this spike was opened, so T29 intentionally targets the stable SDK 57 line. Expo's SDK 57 August update moved to RN 0.86.3 to resolve documented Hermes/startup regressions.

## Native capabilities

| Capability | T29 implementation | Authority boundary |
|---|---|---|
| Navigation | Expo Router stack | Route selection never grants report access |
| Accepted design | `design-tokens/1.0` | Shared semantics, native primitives; no DOM/WebView |
| Capture | `expo-image-picker` + `expo-image-manipulator` | Local derivative only; server revalidates bytes/pixels/media/permissions |
| HEIC/HEIF | Picker input is re-encoded as JPEG derivative | T04 server remains final accepted-format authority |
| Secure session | `expo-secure-store` | Credential material only; no report/image cache |
| IAP bridge | `expo-iap` compatibility import/config plugin | Native client never mints credits; T19 backend verification is authoritative |
| Deep links | Expo Linking / Router | Allowlisted route only; server authorization follows |
| Files/share | Expo FileSystem + Sharing compatibility | Authorized export only; temporary-file cleanup required |
| Push | Expo Notifications compatibility | Opaque references only; T24/T30/T31 own bindings/live provider |
| Abuse | typed fake/port | Challenge is a risk input, never authorization |

## Build ownership

T29 adopts CNG/prebuild. Native changes belong in reviewed app config/config plugins. Generated `ios/` and `android/` projects remain build artifacts, not hand-edited source. Local Gradle/Xcode builds remain the documented fallback; no EAS processor/signing approval is implied.

## Required evidence before T29 can be DONE

T29 requires development builds that exercise real native modules; Expo Go is insufficient for IAP and Android remote push. The repository may qualify prebuild/compile compatibility without owner production credentials, but **physical-device IAP / signed-development references require the `native_signing_accounts` gate**. Live provider composition also remains behind `processor_retention_contracts`.

This PR therefore remains **T29 IN_PROGRESS** unless those gated references are genuinely attached before merge.

## Rollback

Native module/config changes require a native rebuild. Never rely on OTA JavaScript delivery to repair an incompatible native binary.
