# Product roadmap: from canonical measurements to a finished app

**Version:** 1.1 proposed build baseline  
**Research cut-off:** 2026-09-25  
**Repository baseline:** `8f2ec7b07f23f7b3613ccc71576714f3c245e7a0`  
**Scope of this change:** documentation and build plan, not implementation, dataset acquisition, or a claim of validated handwriting/personality accuracy.

## Start here

Build **one deterministic measurement engine, one versioned report system, and two runtime tiers**. The report is an interactive application experience. PDF is an export of that experience; social cards are selected views of the same data.

Read in this order:

1. [Data architecture and contracts](docs/roadmap/01-data-architecture.md).
2. [Corpus acquisition, reference statistics, and continuous updates](docs/roadmap/02-corpus-benchmarks.md).
3. [Premium OpenAI orchestration](docs/roadmap/03-premium-openai.md).
4. [Reports, comparison UX, and Claude Design handoff](docs/roadmap/04-reports-design.md).
5. [API, security, payments, operations, and release gates](docs/roadmap/05-release-operations.md).
6. [Agent backlog and dependencies](docs/roadmap/06-agent-backlog.md), also available as [machine-readable tasks](docs/roadmap/tasks.json).
7. [Evidence register and corrections to earlier research](docs/roadmap/07-evidence-register.md).
8. [Premium selector, question and soft-value database](docs/roadmap/08-premium-question-selector-database.md).

`R`, `P`, and `S` references throughout this package resolve in the evidence register. `R` means observed repository state, `P` means supplied project research, and `S` means externally verified source. An architectural choice or proposed test threshold is a **design decision**, not an empirical finding.

## 1. Fixed product requirements

### Free means zero runtime AI

Free uses classical image processing, geometry, descriptive statistics, and authored deterministic rules. It must work without any OpenAI/Anthropic credentials, model downloads, neural OCR, SVM classifiers, learned embeddings, or other learned inference. AI-assisted development and Claude Design are development tools, not Free runtime dependencies.

Zero AI does **not** mean zero hosting cost, necessarily offline, or necessarily on-device. The initial Python engine can run on our CPU workers. We must explain upload/storage behavior honestly. Local browser processing is a later optimization requiring parity tests, not a precondition for launch.

The existing database's `free_compute=true` means no paid generative call; it is not sufficient to enforce the user's stricter zero-AI requirement. Add a method-level capability manifest and resolve dependency chains. Do not silently rewrite the historical schema to pretend its existing labels mean something different. [P03]

### Premium adds interpretation, not new truth

Premium begins from the same approved deterministic analysis and reference statistics, then sends **the authorized handwriting image + deterministic facts + verified database outliers + constrained selector candidates + a frozen question battery** in one vision-capable OpenAI call. OpenAI chooses among predetermined values and fills bounded evidence-linked soft-text fields. It cannot change measurements, calculate its own rarity, assign unsupported percentile ranks, fabricate source material, or turn a traditional association into a validated personality assessment.

A paid analysis is saved once and reopened without another model call. Expanding a panel, changing the visual theme, sharing a card, and exporting PDF must not trigger fresh inference. Paid follow-up chat and visual enrichment are post-v1 capabilities with separate budgets and consent.

### The report is the product

All three report kinds—individual, pair comparison, and historical comparison—live in the UX. Free and Premium are entitlements on content, not separate render pipelines. Each report can be exported as PDF with the same available content, numbers, qualifications, and version identifiers. Sharing a selected card is separate from sharing the entire report or original handwriting.

The owner receives the complete content they have unlocked in-app; nothing is made PDF-only. Free reports can also be exported. The purchase buys deeper analysis, not permission to retrieve an already displayed number.

### Distinctive handwriting is not a psychological diagnosis

Separate measured geometry, computational proxies, cohort-relative statistics, and playful/traditional interpretation. No intelligence, psychiatric, deception, criminality, hiring, or relationship-outcome claims. The primary study cited in the evidence register concerns graphology's personnel-selection validity and highlights the script-content confound; it is not a validation of our proposed product. [S28]

No population-wide 'top 1%' or 'one in a million' claim from a convenience sample. 'Special princess' is a brand metaphor; the operational quantity is an unusual **measured handwriting characteristic within a named eligible reference set**.

## 2. Verified starting point

PR #1 has merged. The README registers 64 canonical core features against 272 definitions and leaves 208 definition-only. The pure library has preprocessing, segmentation, shared context, eight measurement stages, strict JSON/region validation, and separate elementary comparison utilities. The PR records 91 earlier local tests; this roadmap does not claim a new execution of them. [R01–R03]

The latest inspected main-branch CI run, `36168879709`, concluded `failure`. Its cause is not established here. Investigating runner/account/configuration issues and actual step logs is task T00. Never disable checks or declare the version matrix verified merely because a PR merged. [R04]

There is no production reference corpus, empirical calibration, product database/API, consumer frontend, payment flow, or Premium adapter established by the inspected baseline. The viral-UX research's 'existing Figma/assets' paragraph explicitly uses assumptions and must not be treated as implementation evidence. [P01]

The supplied JSON exactly matches the repository's schema blob `f8c2bb6ab48852e81ec88b84897fbe44d4f94c1c`. A local structural count gives:

| Definition class | Count | Product treatment |
|---|---:|---|
| CLASSICAL_LOCAL | 171 | Candidate methods for zero-AI execution, subject to implementation and dependencies. |
| DERIVED_RULE | 18 | Candidate deterministic statistics/axes; input dependencies still gate eligibility. |
| OCR_LOCAL | 26 | Disabled in strict Free until a specific non-learned method is audited; not required for v1. |
| SMALL_ML_LOCAL | 2 | Excluded from Free. |
| ONLINE_SENSOR | 55 | Requires actual captured sensor streams, not a photo; outside static-photo v1. |

There are 217 static-image definitions. Neither 217 nor 189 classical/rule candidates is a promise of implemented or valid outputs. Feature availability depends on sample quality, scope, and method status.

## 3. Chosen v1 shape

**Design recommendation:** ship a mobile-first responsive web app first, with reusable TypeScript report components. Native iOS/Android packaging follows a successful web beta; native capture/offline needs can then justify Expo or another wrapper. This replaces the earlier tentative native-first suggestion, not a user requirement. The reason is architectural: a share link, interactive report, and print renderer can share a web component system instead of creating three independent products.

Proposed stack:

- Existing `src/princess_graphology/` remains the pure numerical library.
- Python FastAPI application, PostgreSQL, SQL migrations, private object storage, CPU analysis workers.
- A durable PostgreSQL job/outbox system initially; use leases and bounded workers, not long HTTP requests or unreliable in-process background tasks. PostgreSQL documents `SKIP LOCKED` for queue-like consumers. [S26]
- Separate Premium worker holding the OpenAI credential and restricted egress.
- React/TypeScript web frontend and shared report components; Node/Playwright export worker for PDF/PNG. [S18]
- Managed authentication integrated through an adapter; provider, hosting region, DPA, price, and payment account are owner launch decisions, not values an agent invents.

```text
image -> safe intake -> deterministic AnalysisRun -> immutable measurements
                                      |
                  eligible reference snapshot + approved rule pack
                                      |
                  verified outliers + selector/question database
                                      |
                              ReportDocument v1
                                      |
                   +------------------+------------------+
                   |                                     |
            Free content                    PremiumRequestPacket
                   |                  image + facts + outliers +
                   |                  selectors + question battery
                   |                                     |
                   |                           OpenAI -> validate -> save
                   +------------------+------------------+
                                      |
                          entitlement-filtered views
                             /        |         \
                         app UX    share cards    PDF
```

Continuous corpus ingestion is a separate pipeline. An ordinary upload is not automatically a benchmark donation, a public example, or training material.

## 4. Release slices, not a 272-feature completion campaign

| Release | User-visible completion | Dependencies and stop conditions |
|---|---|---|
| Foundation | Reproducible core and published contracts | T00–T03. Hosted CI diagnosis, runtime isolation, schema/version rules. |
| Free alpha | Upload, quality feedback, interactive mechanical report, save/delete, basic exports | T04–T10, T17, T21. A small reliable subset is sufficient; unavailable metrics are explicit. |
| Reference beta | Qualified comparison against a named corpus, individual and Me-v-Me comparison | T11–T14, T18. Real consented samples and calibration; no fabricated cold-start percentiles. |
| Premium beta | Payment, explicit API disclosure, one multimodal evidence-bound generation, report reuse | T15–T16, T19–T22, T26. Interpretation database, account access, budget, legal and evaluation gates. |
| Public web v1 | Free, Premium, pair comparison, sharing, PDF parity, support and recovery | T23–T25. Security/privacy tests and real-device QA passed. |
| Post-v1 | Native apps, learned visual assist, signature specialization, online capture, groups/Wrapped | Separate scope/rights/evaluation decisions; not blockers for web v1. |

Claude Design starts against report contracts and fixtures **in parallel**, not after every extractor is finished. Corpus recruitment also starts early. A missing licensed population benchmark blocks rarity claims, not useful Free measurements or a descriptive pair comparison.

## 5. What v1 contains

Free offers safe image upload, user-correctable crop/orientation, explicit image suitability, verified mechanical metrics, visual evidence, descriptive axes where supported, deterministic captions and optional playful style labels, eligible cohort ranks, basic pair/Me-v-Me comparison, share cards, and PDF export. Saved history requires an explicit retention choice.

Premium adds a multimodal interpretation of the same evidence: constrained visual/style selectors, verified-outlier selection, cross-feature explanation, bounded soft values, source-labelled traditional interpretations when an approved rule pack exists, and an optional paid pair narrative. It does not hide better deterministic measurements or real percentile calculations behind an API call. Premium UI shows pending, failure, refund/retry, and successful saved states distinctly.

A minimum successful launch does not require OCR, handwriting identification, 'handwriting twins', a public social graph, native applications, all ten radar axes, or all 272 definitions. It does require clear evidence and reliable failure behavior.

## 6. Definition of finished v1

A first-time user can upload their own supported handwriting, understand and correct an unsuitable capture, receive a useful Free report, inspect evidence, optionally buy a bounded Premium analysis, reopen it without a model call, compare authorized samples, share selected redacted cards, export the same content, and delete their data.

The operating team can reconcile payments and refunds, disable Premium without breaking Free, revoke sharing and corpus contributions, restore backups without resurrecting deleted data, roll back a bad benchmark/prompt/engine release, and see failures without logging private writing.

Technical completion means passing contract tests, zero-AI isolation tests, cross-owner authorization tests, version/reproducibility tests, real-handwriting validation, report parity tests, payment/retry tests, and device/accessibility checks. Synthetic unit tests and a good-looking prototype alone do not satisfy these gates.

## 7. Owner gates and safe defaults

| Gate | Required decision/evidence | Safe behavior before approval |
|---|---|---|
| Corpus rights and consent | Approved agreement, purposes, retention, withdrawal and source terms | Synthetic engineering fixtures only; no public rarity statistics. |
| Measurement calibration | Held-out writer-disjoint evaluation with annotated geometry | Label experimental; withhold affected claims. |
| Traditional content | Reviewed source-backed rule pack and wording | Mechanical descriptions and playful geometric labels only. |
| Provider/account access | Approved model, region/retention arrangement, API access and spend cap | Premium disabled; mocked integration tests. |
| Commercial release | Price, taxes, payment/refund terms, processor account | Test mode only; no real charges. |
| UX acceptance | Claude Design handoff plus usable mobile/desktop prototype | Contract-driven fixtures, not a claim of completed UX. |
| Privacy/security release | Access/deletion/retention review, threat-model tests and support process | Private alpha with restricted access. |

## 8. Agent execution protocol

Read `AGENTS.md`, select one ready task from `tasks.json`, and implement only that task's owned surfaces. Add tests and evidence before marking it done. Tasks involving real people, purchases, external data downloads, legal approvals, or production secrets require the corresponding owner gate; do not simulate completion with invented records.

Every code PR should state baseline commit, task ID, changed contracts, actual commands/results, fixtures/corpus version, known limitations, and migration/rollback behavior. Keep benchmark releases, editorial rule changes, and software releases independently reviewable.

**The critical path is contracts -> reliable intake -> interactive Free report -> defensible reference/comparison -> bounded Premium -> launch hardening.** Richer mechanics, recruitment, and design can advance in parallel. More features are useful only when they improve an observable user outcome and survive the same validation gates.
