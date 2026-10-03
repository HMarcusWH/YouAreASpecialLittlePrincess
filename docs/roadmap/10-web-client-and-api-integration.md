# 10 — Web client, API and shared report integration

[Index](00-index.md) · [Report design](04-reports-design.md) · [Boundaries](09-connectors-and-provider-boundaries.md) · [Mobile](11-mobile-architecture.md) · [Web release](../release/web.md).

## Architecture default

Use Next.js/React/TypeScript for the web presentation, session boundary, public landing pages and controlled share metadata. FastAPI owns application authorization, consent, jobs, ledger and report publication. Next route handlers may proxy authenticated requests and manage secure cookies; they must not become a second commerce engine, query private tables directly or issue model calls. Native clients talk to the same versioned application API through their own token transport.

T28 establishes a pinned pnpm workspace and Node/toolchain matrix. Preserve the inherited Node baseline until compatibility is actually tested. T01 supplies generated schemas and types; T17 must not type an API response with `as ReportDocument` and treat that as runtime validation. Validate payloads at trust boundaries and reject unknown schema majors.

## API surfaces and ownership

The callable method/path/request inventory is now the source-generated [current API reference](../reference/api-routes.md), with [authorization/error/retry semantics](../reference/api.md). Do not implement against the historical `/v1/samples`, `/v1/jobs/{id}`, `/v1/commerce/catalog`, `/v1/devices` or generic `/v1/webhooks/{provider}` sketches: current handlers use uploads, analyses, catalog, account-bound push installations and rail-specific payment events.

The API owns identity/principal resolution, purpose decisions, immutable intake, report projections, account-backed history, ledger, export, feedback and installation state. Shared clients consume runtime-guarded responses. Product schema components are generated separately from endpoint routing.

T30A added run discovery, report-scoped deletion, authorized retained source-image delivery, exact notice catalogue delivery and unsaved same-owner comparison. Persisted invitations, partner grants and pair Premium remain T22 work; no proposed share/contribution route is callable merely because a roadmap names it.

Upload completion and analysis start are separate. Completion binds verified immutable bytes and returns a capture; `POST /v1/analyses` creates/reuses the intended run. Idempotency is operation-specific: completion is digest-bound, analysis start is capture/config-bound, permission and feedback requests carry decision IDs, and an upload reservation can consume another quota slot after a lost response. A 202 response is acceptance, not completed inference. Never blindly replay an ambiguous paid request.

## Web session and request safety

Keep long-lived credentials out of localStorage and URLs. The implemented web boundary keeps one opaque API credential in a server-only host cookie; `session-policy.ts` centralizes the HttpOnly/SameSite/path/Secure issue-and-clear attributes so sign-out cannot drift from issuance. `session.ts` exposes the credential only to server-side API construction/proxy code and never parses provider claims. A local-device sign-out clears only this browser transport; sign-out-everywhere first invokes the application `/v1/me/logout-everywhere` fence and then clears the cookie. Neither action implies provider-side revocation. Use the chosen identity adapter later for real sign-in/refresh, keep CSRF/origin checks for cookie-authenticated mutations, explicit CORS allowlists for any cross-origin API and anti-replay login state/nonce. Forward only the opaque credential to FastAPI, which verifies identity and authorization independently. Avoid caching personalized responses in shared Next/CDN caches; owner/report scope must be part of any permitted application cache.

A route parameter, invitation token or purchase redirect is untrusted. Validate redirect destinations and deep-link targets. Generic public share metadata contains only permitted redacted fields. Revocation must prevent future protected report/asset issuance; previously downloaded images cannot be recalled.

## Client state implementation

Separate persisted server state from transient UI state. Use a query/cache library chosen and pinned in T17; key by principal, report ID, revision and visibility epoch. Clear sensitive caches on sign-out/account switch and reject late responses for the previous principal. Retry idempotent reads; never blindly replay a paid mutation or upload-completion event.

Implement explicit capture, uploading, queued, running, partial, complete, failed, deleted and revoked flows. Resume a known server job after refresh; do not generate a new analysis simply because the route remounted. Begin with bounded polling and backoff; add SSE only with owner-scoped reconnect and cursor semantics. Do not hold a web request open during CPU extraction or model inference.

## Report and rendering contract

`ReportDocument` is stored content. `ReportViewModel` is a server-authorized presentation. Use `packages/report-core` for safe formatting, section state mapping and chart specifications; it does not calculate new percentiles or model text. `packages/report-web` provides web and print components. A native implementation consumes the same semantic data but uses native accessibility/layout primitives.

Display actual evidence arrays, never reconstruct a histogram from mean/std. Fixed radar axes require validated mappings and partial-state treatment; a missing value is not plotted as zero. Every visual carries evidence class, unit, missing/calibration state, text equivalent and method link. Swedish and English text must fit without fabricated abbreviations; localize display, not fact IDs.

## Test-first coding slices

T17 has landed fixture-backed navigation/state UI, real safe upload/job integration, authorized report/evidence components, saved history/deletion/settings, account mail preferences, automated responsive/accessibility qualification and a hardened provider-neutral web credential transport boundary. Its remaining work is real provider/account qualification plus production PKCE/session refresh and cross-device recovery after ADR-002; the accepted T10 design is already integrated. T20 adds paid states; T21 renders saved projections and PR #34 completes the accepted Dossier print/share integration plus full-size render inspection, while machine status remains open until hard predecessor T17 closes; T22 adds disclosure-aware share routes. No hidden paid text in a Free response, fake personalized blur or permanent placeholder score.

Use unit/fixture tests, generated-client contract tests and Playwright journeys. Verify refresh during a job, auth expiry, cross-account URLs, stale cache after sign-out, provider-disabled Free, keyboard navigation, reduced motion, long labels, no-reference report, zero values, revocation during export and duplicate purchase clicks. The complete test matrix and command lifecycle are in [16](16-testing-evals-and-quality-gates.md).
