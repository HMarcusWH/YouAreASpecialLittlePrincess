# 10 — Web client, API and shared report integration

[Index](00-index.md) · [Report design](04-reports-design.md) · [Boundaries](09-connectors-and-provider-boundaries.md) · [Mobile](11-mobile-architecture.md) · [Web release](../release/web.md).

## Architecture default

Use Next.js/React/TypeScript for the web presentation, session boundary, public landing pages and controlled share metadata. FastAPI owns application authorization, consent, jobs, ledger and report publication. Next route handlers may proxy authenticated requests and manage secure cookies; they must not become a second commerce engine, query private tables directly or issue model calls. Native clients talk to the same versioned application API through their own token transport.

T28 establishes a pinned pnpm workspace and Node/toolchain matrix. Preserve the inherited Node baseline until compatibility is actually tested. T01 supplies generated schemas and types; T17 must not type an API response with `as ReportDocument` and treat that as runtime validation. Validate payloads at trust boundaries and reject unknown schema majors.

## API surfaces and ownership

| Route family | Use case | Implemented by |
|---|---|---|
| `/v1/me`, identity/session binding | Resolve internal principal; guest upgrade; account deletion request | T02 |
| `/v1/permissions`, grants/withdrawals/status | Persist/query append-only purpose, policy, scope and effective permission state for service, retention, AI, contribution and sharing | T02 |
| `/v1/samples`, `/{id}/upload`, `/{id}/complete` | Reserve asset, issue bounded upload authorization, bind immutable verified bytes, enqueue decoding | T04 |
| `POST /v1/analyses` | Idempotently start deterministic analysis from an authorized completed sample/capture and return the AnalysisRun/job reference | T04 |
| `/v1/jobs/{id}` | Owner-scoped status, progress stage and safe error code | T04 |
| `/v1/reports/{id}` and history pagination | Authorized immutable revision projection, not raw DB rows | T09/T17 |
| `/v1/reports/{id}/premium` | Validate consent/credit/suitability, reserve one business fulfilment | T15/T19 |
| `/v1/commerce/catalog`, purchases, claim/status | Server catalog mapping, Stripe intent, native transaction verification/recovery | T19 |
| `/v1/comparisons` | Authorized common-feature comparison of specific revisions | T18/T22 |
| `/v1/report-exports`, `/{id}` | Async PDF/card creation, authorized retrieval | T21 |
| `/v1/share-grants`, invitations | Scope, preview, redeem, revoke; no implicit image or Premium consent | T22 |
| `/v1/contributions`, withdrawals | Contribution-specific permission plus corpus lineage/release invalidation; uses the T02 permission ledger | T02/T12/T14 |
| `/v1/devices`, notifications | Push token binding and notification preferences | T29/T24 |
| `/v1/reports/{id}/feedback` | Owner-bound, redacted report-content feedback with retention/deletion and restricted support review | T24 backend; T20/T30/T31 clients |
| `/v1/webhooks/{provider}` | Raw signature verification then durable inbox | T19/T24 |

These are planned route contracts, not endpoints that exist today. T01 freezes DTOs; each owning task adds route schemas, operation IDs, status/error codes and generated clients. Follow existing [05](05-release-operations.md) semantics, including safe intake and deletion. Partner comparison is a distinct permission purpose from ordinary sharing; invitation or share state never substitutes for an effective partner-comparison grant in the T02 permission ledger. Upload completion and analysis submission are deliberately separate: `/samples/{id}/complete` verifies/promotes immutable bytes and may enqueue decode preparation, while `POST /v1/analyses` is the explicit idempotent business operation that creates or reuses the intended deterministic AnalysisRun/job.

Mutating API calls use server-scoped idempotency keys and a canonical request digest. A reused key with a different body fails. Responses identify job/report revision separately; `202` acceptance is not successful inference. Use cursor pagination with stable ordering, bounded page sizes and ownership checks. Return machine error codes plus localized UI actions; keep traces and internal paths private.

## Web session and request safety

Keep long-lived credentials out of localStorage and URLs. Use the chosen identity adapter, secure HttpOnly SameSite cookies for browser sessions, CSRF/origin checks for cookie-authenticated mutations, explicit CORS allowlists for any cross-origin API and anti-replay login state/nonce. Forward only necessary identity to FastAPI, which verifies authorization independently. Avoid caching personalized responses in shared Next/CDN caches; owner/report scope must be part of any permitted application cache.

A route parameter, invitation token or purchase redirect is untrusted. Validate redirect destinations and deep-link targets. Generic public share metadata contains only permitted redacted fields. Revocation must prevent future protected report/asset issuance; previously downloaded images cannot be recalled.

## Client state implementation

Separate persisted server state from transient UI state. Use a query/cache library chosen and pinned in T17; key by principal, report ID, revision and visibility epoch. Clear sensitive caches on sign-out/account switch and reject late responses for the previous principal. Retry idempotent reads; never blindly replay a paid mutation or upload-completion event.

Implement explicit capture, uploading, queued, running, partial, complete, failed, deleted and revoked flows. Resume a known server job after refresh; do not generate a new analysis simply because the route remounted. Begin with bounded polling and backoff; add SSE only with owner-scoped reconnect and cursor semantics. Do not hold a web request open during CPU extraction or model inference.

## Report and rendering contract

`ReportDocument` is stored content. `ReportViewModel` is a server-authorized presentation. Use `packages/report-core` for safe formatting, section state mapping and chart specifications; it does not calculate new percentiles or model text. `packages/report-web` provides web and print components. A native implementation consumes the same semantic data but uses native accessibility/layout primitives.

Display actual evidence arrays, never reconstruct a histogram from mean/std. Fixed radar axes require validated mappings and partial-state treatment; a missing value is not plotted as zero. Every visual carries evidence class, unit, missing/calibration state, text equivalent and method link. Swedish and English text must fit without fabricated abbreviations; localize display, not fact IDs.

## Test-first coding slices

T17 should land: (1) fixture-backed navigation/state UI; (2) real safe upload/job integration; (3) authorized report/evidence components; (4) account/history/deletion; (5) inaccessible/partial/error cases and responsive accessibility. T20 adds paid states; T21 reuses saved projections for export; T22 adds disclosure-aware share routes. No hidden paid text in a Free response, fake personalized blur or permanent placeholder score.

Use unit/fixture tests, generated-client contract tests and Playwright journeys. Verify refresh during a job, auth expiry, cross-account URLs, stale cache after sign-out, provider-disabled Free, keyboard navigation, reduced motion, long labels, no-reference report, zero values, revocation during export and duplicate purchase clicks. The complete test matrix and command lifecycle are in [16](16-testing-evals-and-quality-gates.md).
