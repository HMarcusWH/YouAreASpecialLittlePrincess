# 05 — Product API, security, payments, and operations

Status: proposed deployment/release design. See [07](07-evidence-register.md) for primary sources and [06](06-agent-backlog.md) for implementation gates.

## 1. Repository boundaries

Preserve `src/princess_graphology/` as a pure library. Add product surfaces incrementally:

```text
apps/api/                 HTTP, auth, permissions, persistence, outbox
apps/workers/analysis/    CPU-only safe extraction
apps/workers/premium/     OpenAI adapter, evidence validation, metering
apps/web/                 responsive interactive report UX
apps/render/              isolated Playwright PDF/PNG jobs
packages/contracts/      generated Python/TypeScript/JSON interfaces
packages/report-ui/      shared web/print/card components
migrations/              database schema and rollback tests
content/                  reviewed localization, templates, rule packs
reference/                source/cohort manifests and build code, NOT private samples
evals/                    public-safe synthetic fixtures and test definitions
```

These paths are planned; do not claim they already exist. Keep input bytes, private samples, production feature vectors and participant consent records outside Git. Add repository exclusions, secret scanning and safe fixture reviews. Public datasets are not automatically safe to redistribute in CI.

## 2. Proposed API boundaries

| Endpoint family | Purpose | Required safeguards |
|---|---|---|
| `POST /v1/samples` | Create private sample and upload authorization | Auth/guest quota, owner binding, media/size constraints. |
| `POST /v1/samples/{id}/complete` | Confirm uploaded object and enqueue decoding | Verify storage metadata, owner and checksum; never trust client MIME. |
| `POST /v1/analyses` | Start deterministic analysis | Idempotency key, sample access, transform config/version, resource budget. |
| `GET /v1/jobs/{id}` | Poll/subscribe to processing state | Owner/grant access, no private exception dumps. |
| `GET /v1/reports/{id}` | Return authorized interactive view model | Server-side entitlement and disclosure projection. |
| `POST /v1/reports/{id}/premium` | Authorize a bounded enrichment job | Paid capability, exact consent scope, quality, model/spend policy. |
| `POST /v1/comparisons` | Create pair or history report | Explicit permission for both inputs; same-method/coverage checks. |
| `POST /v1/report-exports` | PDF or selected-card export | Snapshot/access verification, output quota, cache/dedupe. |
| `POST /v1/share-grants` / `DELETE /v1/share-grants/{id}` | Disclose selected content and revoke it | Field allowlist, preview, expiring token, partner permission where applicable. |
| `POST /v1/contributions` / `DELETE /v1/contributions/{id}` | Separate corpus grant/withdrawal | Purpose/policy version, author authority, lineage and release invalidation. |
| `POST /v1/billing/checkout` | Start purchase | Server-owned SKU/price; no arbitrary client-supplied price. |
| `POST /v1/billing/webhooks/{provider}` | Reconcile purchase/refund lifecycle | Raw-body signature verification, duplicate/out-of-order handling. |
| `DELETE /v1/samples/{id}` / `POST /v1/me/deletion` | Erasure workflow | Re-auth where appropriate, descendant artifacts, corpus/shares/backup tombstones. |

A separate privileged administration surface reviews licenses/candidates, publishes benchmarks, manages prompt/rule releases and processes support/refunds. Normal clients never query corpus member tables or supply arbitrary cohort SQL.

Return structured error codes and recoverable next actions: invalid media, image too large, not enough usable writing, ambiguous page/crop, unsupported context, no eligible reference, missing entitlement, revoked permission, provider unavailable, export failed. Keep detailed stack traces private and redacted.

## 3. Safe intake and numerical integrity

Initial supported uploads are decoded raster handwriting photographs/scans. Start with JPEG/PNG; support common phone formats only after an audited conversion path exists. Do not pretend an unrecognized HEIC file is a failed handwriting analysis. Reject archives, SVG/scripts, arbitrary remote image URLs, and multi-page documents until specifically implemented.

Enforce compressed byte size and decoded pixel count separately. Strip metadata after applying legitimate orientation; generate server-owned filenames; use isolated decoding with memory/CPU/time limits. Protect decompression bombs, malformed files, path traversal, content-type spoofing and public bucket access. OWASP recommends layered checks rather than trusting extension or MIME alone. [S19]

Proposed starting limits such as 20 MB compressed/24 MP decoded are engineering settings to benchmark and revise, not proof of adequate safety. Run analysis in a worker with constrained resources and cancellation checks. Do not execute uploaded content or fetch user-selected URLs from internal networks.

Preserve original/corrected coordinate transforms. Deskew is not deslant: removing the writer's slant would destroy a target measurement. Automatic crop must not erase real margins or reinterpret crop boundaries as paper edges. For uncertain page geometry, ask for a corrected crop or withhold page-relative claims.

## 4. Jobs and reliability

Use a transactional outbox and durable job records. A worker claims a short-lived lease, records attempt metadata, heartbeats and publishes a terminal result atomically. PostgreSQL queue-like locking can support an initial implementation; keep long CPU/model work outside a held SQL transaction. [S26]

Separate queues/pools for decode/extraction, model generation, export and reference builds so a large reference rebuild cannot starve user reports. Apply per-owner quotas, global concurrency caps and a circuit breaker for Premium/provider outages. Free report generation remains operational when the OpenAI key is absent or a provider is down.

Use idempotency on business operations, not unsafe assumptions about network delivery. Reconciliation finds paid-but-unfulfilled jobs, abandoned reservations, orphaned assets and exports referencing revoked grants. Jobs must check deletion/consent state again before publication.

## 5. Payment and entitlement model

Start with per-analysis/pair-generation entitlements. No subscription is required for the first complete product. Pricing and bundles are owner decisions after measured costs and demand; this roadmap does not approve a consumer price.

The selling price must account for API usage, failed/retried jobs, CPU extraction, object storage, exports, authentication, payment fees, taxes, refunds and support. Zero-AI Free still consumes infrastructure. Avoid unlimited unauthenticated CPU/PDF endpoints. Generate Premium only after confirmed entitlement, not for every free visitor in anticipation of purchase.

For web v1, use a payment adapter with a hosted checkout and webhook reconciliation. Stripe documentation specifically covers signature verification, duplicate events and request idempotency; implement both application and provider safeguards. [S23, S24]

Entitlements attach to a report/operation, not merely a UI flag. Store the provider transaction/event IDs, currency, amounts and fulfilment/refund state with uniqueness constraints. A browser success redirect is not payment proof. Test replay, reordering, duplicate clicks, disconnects, refunds and delayed processing.

Native app distribution adds current storefront/billing, purchase restoration, data-disclosure and third-party-AI consent requirements. Review the applicable Apple/Google policies at that release; do not assume a web checkout can simply be embedded worldwide. Apple's current guidelines are included as a verification starting point, not a blanket compliance finding. [S25]

## 6. Privacy and data lifecycle

Prepare a data inventory and threat model before public beta. Document purpose, legal basis, access, processors, storage location, retention and deletion for every table/asset class. Service processing and optional reference donation need distinct controls; permission should be specific and withdrawable where consent is relied on. [S20, S21]

Treat images, crops, feature vectors and reports as private personal data unless a defensible anonymization assessment establishes otherwise. Pseudonymization, hashing and hiding a name are not automatic anonymization. Unique-identification uses can materially change the biometric analysis; leave writer identification and handwriting-twin services out of v1. [S22]

**Proposed retention policy, requiring approval before launch:** ephemeral guest originals/derivatives are removed after successful processing and a short documented retry window, capped at 24 hours; a user explicitly choosing visual history can retain the approved images for 30 days initially. Retaining beyond that requires a visible saved-history choice and an approved inactivity/deletion policy. Corpus contributions have their own agreed retention. Payment records follow applicable legally required retention separately.

These are proposed product settings, not legal mandates. Make the exact live policy visible. A crop, thumbnail or annotated background containing handwriting counts as an image; 'delete original' cannot hide retained readable copies. When images are deleted, numerical reports may remain under the user's chosen service-retention policy, but visual evidence becomes unavailable and re-analysis may require a new upload.

Deletion covers original objects, derivatives, versions, exports, CDN caches, share grants, reference membership and pending jobs. Maintain tombstones through backup expiry and restore; prevent background jobs from recreating deleted content. Disclose third-party retention accurately rather than promising instantaneous deletion from all providers. Already downloaded exports cannot be recalled.

Use TLS, private encrypted storage, expiring signed asset access, least privilege and audit trails. No production samples in analytics/session-replay tools. Do not claim GDPR compliance merely because these engineering controls exist; controller decisions, contracts, lawful basis and transparency still require review.

## 7. Security test matrix

At minimum: cross-account report/sample/export access; forged comparison permissions; revoked partner grants; guessed job IDs; public-link field leakage; prototype pollution/HTML injection in generated text; prompt injection; uploaded archive/SVG masquerading as an image; pixel bombs; stale signed links; payment replay/out-of-order/refunds; API spending abuse; concurrent premium generation; deleted data republished by a worker; backup restore resurrecting erased rows.

RLS tests use the actual non-owner application role. Premium workers cannot mutate canonical measurements or read arbitrary unrelated accounts. Render workers can resolve only authorized internal assets and cannot browse the internet on behalf of content. Reference build roles do not expose member vectors to user endpoints.

## 8. Product and operating metrics

Track distinct events and denominators: upload started/completed; quality rejection; analysis completed; useful Free report viewed; benchmark eligible; comparison completed; purchase confirmed; Premium succeeded/refused/failed/refunded; report reopened; share initiated; artifact exported; invitation accepted; referred first analysis completed; deletion completed.

Record engine/model/benchmark/template versions, latency, infrastructure usage and feature coverage, but not writing text, image URLs, personal attributes or complete feature vectors in general analytics. Attribute referral activity only where supported by actual events; do not label every export a successful social share.

Review report completion and usefulness, repeat/comparison use, purchase conversion among eligible offers, successful paid fulfilment, refund reasons, p50/p95 latency, cost per successful analysis, quality-rejection rates by supported capture cohort, benchmark coverage and permission/deletion failures. Set performance/conversion targets after a measured beta baseline; do not invent 'industry-standard' percentages.

## 9. Release gates and rollback

**Free alpha:** hosted core checks green; safe intake; actual-method manifest; no-AI isolation; numerical/region validity; useful partial reports; access/delete flows; same-content PDF/card proof; declared script/capture limits.

**Reference beta:** source/consent approval; writer-level deduplication and holdout; calibrated geometry; fixed reference plan and reproducible release; cold-start/uncertainty/multiplicity behavior; withdrawal/rebuild rehearsal. Without these, suppress reference claims while keeping Free available.

**Premium beta:** approved account/data controls/price/budget; strict schema and semantic checks; adversarial/human eval; paid fulfilment/retry/refund reconciliation; no model calls on view/export; Free survives provider failure.

**Public web v1:** real mobile/desktop/browser QA; accessibility and export inspection; security test matrix; privacy notices and deletion; restore/rollback exercises; source/code/license inventory; monitoring, alerts, support and incident runbooks. Require owner sign-off rather than an agent self-declaring legal or statistical validation.

Rollback independently by engine/method version, active benchmark pointer, rule pack, prompt/model policy and renderer template. Retired or withdrawn reference data must not become active through rollback. Keep report snapshots traceable to their original versions and disclose invalidated evidence rather than silently rewriting it.
