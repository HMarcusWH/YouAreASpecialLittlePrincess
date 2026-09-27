# 23 — Post-PR14 reconciliation

[Index](00-index.md) · [Machine graph](tasks.json) · [Build sequence](20-end-to-end-build-sequence.md) · [PR #14](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/14).

## Purpose

PR #14 merged a large set of roadmap slices without promoting those task records to `DONE`. This record reconciles the merged repository against each task's own acceptance contract. A merged PR is implementation evidence, not automatic task completion. Human/provider gates remain separate from task status.

## Frozen reconciliation baseline

- PR #14 merged to `main` as `e8e174a2311f8d4327850218405819de8f87277e` on 2026-09-27.
- Its final implementation head was `d2e106325c549f91c177d5cfd8277b032526ecff`.
- The PR recorded 1,103 core pytest cases passing locally on Python 3.12 (CI also exercises 3.10 and 3.11), 164 PostgreSQL/backend tests, clean TypeScript typecheck/package tests, ten Chromium fixture journeys, and a local live upload → consent → analysis → report → real PDF download journey.
- The exact final implementation head passed the repository's CI, Roadmap integrity and Application environments workflows.
- The final restore/notification slices received a documented self-review because Codex review credits were exhausted. Six self-review findings were fixed in `d2e1063`; this is not rewritten as an automated review.

## Disposition matrix

| Task | PR #14 result | Acceptance disposition | Reconciled status | Residual owner |
|---|---|---|---|---|
| T27 | Ten application-owned ports, deterministic fakes, conformance harness and import boundaries | Port/fake task complete; real adapters remain downstream responsibilities | `DONE` | owning provider/product tasks |
| T05 | Versioned `evidence/1` payload, `EvidenceBundle`, coordinate-frame composition and fixtures | Complete | `DONE` | — |
| T09 | Immutable self-digested `ReportDocument`, revision rules and FREE/OWNER/PREMIUM/SHARE/EXPORT projections | Complete for current report contract; T13 owns later reference fields | `DONE` | T13 |
| T28 | Environment manifests, secret/egress matrix, locked backend environment, pnpm workspace and app CI | Complete after clarifying that native scaffold/build validation belongs to T29 and deployed packaging/topology belongs to T24 | `DONE` | T29/T24 |
| T02 | PostgreSQL/RLS product plane, permission ledger, identity bindings, OIDC verifier and API composition | Provider-independent persistence/authorization task complete; production identity/hosting decisions remain separate gates | `DONE` | ADR-002/003 activation |
| T04 | Safe intake, immutable captures, idempotent runs, fenced leased worker and erasure paths | Complete for measured current latency. A heartbeat is deferred to T24 only if production latency approaches the lease budget | `DONE` | T24 if needed |
| T15 | Bounded evidence-bound Premium packet/schema/validator/OpenAI adapter and adversarial cases | Substantial but incomplete: supported dynamic selector contracts still need deterministic candidate producers or explicit unsupported dispositions | `IN_PROGRESS` | T15 |
| T19 | Internal immutable purchase/credit/reservation/fulfilment ledger | Incomplete as a full task: Stripe/App Store/Play real adapters and sandbox evidence are absent | `IN_PROGRESS` | T19 |
| T10 | Draft tokens and contract-driven design handoff | Implementation exists, but task acceptance explicitly requires owner `design_acceptance` | `IMPLEMENTED_PENDING_REVIEW` | owner/design gate |
| T17 | Working Free Next.js upload → analysis → report journey | Incomplete: production sign-in UI, history, evidence charts and automated axe coverage remain | `IN_PROGRESS` | T17 |
| T21 | Offline PDF/PNG renderer, export jobs/storage/retrieval and live PDF journey | Renderer implementation exists; final design/integration review remains. Premium/pair/history content is owned by T20/T18, not invented here | `IMPLEMENTED_PENDING_REVIEW` | T10/T20/T18 integration |
| T24 | Feedback, ops commands, restore tombstones and notification delivery state machine | Explicitly incomplete operations task | `IN_PROGRESS` | T24 |

## T15 coverage finding

The reviewed individual Premium pack contains 71 questions. In the current database, 47 are model-answer questions: 28 use fixed selection domains and 19 use dynamic selection domains. The packet compiler correctly fails closed by omitting a dynamic question when no deterministic producer is registered. Reconciliation therefore records T15 as incomplete rather than treating safe omission as full product coverage.

Runtime activation remains false. No live model call, traditional rule activation or provider approval is created here.

## T24 residuals carried forward

The following PR #14 follow-ups remain explicit T24 work unless another task is named. The single-device logout and feedback-withdrawal restore gap was closed by the subsequent T24 tombstone repair using transactionally queued outbox events plus external replay tombstones.

- reconcile restored queued Premium attempts using provider-side request lookup where supported;
- production object/tombstone storage placement, backup tooling, RPO/RTO and a timed restore drill;
- live transactional mail, signed bounce/complaint handling and APNs/FCM integration;
- broader key rotation/compromise handling, account/identity recovery and store-rollout halt procedures;
- dashboards, alert thresholds, named operational ownership and edge/global limits;
- deployable/installable backend topology and a web mail-preference surface;
- add a lease heartbeat only if measured real latency makes the current 120-second lease unsafe.

## Status semantics after reconciliation

- `PLANNED`: meaningful implementation has not started.
- `IN_PROGRESS`: known coding/integration acceptance remains; `remaining_work` names it.
- `IMPLEMENTED_PENDING_REVIEW`: implementation is believed complete, `implementation_evidence` exists, and only review/human acceptance remains.
- `DONE`: the integrated acceptance contract and exact evidence are recorded; no `remaining_work` remains.
- `BLOCKED`: a named external dependency prevents further implementation.

Human gates do not become approvals merely because implementation is complete.

## Resulting handoff

After this reconciliation, `plan_tools.py --ready` should identify T11 as the only newly startable planned task. T29 remains blocked by T10's hard predecessor until the owner explicitly accepts the design. `plan_tools.py --active` surfaces T10, T15, T17, T19, T21 and T24 without confusing them with new READY work.
