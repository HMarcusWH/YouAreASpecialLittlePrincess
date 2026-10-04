# Inktrospect native client (Expo / React Native)

Shared iPhone/iPad and Android phone/tablet client (task T30A, consumed by T30/T31). Native screens, not a web view. The FastAPI service owns authorization, consent, jobs, the ledger and reports; this app never measures handwriting, ranks facts, mints credit or authorizes access. Free inference is zero runtime AI. Pinned versions and native build evidence are in [COMPATIBILITY.md](COMPATIBILITY.md); architecture in [11-mobile-architecture.md](../../docs/roadmap/11-mobile-architecture.md). Native presentation follows the accepted Dossier system and the [v3 implementation matrix](../../docs/design/NATIVE_IMPLEMENTATION_MATRIX_V3.md); v3 is a post-acceptance implementation sync, not a second product authority.

## Layout

| Path | Contents |
|---|---|
| `app/` | Expo Router screens: start, capture, review (rotate/crop/consent), analysis status, reports (history/compare selection), report Dossier, feedback, Premium, compare, settings, account, link intent |
| `src/bootstrap/` | `createServices` composition (no React Native imports), native port wiring and the React provider (lifecycle, store replay, push opens) |
| `src/config/runtime.ts` | Build-variant configuration validation |
| `src/session/` | Secure-store credential record, verified hydration, guest sessions, development sign-in with guest transfer, sign-out/everywhere/deletion, epoch fencing |
| `src/work/` | Journal, resumable capture workflow, foreground runner, derivative bounds |
| `src/features/` | Controllers: commerce, Premium, exports, history, feedback, comparison, push, preferences |
| `src/platform/` | Port contracts, fakes, link resolution and Expo adapters (capture, files, share, push, StoreKit/Play via expo-iap, secure store, external-user-agent identity) |
| `src/ui/` | Dossier renderer, evidence drawing, Premium overlay, crop view, shared primitives and tokens |
| `src/i18n/copy.ts` | App chrome copy (EN/SV); report copy comes from `@princess/report-core` |

## Run against a local API

Native builds need a development build (`expo-dev-client`); Expo Go cannot exercise these native modules. The phone talks to the API directly, so the API must issue upload URLs on an origin the device can reach.

Follow [local setup](../../docs/development/local-setup.md) for complete locked backend/role/worker preparation and Android/macOS launch commands. The API and issued upload URLs must use the same device-reachable origin; do not paste a placeholder command as a shell recipe.

| Variable | Meaning |
|---|---|
| `INKTROSPECT_APP_VARIANT` | `development` (default), `staging` or `store`; selects identifier and scheme |
| `INKTROSPECT_API_BASE` | Required. HTTPS for staging/store; development may use loopback/LAN/emulator aliases |
| `INKTROSPECT_BACKEND_ENV` | `local`/`test`/`preview` for development, `staging`, `production` (defaults per variant) |
| `INKTROSPECT_UPLOAD_ORIGINS` | Extra upload origins (presigned storage); uploads elsewhere are refused |
| `INKTROSPECT_LINK_HOSTS` | Verified Universal Link / App Link domains |

Invalid configuration stops at a configuration screen with a code. Store and staging builds cannot contain the development identity path (`src/config/runtime.ts`, tested in `test/app-config.test.ts`). Draft consent notices are shown as drafts and only authorize synthetic local/test use.

## Tests

```bash
pnpm --filter @princess/mobile typecheck
pnpm --filter @princess/mobile test          # Node: session, workflow recovery, runner, controllers, config, links, copy
# The destructive native API journey has a complete isolated recipe in docs/development/local-setup.md.
```

`tools/run_mobile_journey.sh` drives the app's real composition in Node with Node stand-ins only for device I/O. It is development-API evidence (session, notice, journaled upload with a lost response, process-death resume, Dossier, evidence, retained image, history, comparison, feedback, PDF export with `PRINCESS_E2E_EXPORTS=1`, guest transfer, deletion). It is not device, simulator UI, signed-build or store evidence. The packaged Android UI journey is separate; see below.

## Android artifacts: dev client versus standalone handoff

Native foundation (`.github/workflows/native.yml`) builds two different Android binaries. Do not confuse them.

| | Dev-client APK (`android-development`) | Standalone developer-handoff APK (`android-handoff`) |
|---|---|---|
| Gradle task | `:app:assembleDebug` | `:app:assembleRelease` |
| JavaScript | Not embedded: Expo Dev Launcher loads it from Metro | Hermes bundle embedded as `assets/index.android.bundle`; no Metro |
| Runtime config | CI builds it without `INKTROSPECT_*` values (embedded `apiBaseUrl` blank); under Metro the dev server's environment supplies it | Fixed at build time: `development` variant, `local` backend, `http://127.0.0.1:8000`, development identity on |
| Debuggable | Yes | No (`debuggable=false`) |
| Signing | Generated debug key | Generated debug key from the CNG template (development signing; not Play signing) |
| Qualification | Native-module compile evidence | Repository verifier, `apkanalyzer`/`apksigner`, then the exact APK driven through the real Free journey on an API-36 emulator |
| Merged-`main` artifact | `inktrospect-android-dev-client-<sha>` with `inktrospect-dev-client-<short-sha>.apk` and `.sha256`, 14 days | `inktrospect-android-handoff-<sha>` with `inktrospect-handoff-<short-sha>.apk`, `.sha256`, `BUILDINFO.json` and `HANDOFF.md`, 30 days |

Pull-request runs build and qualify both but publish neither: a pull request's `GITHUB_SHA` is a synthetic merge candidate. Only a successful `main` push publishes, and `BUILDINFO.json` records that run's own source commit. Artifacts published before this naming (`inktrospect-android-development-<sha>`) are dev-client debug APKs, not handoff binaries.

### Using the standalone handoff APK

Build it yourself with `tools/build_android_handoff.sh` (a frozen `pnpm install`, a JDK and an Android SDK with build-tools/cmdline-tools are required), or download the merged-`main` artifact and check `sha256sum -c inktrospect-handoff-<short-sha>.apk.sha256`. Then:

1. Check out the `source_commit` from `BUILDINFO.json` and start the local database, API and analysis worker per [local setup](../../docs/development/local-setup.md#8-standalone-android-handoff-apk). Keep the API on host `127.0.0.1:8000` with `PRINCESS_PUBLIC_API_BASE=http://127.0.0.1:8000`.
2. On the emulator or USB-debuggable device: `adb reverse tcp:8000 tcp:8000`, then `adb install -r inktrospect-handoff-<short-sha>.apk`.
3. Launch Inktrospect and use synthetic or explicitly authorized test data only.

The device's `127.0.0.1:8000` reaches the development machine through `adb reverse`, so the fake-provider API never has to listen on the LAN. Android cleartext HTTP is enabled only for the `development` variant (`usesCleartextTraffic` through `expo-build-properties`); staging and store builds keep it off and still require HTTPS.

### What the handoff qualification proves

`tools/run_android_handoff_journey.sh` installs the exact `assembleRelease` output (it pulls the installed APK back and compares SHA-256), confirms the installed package is not debuggable, and refuses to run while anything serves host port 8081. It then drives the app with pinned Maestro 2.11.0 flows in [`e2e/maestro/`](e2e/maestro/):

- clean launch, `Start privately`, `Analyse handwriting`, `Choose from photos`;
- a runtime-generated synthetic 900 × 360 page selected through the Android system Photo Picker;
- review, the server notice's `Analyse this page` switch, and `Analyse my handwriting`;
- a server-backed queued run, with the analysis worker held behind a gate;
- `am force-stop` with data kept, relaunch, recovery of the same journaled run;
- release of the worker, then completion into the saved Dossier and evidence.

Exact database counts before and after (one capture, one run, then one report and one revision, all bound to the same run) prove that the relaunch created no second business result. This is one emulator. It is not physical-device, tablet, signing, store, push or T31 evidence.

## Known limits

- One Android emulator (API 36, x86_64 Google APIs) runs the packaged Free journey; there is no physical-device, tablet, iOS simulator UI, release-signed build, StoreKit/Play sandbox or push-delivery evidence yet. Those are T30/T31 and gated on `native_signing_accounts`, `price_account_terms_before_charges` and `processor_retention_contracts`.
- Account sign-in uses the development identity path only; provider sign-in/refresh (N07) waits for T17 closeout.
- Comparisons are same-owner and not saved; invitations, partner grants and pair Premium wait for T22.
- Fonts use platform serif/monospace fallbacks rather than bundled faces.
- A lost upload-reservation response costs one daily slot (recorded in the journal); the orphaned slot expires server-side. Byte-range resumable upload is not offered.
- React Native's global `URL` is an approximation; security-relevant parsing uses `parseUri` from `@princess/api-client`.

## Maintainer handover

Use the [complete host-specific setup](../../docs/development/local-setup.md) rather than assembling the abbreviated launch examples above. [Native lifecycle/private data](../../docs/architecture/mobile-lifecycle.md) documents session epochs, workflow recovery, signed upload URLs and cleanup. [Testing](../../docs/development/testing.md) distinguishes Node/controller integration, the packaged Android emulator journey and device/store qualification. [Current state](../../docs/handover/current-state.md) records the post-#76 baseline and the standalone Android handoff. [Configuration](../../docs/reference/configuration.md) explains build-time values and runtime/provider limits.
