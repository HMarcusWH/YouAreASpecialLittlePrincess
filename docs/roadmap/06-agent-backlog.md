# 06 — Agent backlog and review boundaries

Status: all tasks are planned. Machine-readable dependencies are in [tasks.json](tasks.json). No task below is marked complete by the existence of this roadmap.

## How to execute

One task should normally produce one bounded PR, or a short PR series if the scope requires it. A task can be implemented behind a disabled capability while an owner gate remains open. Code completion, empirical validation, rights approval and production enablement are separate statuses.

Read the owning spec, inspect the current code, record the actual base commit, implement the smallest end-to-end slice, add negative tests, run relevant checks, and document rollback. Never manufacture production data, consent, API calls or successful tests to satisfy an acceptance field.

Existing baseline commands are `python tools/generate_feature_contract.py --check`, `ruff check src tests tools`, `python -m compileall -q src`, and `pytest -q`. Product tests and frontend commands below are to be created and documented by their tasks; they are not claimed to exist today.

## Foundation

### T00 — Establish a genuinely green baseline

Owner: maintainer/platform. Inspect main CI run `36168879709`, fetch job/step logs and diagnose the actual failure. Account billing, runner availability and permissions are owner fixes if that is the evidence; do not guess. Run lint, compile, schema drift, unit tests, installed-wheel smoke tests and the declared Python matrix. Establish dependency locks/pins and a supported Node LTS selection for later app work.

Acceptance: evidence of executed checks on the reviewed commit; unresolved baseline failures documented and blocking release; no bypassed branch protection, hidden lint exclusions, or dropped interpreter support without an explicit decision. A historical '91 passed locally' is not today's CI result.

### T01 — Publish product contracts and runtime capability isolation

Owner: contract steward. Add reviewed JSON schemas plus generated Python/TypeScript interfaces for analysis references, EvidenceBundle, ReportDocument/ViewModel, comparison, and Premium input/output. Add method capability/dependency manifest. Preserve current aggregate feature semantics; resolve future schema issues only with scoped amendments.

Acceptance: positive and negative fixtures; type generation reproducible; Free installation/import/execution with provider credentials absent and provider egress denied; learned dependencies excluded transitively; missing/uncalibrated/locked/pending states distinguished. Schema changes need migration notes.

### T02 — Persistence, identity and authorization

Owner: backend. Implement the first tables in [01](01-data-architecture.md): ownership/session/writer, assets/sample/capture, runs/measurements/regions, reports, jobs/outbox and version references. Add migrations and managed-auth adapter; no custom password implementation.

Acceptance: aggregate JSON/projections committed atomically; duplicate features rejected; cross-run/cross-owner region links rejected; non-owner DB role/RLS tests; guest-to-account ownership transition; migration and restore smoke tests. Reference/member access remains service-only.

### T03 — Rights, consent and collection manifests

Owner: product/data steward with backend. Implement purpose-specific consent/withdrawal records, source-license manifests, proposed retention configuration and cohort definitions. Draft original Swedish/English collection prompts and participant guidance. All external sources remain pending until their exact rights are approved.

Acceptance: no prechecked contribution/public-sharing grant; declined contribution does not reduce Free; source code/data/weights reviewed separately; owner-approved pilot agreement and deletion plan before recruiting/processing pilot contributors. Legal conclusions are not delegated to a code test.

## Intake, mechanics, and reports

### T04 — Safe upload and durable analysis jobs

Owner: backend/platform. Add supported raster intake, sanitization, resource limits, transform preservation, private assets, durable jobs/leases and owner-scoped status endpoints.

Acceptance: blank/malformed/oversized/spoofed/rotated inputs handled; source crop/paper distinction preserved; no arbitrary external URL fetch; retry/double-submit publishes one business result; delete-during-run prevents publication; bounded CPU/memory; no private file paths in client errors.

### T05 — Evidence payload and real chart observations

Owner: engine. Add explicit evidence outputs for baseline points, slant observations/histograms, accepted gaps, component distributions and annotation transforms. Keep canonical aggregates unchanged and link evidence to source regions.

Acceptance: real bins/points match aggregate calculations; no fabricated normal curves; crop/resize/deskew round-trip overlays; deterministic ordering and repeatability; no source image mutation; empty evidence has a reason. Cross-frame and false region references fail.

### T06 — Calibration, suitability, and core method repair

Owner: engine/evaluation. Freeze an annotation/evaluation plan; use authorized writer-disjoint pilot data and synthetic known-geometry cases. Validate page boundaries, segmentation, x-height, baseline, slant, spacing and stroke proxies; fix errors exposed by real captures.

Acceptance: report accuracy/coverage/uncertainty by supported task/capture context; record annotator disagreement and repeat-photo sensitivity; empirical confidence only where calibrated; distinguish exact metadata from experimental descriptors. Predeclare numeric tolerances before final evaluation. Unsupported samples are rejected or reduced, not assigned certainty.

### T07 — Bounded high-value classical expansion

Owner: engine. Implement topology and selected shape geometry where validated user-visible output warrants it: skeleton connectivity/endpoints/loops and selected curvature/angularity descriptors. Add one family at a time, reusing context and evidence contracts; do not chase all definitions.

Acceptance: canonical IDs, units, scale conventions, synthetic topology invariants and real-image robustness; no pen-lift/pressure/time claims from a static image; defined-but-absent outputs remain unavailable. This task can be omitted from the first narrow Free alpha if existing descriptors already support a useful report.

### T08 — Versioned display normalization and reviewed content

Owner: engine/content steward. Implement supported mechanical axes with fixed formulas, domain checks, missingness and family weights. Add deterministic captions/geometric style labels. Add a traditional-rule pack only when sources and wording have been reviewed.

Acceptance: monotonicity, zero-denominator, partial-dependency and scale-equivalence tests; no per-user auto-max radar normalization; no double-counted identical signals; missing rules do not become invented personality weights. Traditional evidence labels appear wherever those associations are used.

### T09 — Report assembly and authorized projection

Owner: report/backend. Build immutable ReportDocument assembly from current results, optional axes/reference/rules, and an optional saved Premium overlay. Produce owner, paid and share-grant-specific view models.

Acceptance: complete and partial Free fixtures; zero-reference fixture; entitlement filtering server-side; no hidden paid prose in Free JSON; version manifest/digest; snapshot immutability and explicit revision behavior; report reads make no provider call.

### T10 — Claude Design contract-driven handoff

Owner: product/design. Give Claude Design the schemas, fixtures and [04](04-reports-design.md). Design mobile/desktop report experience, capture/failure states, offer/consent, comparison, sharing and export. Start from synthetic product-state fixtures while backend implementation proceeds.

Acceptance: interactive prototype, reusable components/tokens, keyboard/text/motion states, print/card layouts, no fake personalized blurred results, clear missing-reference states and content/evidence labels. Owner accepts the design before production styling is considered done.

### T17 — Interactive Free web product

Owner: frontend. Implement approved upload/crop/status/report/history/delete flows and shared report components. Use the real API contract, not hardcoded demo scores. Include unsupported-format and no-reference states.

Acceptance: useful first report on mobile/desktop, interactive evidence, honest coverage, persistent authorized history, safe error recovery, no model/network key in frontend, keyboard and screen-reader flow; a failed provider has no effect on Free.

### T21 — Same-content PDF and share-card rendering

Owner: report/frontend. Implement shared print/card renderers using saved ReportDocument projections. Add bounded render jobs, supported page sizes, typography/font loading and cache keys.

Acceptance: Free/Premium/pair/history parity fixtures; PDF text/numbers match UX; actual page render inspection; no clipping; no AI calls; expired/revoked assets cannot leak; no screenshot-stack PDF; user can omit handwriting imagery visibly.

## Reference and comparison

### T11 — Recruit and annotate the owned pilot

Owner: product/data steward, not an autonomous code agent. Recruit the initial distinct writers under the approved protocol, collect controlled/free/repeated captures, verify permissions and annotate a calibration subset. Record recruitment bias and actual counts.

Acceptance: real consent artifacts and participant/capture linkage, declared author/task metadata, protected writer-disjoint splits, no synthetic or duplicated images counted as humans, withdrawal test. Agents may build tooling; they cannot declare participants or signatures collected when they have not been.

### T12 — Candidate corpus ETL and deduplication

Owner: data/backend. Build ingestion of approved owned/licensed sources, source checksums, candidate quality masks, capture/specimen/writer groups and review states. One primary specimen per writer/cohort follows a predeclared policy.

Acceptance: duplicate rotations/resizes do not inflate N; perceptual matching never claims writer identity; rights-denied records cannot enter candidate releases; all input versions traceable; pipeline re-runs idempotently; genuine unusual samples are not excluded just for being unusual.

### T13 — Reference statistics and calibrated distinctiveness

Owner: statistics/engine. Implement tie-aware CDFs, per-feature eligible counts, leave-writer-out queries, uncertainty/coverage and fixed cohort selection. Add conservative selected-feature handling and optional calibrated family distance.

Acceptance: reference claims explicitly scoped; empty/small/constant/tied/missing data cases; no marginal rarity multiplication; no 'best flattering cohort' selection; replayable snapshots; query writer fully excluded; repeated writers/pairs never treated as independent N. Public claims stay disabled until empirical gates pass.

### T14 — Reference releases, drift, withdrawal and rollback

Owner: data/platform. Add build/review/publish/retire states, member/artifact hashes, drift reports and active-version switching. Implement withdrawal lineage, rebuild and rollback to still-authorized releases.

Acceptance: continuous candidates do not mutate old reports; version mismatch rejected; poisoning/duplicate review; consent revoked during build cannot be published; backup restore cannot resurrect removed membership. Human approval gates initial benchmark promotion.

### T18 — Deterministic pair and history comparison

Owner: statistics/report. Build common-feature masks, native-unit differences and family comparisons, plus optional qualified similarity after calibration. Support same-owner Me-v-Me first; other-owner inputs require T22 grants before release.

Acceptance: A/B symmetry, self-distance, directional labels, unit equivalence, zero variance, incomplete coverage and method mismatch tests; no authorship/romantic predictions; no overall percentage without an explicit evaluated mapping; reference absence still permits suitable raw comparisons.

## Premium, sharing and commerce

### T15 — Evidence-bound OpenAI adapter

Owner: Premium/backend. Implement EvidencePacket assembly, strict output schema, versioned prompts, server-only OpenAI adapter, output checks and mocked refusal/error fixtures. Follow [03](03-premium-openai.md).

Acceptance: no image/transcript by default; no arbitrary tools; unknown IDs/extra properties/prohibited outputs rejected; store/retention configuration explicit; provider credential never needed by Free; bounded token/call policy. Live calls require owner-approved account and spend.

### T16 — Model evaluation and generation policy

Owner: evaluation/content. Assemble varied fact packets/adversarial cases, compare approved candidate models on factuality and usefulness, and record real costs/latencies and Swedish/English review. Include no-reference and conflicting-rule cases.

Acceptance: rubric/tolerances fixed before model selection; critical invented-fact/privacy failures block enablement; repeated-case stability assessed; actual account capability tested; no invented snapshot IDs; failure/fallback policy documented. Neither API access nor successful empirical evaluation is assumed by the roadmap.

### T19 — Purchase ledger, entitlements and metered jobs

Owner: backend/commerce. Add hosted web checkout adapter, signed webhook reconciliation, report-specific capabilities, durable Premium jobs/leases, budget reservations and refund/credit restoration.

Acceptance: test mode first; duplicate/out-of-order/refund events; no trust in browser redirect; one intended business fulfilment; timeout ambiguity cost bounded; no double customer charge; Premium failure preserves Free. Real prices/accounts/terms require owner approval.

### T20 — Premium and paid pair experience

Owner: frontend/Premium. Integrate the offer, third-party processing disclosure/permission, checkout/job states, saved result and optional pair narrative into the existing report experience.

Acceptance: inspect packet preview/privacy copy, no counterfeit precomputed teaser, refusal/failure/refund paths, no model calls on panel expansion/reopen/export, paid content server-filtered and content parity maintained.

### T22 — Scoped sharing and comparison invitations

Owner: frontend/backend/privacy. Add redacted share grants, card previews, expiring/revocable links, explicit partner authorization and referral events.

Acceptance: no original text or partner identity by default, link guessing/metadata leakage tests, revoked grants stop serving, pair reuse needs its own permission, no contact harvesting; analytics distinguishes share initiation from confirmed referral activity.

## Launch

### T23 — End-to-end QA and threat-model tests

Owner: independent review/test agent. Test the full user and adversarial paths in [05](05-release-operations.md), with real authorized samples on supported devices. Check visual/report accessibility and numerical/evidence parity.

Acceptance: successful journeys across Free/Premium/pair/history; all critical privacy/billing/security regressions fixed; unsupported contexts honestly limited; no-AI runtime tests pass; benchmark/model claims enabled only with their evidence. Publish actual latency/cost/coverage results, not predictions.

### T24 — Deployment, recovery and support operations

Owner: platform/product. Deploy staging, isolated worker pools, private storage, DB migrations/backups, secret handling, metering/alerts and support/refund/deletion runbooks. Exercise provider outage and rollback.

Acceptance: restore with deletion tombstones, deletion across derivatives/exports, dead-job reconciliation, cost circuit breakers, reference/prompt/engine rollback, versioned deployment manifest and owner support responsibility. Do not expose production writing in logs/session replay.

### T25 — Owner-reviewed public web v1

Owner: product owner. Review actual gate evidence, approved pricing/terms/privacy, accepted Claude Design implementation, support readiness, claims and optional capabilities. Publish only supported functionality.

Acceptance: explicit sign-off and release notes with supported inputs, feature coverage, benchmark/model versions and known limits. Disabled/unvalidated rarity, rules or visual enrichment are not marketed as delivered. Native apps and advanced post-v1 modules are separate projects, not uncompleted v1 promises.

## Parallel work and merge rules

T00 (CI diagnosis) and T03 (rights/collection planning) can begin immediately. After T01, T02, T05, T10 and schema/fixture-based Premium preparation can proceed without waiting for all 272 features. Real recruitment/annotation can run alongside rendering/client work once safe intake and participant approvals exist.

Coordinate edits to `models.py`, canonical schema, contract generation and shared report components through one steward. Do not create competing ad-hoc metric registries. Pin dependent PRs to an agreed contract version and integrate small slices frequently.

A code implementation can pass synthetic tests while its production capability remains disabled. Record this as `IMPLEMENTED_PENDING_VALIDATION`, not `VALIDATED`. Owner-gated tasks need actual evidence and named approval, not an agent-generated approval record.

## Post-v1 backlog

Native capture/store packaging and billing; browser/on-device execution with numerical parity; optional learned OCR/visual assist outside strict Free; signature specialization with separate datasets; actual online stylus timing/pressure; group comparisons; opt-in historical/famous samples with rights; calibrated nearest-neighbor matching; monthly/annual recaps where genuine usage exists. Each needs its own scope, safety, rights, cost and validation review.
