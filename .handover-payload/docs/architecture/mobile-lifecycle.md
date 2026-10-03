# Native client lifecycle and private state

The shared client is in [apps/mobile](../../apps/mobile/README.md). `src/bootstrap/services.ts` composes platform-independent controllers; `native.ts` supplies native ports; `AppProvider.tsx` connects React lifecycle, work replay, purchase recovery and notification opens. Platform fakes are tests, not a live-provider fallback.

## Session boundary

`src/session/session-manager.ts` owns a versioned secure-store credential record: principal ID, kind, opaque token, origin and optional expiry. Hydration verifies `/v1/me` when reachable. Active-but-unverified offline state is not a new authorization grant. Credential changes are serialized and advance `SessionEpoch`; results arriving for the previous epoch are discarded.

The API credential is read per request, not captured forever by a long-lived client. A rejected credential should not clear a replacement credential installed while that request was in flight. Exit hooks purge outgoing-principal data and unregister relevant local/platform state as implemented. Provider sign-in/refresh/recovery remains N07/T17 work; accepting a provider-shaped record type is not a complete provider lifecycle.

Distinguish local sign-out, application-wide revocation and requested account deletion. Never claim provider-global revocation from a local secure-store clear.

## Capture journal and recovery

`src/work/journal.ts`, `capture-workflow.ts` and `runner.ts` own the resumable local workflow:

| Phase | Meaning / stable next operation |
|---|---|
| PREPARED | Re-encoded private derivative hashed; no acknowledged slot |
| RESERVED | Signed upload slot known; PUT not acknowledged |
| UPLOADED | Bytes PUT; completion not acknowledged |
| COMPLETED | Verified capture known; local upload bytes no longer needed |
| PERMITTED | Service-processing decision recorded for the capture |
| STARTED | Durable run known; poll/recover that run |
| SUCCEEDED / FAILED / CANCELLED / ABANDONED | Terminal outcome; no automatic new intended analysis |

Work is recorded before external effects. Unknown outcomes preserve the recovery path; idempotent downstream operations are retried under their actual contract. The reservation step is not perfectly idempotent: a lost response costs a daily slot until it expires server-side. Byte-range resume is not offered.

The journal distinguishes retry, server-wait and user-action blockers and respects `notBefore`. Foreground reconciliation is not a promise of arbitrary background execution on either operating system. A corrupt journal is dropped and server run discovery can recover known account work; it cannot recover a derivative that never reached a capture or a lost guest credential.

## Local data inventory

| Storage | Data | Safety / lifetime |
|---|---|---|
| Platform secure store | Versioned credential record including bearer token | Never telemetry, logs, preferences or a URL. Clear on the appropriate sign-out/deletion path. Reinstall behavior needs device qualification |
| App-private work journal | Principal/op/capture/run/report IDs, derivative reference/digest/size, consent choice/version, phases, retry counters/timing, **upload URL and expiry/limits** | A signed upload URL is a scoped capability. Never log the journal. Outgoing-principal purge and terminal pruning follow implementation |
| Private derivative files | Re-encoded upload bytes | Delete when no longer needed; account changes and orphan cleanup must not expose another principal's file |
| Downloaded images/exports | Authorized image/PDF bytes and private local file path | Re-fetch with current authorization; temporary share files are cleaned up. Already externally shared copies cannot be recalled |
| Preferences | App chrome locale/theme and approved non-sensitive settings | Not a credential/report cache; do not add private payloads casually |
| In-memory controllers | Report views, pending UI state, current credit/job observations | Fence by current principal/epoch. Do not render late previous-account results |

The journal keeps active entries rather than dropping unfinished work to make room; terminal entries are pruned under its bounded retention policy. Its current seven-day terminal age and entry target are implementation values, not approval of public personal-data retention.

## Image and evidence presentation

Native preparation uses platform picker/camera and reviewed bounded conversion. The uploaded derivative's bytes determine its digest. Crop/rotation/EXIF handling must agree with the server's coordinate lineage. Draw overlays only when frames match; do not label crop margins as physical page margins or replace a missing retained original with synthetic lettering.

`@princess/report-core` provides safe formatting, EN/SV report copy and `buildDossier()` in server order. It does not select new highlights, calculate percentiles or synthesize text. Native layout uses accessibility primitives, not the web renderer. Text scale, screen readers, gestures, tablets and actual camera formats still require app-driving/device acceptance.

## Commerce and Premium

Store updates are observations, not entitlements. The backend binds a verified transaction to the application account and grants credit durably before transaction completion. Preserve the chosen Apple/Google completion owner; never add an independent auto-consume path. A pending/Ask-to-Buy transaction is not failed or granted.

Premium offer, credit reservation, generation status and saved output are separate states. The client reads the validated saved overlay; no generation on read, re-open or export. Account switch and revoked image/AI permission must invalidate old views. Actual native store proofs, provider callbacks and finish/consume recovery need sandbox/device evidence.

## Links, pushes and files

Security-sensitive URI parsing uses the repository's strict `parseUri`; do not replace it with unchecked platform/global URL parsing. A link is a navigation hint, not authorization. Validate the destination and fetch current access after cold/warm start. Keep incoming auth callback checks separate from generic report links.

Push installation belongs to the current principal and environment. Tokens are not printed or used as business identity. A tapped notification reopens by fetching authorized state; denied notification permission must not break report recovery. Actual APNs/FCM delivery remains separately gated.

PDFs are fetched using authenticated API transport, then shared as private temporary files through the native share port. Opening a bare protected export URL in another app does not send the bearer credential. Never forward that credential to a presigned object-store origin.

## Modification checklist

Test interrupted effects at every journal transition; expired/changed credentials; late account responses; withdrawn permission; replayed store events; image erasure; export failure; denied permissions; malformed links; and missing/zero/uncalibrated facts. Use the [testing guide](../development/testing.md) to distinguish controller evidence from native UI/device evidence.