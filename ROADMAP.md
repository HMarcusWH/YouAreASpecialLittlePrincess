# Product roadmap — Web, iOS and Android

**Plan version:** 2.0 · **Research reviewed:** 2026-09-26 · **Code baseline:** `251668a521150668b90c3551530daab694a5c739`.

[Agent instructions](AGENTS.md) · [Documentation map](docs/roadmap/00-index.md) · [Detailed task briefs](docs/roadmap/06-agent-backlog.md) · [Machine task graph](docs/roadmap/tasks.json) · [Execution sequence](docs/roadmap/20-end-to-end-build-sequence.md) · [Release gates](docs/roadmap/21-release-readiness-checklists.md).

## What we are building

A consumer handwriting app with a useful deterministic Free report and an optional paid, evidence-bound Premium interpretation. The supported core journey must work on **web, iOS/App Store and Android/Google Play**: capture/upload → suitability feedback → Free report → platform-appropriate purchase → saved Premium report → history/comparison → sharing/PDF → data/account deletion. Native clients and native digital purchases are part of the main programme, not post-v1 extras.

The report is the product: an attractive, interactive personal dossier with real visual evidence, bounded explanations and playful branding. A PDF and a share card are authorized presentations of the same saved report, not independent analyses. The brand is not a scientific claim about personality or population rarity.

## Verified starting point, not a completion percentage

The repository contains the pure Python measurement core, 272 canonical feature definitions, 64 registered core measurements, provenance/research material, and the reviewed T26 interpretation database. The remaining definitions are not promised outputs. Most measured estimates remain experimental rather than empirically calibrated. See the [engine README](README.md), [measurement methods](docs/measurement_methods.md) and [interpretation manifest](schema/graphology_interpretation/v1/manifest.json).

T00 and T26 remain `DONE` as historical task completions. PR #10 merged the CI/dependency baseline. Its final code review produced four follow-up dependency-policy findings; these were assigned to **T00A**, which is now `DONE`: PR #12 recorded failing-before/passing-after regressions in the [T00 evidence](docs/ci/T00_BASELINE.md#t00a-post-merge-follow-up), exact-head CI and a clean review. T03 (draft consent protocol, pilot gate still pending) and T01 (product contracts, PR #13) are also `DONE`. The [T00 evidence](docs/ci/T00_BASELINE.md) and [review follow-up](docs/roadmap/06-agent-backlog.md#t00a) remain linked.

There is no production API, application database, consumer client, store billing implementation, production reference corpus or live Premium service established by this baseline. Paths in the build specifications are planned unless identified as existing. Documentation, mock completion, human approval, store approval and production activation are distinct.

## Non-negotiable product boundaries

* Free inference is literally zero runtime AI: no learned weights, neural OCR, embeddings, classifiers or generative provider calls. AI-assisted development is permitted. CPU workers may be hosted; zero AI does not mean zero hosting cost or on-device execution.
* One canonical measurement authority. Do not relabel unrelated calculations to fit feature IDs, invent confidence, turn missing into zero, or infer physical pressure from image darkness.
* Premium starts from the same evidence. One bounded multimodal request selects reviewed values and produces bounded evidence-linked prose; it never owns measurements, percentiles, cohort selection or purchase entitlement.
* Viewing, expanding, reopening, sharing and exporting a saved report do not call a model. Failed Premium preserves Free.
* No diagnosis, intelligence, deception, criminality, employment suitability, authorship identification or relationship-outcome claims. Traditional associations are labelled and inactive until separately approved.
* Service processing, retention, corpus contribution, third-party AI processing, partner comparison and public sharing have separate permissions. Immutability does not defeat erasure or revocation.

## Implementation defaults

These are the proposed engineering defaults of this plan, not claims that SDKs, accounts or production vendors are already installed or approved. The [decision register](docs/roadmap/19-provider-decision-register.md) records remaining decisions and the [ADRs](docs/adr/README.md) explain alternatives.

| Surface | Build it this way |
|---|---|
| Numerical core | Keep `src/princess_graphology/` pure; no HTTP, SQL, identity or provider imports. |
| Product backend | A modular Python application with FastAPI entry points, PostgreSQL, SQLAlchemy and reviewed Alembic migrations. Separate deployments for API, CPU, Premium, render and reference workers; not a microservice per table. |
| Contracts | Reviewed product JSON Schemas separate from the canonical feature database; generated Python/TypeScript DTOs, derived OpenAPI and shared positive/negative fixtures. |
| Web | React/TypeScript with Next.js as a thin presentation/session boundary. FastAPI remains the business authority. No second billing or report backend in route handlers. |
| Mobile | Expo/React Native native screens and Expo Router. Shared API types, state logic and design tokens; native capture, secure storage, StoreKit/Play Billing and platform navigation. Not a webview wrapper. |
| Rendering | Shared web report components in an isolated Playwright print/card worker. Native screens consume the same projection and shared formatting rules, not DOM components. |
| Jobs | PostgreSQL durable job/outbox records, short leases and fenced publication. No long CPU/model work inside database transactions or HTTP request handlers. |
| Connectors | Typed application-owned ports; provider SDKs live behind adapters. Fakes are mandatory. Identity, storage, payments, model, mail, push, abuse, analytics and telemetry have explicit specifications. |
| Commerce | One internal immutable purchase/credit/fulfilment ledger; web Stripe candidate, iOS StoreKit, Android Play Billing. Provider verification precedes grants. Storefront rules control cross-platform credit use and steering. |

The complete import graph, runtime boundaries and build paths are in [09](docs/roadmap/09-connectors-and-provider-boundaries.md). Provider version pins are chosen and tested in their owning tasks, not fabricated in this roadmap.

## Release slices

| Slice | Deliverable | Gate |
|---|---|---|
| Foundation | T00A hardening; T01 contracts; T03 permission protocol; T27 ports; T28 reproducible environments | Exact-head CI and contract fixtures; no real purchases/data collection without approval. |
| Private Free alpha | Safe intake, durable jobs, evidence, authorized report, web client and mobile development shell | Honest experimental labels, no reference claims, no-AI isolation, access/delete tests. |
| Reference beta | Consented pilot, calibrated supported methods, controlled corpus, scoped statistics and comparisons | Writer-disjoint validation, rights, release/withdrawal evidence. |
| Premium/commerce beta | Evidence-bound model adapter, evals, ledger and three verified payment channels | Provider data/spend approval, sandbox reconciliation, pending/refund/duplicate tests. |
| Multi-platform beta | Complete web/iOS/Android journeys, shared facts, push/deep links, native billing and exports | Device/accessibility/privacy QA and actual TestFlight/Play testing evidence. |
| Ready for public release | Operations rehearsal, security review, store-ready evidence, approved metadata/products | T23/T24/T32/T33 evidence; owner T25 approval and staged publication. |

A narrow private alpha need not wait for a population corpus. It must omit unsupported ranks and restrict experimental claims. **Public multi-platform signoff still depends on the release graph**, including any advertised reference capability. Dropping a release capability requires an explicit scope amendment; an agent cannot mark a gate skipped merely to finish.

## Execution and navigation

The task graph is authoritative in [tasks.json](docs/roadmap/tasks.json); the human backlog is generated from it. T00–T26 retain their IDs. T00A closes the post-merge findings; T27–T33 add connector, environment, mobile and store work. T25 now means multi-platform signoff. T19 implements shared commerce before clients integrate it; mobile clients do not block the ledger itself.

```bash
python docs/roadmap/plan_tools.py --check
python docs/roadmap/plan_tools.py --ready
python docs/roadmap/plan_tools.py --task T01
```

These documentation commands are provided by this PR. Product test commands marked `TO_IMPLEMENT` in task briefs are not executable claims. After changing task data, run `--write` to regenerate the human backlog, then `--check`.

The foundation contracts (T00A, T01, T03) are merged; run `plan_tools.py --ready` for the next unblocked tasks. Follow [20](docs/roadmap/20-end-to-end-build-sequence.md) for safe parallel work. Maintain one contract steward for shared DTOs, one owner of each provider adapter and a documented handoff for stacked PRs.

## Definition of ready

A real user on each supported platform can complete the core journey without hidden inference charges, lost consumable credits, unauthorized disclosure or fabricated measurements. A returning user can recover their account-backed reports and unused eligible credits without creating new grants. Support can reconcile payments, restore backups while honouring tombstones, revoke shares, stop Premium without stopping Free and roll back supported releases without resurrecting withdrawn data.

Passing unit tests or generating an IPA/AAB is not store approval. Uploading a build is not public rollout. Final approval is recorded in [multi-platform signoff](docs/release/multi-platform-signoff.md), with actual artifacts, human owners and remaining limitations.
