# Inktrospect native client (Expo / React Native)

Shared iPhone/iPad and Android phone/tablet client (task T30A, consumed by T30/T31). Native screens, not a web view. The FastAPI service owns authorization, consent, jobs, the ledger and reports; this app never measures handwriting, ranks facts, mints credit or authorizes access. Free inference is zero runtime AI. Pinned versions and native build evidence are in [COMPATIBILITY.md](COMPATIBILITY.md); architecture in [11-mobile-architecture.md](../../docs/roadmap/11-mobile-architecture.md).

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

`tools/run_mobile_journey.sh` drives the app's real composition in Node with Node stand-ins only for device I/O. It is development-API evidence (session, notice, journaled upload with a lost response, process-death resume, Dossier, evidence, retained image, history, comparison, feedback, PDF export with `PRINCESS_E2E_EXPORTS=1`, guest transfer, deletion). It is not device, simulator UI, signed-build or store evidence.

## Known limits

- No physical-device, simulator-UI, signed-build, StoreKit/Play sandbox or push-delivery evidence yet; those are T30/T31 and gated on `native_signing_accounts`, `price_account_terms_before_charges` and `processor_retention_contracts`.
- Account sign-in uses the development identity path only; provider sign-in/refresh (N07) waits for T17 closeout.
- Comparisons are same-owner and not saved; invitations, partner grants and pair Premium wait for T22.
- Fonts use platform serif/monospace fallbacks rather than bundled faces.
- A lost upload-reservation response costs one daily slot (recorded in the journal); the orphaned slot expires server-side. Byte-range resumable upload is not offered.
- React Native's global `URL` is an approximation; security-relevant parsing uses `parseUri` from `@princess/api-client`.

## Maintainer handover

Use the [complete host-specific setup](../../docs/development/local-setup.md) rather than assembling the abbreviated launch examples above. [Native lifecycle/private data](../../docs/architecture/mobile-lifecycle.md) documents session epochs, workflow recovery, signed upload URLs and cleanup. [Testing](../../docs/development/testing.md) distinguishes Node/controller integration from native UI/device/store qualification. [Current state](../../docs/handover/current-state.md) records #72 workflow evidence without inventing a Codex review. [Configuration](../../docs/reference/configuration.md) explains build-time values and runtime/provider limits.
