> Human maintainer entry: [docs/README.md](docs/README.md), [handover](docs/handover/README.md), [setup](docs/development/local-setup.md) and [testing](docs/development/testing.md). For documentation changes also run `python tools/documentation.py --check`. Current implementation references override historical route sketches; task/gate authorities remain unchanged.

# Coding-agent entry point

Read [ROADMAP.md](ROADMAP.md), then the [documentation map](docs/roadmap/00-index.md). This repository contains a deterministic Python core, shared product services and an implemented mobile-first native client with supporting web presentation. Do not mistake planned paths or historical roadmap statements for implemented code.

## Find and claim work

1. Inspect current `main`, open PRs, failing checks and unresolved review findings. Record the actual base commit.
2. Run `python docs/roadmap/plan_tools.py --ready`; select a task whose hard predecessors are `DONE`. Read `--task ID`, every `required_docs` entry and the corresponding [task brief](docs/roadmap/06-agent-backlog.md).
3. Work in a branch named `task/<ID>-<short-purpose>`. State owned paths, contracts affected, acceptance evidence and rollback in the PR before expanding scope. One bounded slice per PR; a large task may use a numbered PR series, but it is not DONE until integrated acceptance passes.
4. Coordinate shared schema, DTO generation, migrations, ledger and worker state-machine edits. Another PR's proposal is not a merged dependency. A mock or frozen fixture can unblock only work explicitly scoped to mocks.
5. Finish with positive and adversarial tests, actual executed command results, resolved versions, migration/recovery evidence and a limitation statement. Never merge or weaken protection/checks to bypass failure.

Mobile-first execution (2026-10-03): shared native client work proceeds under T30A against `DONE` capability tasks, fakes and the development API; T30/T31 platform qualification no longer waits for web Premium T20, and a mobile-scoped release is not T25 multi-platform signoff. This does not relax any owner gate or mark a predecessor done.

`docs/roadmap/tasks.json` is the task/dependency/status authority. The [human backlog](docs/roadmap/06-agent-backlog.md) is generated; edit the JSON then run `python docs/roadmap/plan_tools.py --write`. `--check` rejects cycles, missing references, stale generated text and broken local document links. `--ready` shows unopened planned work whose hard predecessors are DONE; `--active` shows `IN_PROGRESS` and `IMPLEMENTED_PENDING_REVIEW` work. Partial tasks record `implementation_evidence` and explicit `remaining_work`; a merged PR never implies `DONE`. Owner gates may allow mock implementation, never unapproved activation.

## Where code belongs

Follow [module boundaries](docs/roadmap/09-connectors-and-provider-boundaries.md). Preserve the pure `princess_graphology` core. Application/domain/adapters live separately; web and native clients consume the same generated contracts and authorized report projections. No SQL, provider SDK or browser dependency in core measurement modules. No provider objects in public API DTOs. No client-side entitlement or measurement authority.

[Connector specifications](docs/connectors/README.md) define ports, failure semantics, secrets, fakes and contract tests. [ADRs](docs/adr/README.md) distinguish engineering defaults from open provider choices. Do not introduce a new vendor, package manager, auth system, local password implementation, queue broker or billing aggregator without updating the owning decision and tests. Verify exact SDK/tool versions before pinning them; inherited version strings are not recommendations to install latest.

## Non-negotiable boundaries

- Free inference is literally zero runtime AI: no learned weights, neural OCR, local classifiers, embeddings or model-provider calls. AI-assisted development is allowed. The method dependency closure, installed package partition and egress tests enforce this; `free_compute` alone does not.
- Preserve canonical IDs, units, estimands, coordinate frames, missingness and provenance. `AnalysisResult.measurements` stays one aggregate per feature ID. Repeated regional observations belong in the separate versioned evidence contract.
- Measured geometry, proxies, reference statistics, traditional associations and AI synthesis are distinct evidence classes. No diagnostic, intelligence, deception, criminality, hiring, identity or relationship-outcome claims.
- Do not invent confidence, rarity, writer counts, source clearance, test results or provider compatibility. Missing is not zero. Synthetic samples are labelled and excluded from human statistics.
- One immutable report snapshot feeds authorized web, native, PDF and share projections. No model calls on read, expand, reopen, export or share. Immutability never defeats deletion/revocation.
- Server-verified purchases grant through one internal ledger. Store credits, local transactions, credit reservation, model attempts and durable report publication are separate lifecycles. Never grant on a client flag or browser redirect. See [commerce](docs/roadmap/14-payments-entitlements-and-commerce.md).
- No private writing, crops, transcriptions, raw prompts, tokens, private vectors, production dumps or signing secrets in Git, logs, analytics, public fixtures or design-provider uploads.
- Service processing, storage retention, optional corpus contribution, third-party AI processing, partner comparison and public disclosure require distinct permission records. Declining donation does not diminish Free.
- A provider timeout does not prove no execution occurred. Promise idempotent business publication, not exactly-once external execution. Recheck permissions and deletion epochs immediately before publication.
- Web, iOS and Android are in release scope. Native digital billing uses platform adapters. Apple Pay/Google Pay are not substitutes for StoreKit/Play Billing. Regional alternative payments require an explicit fresh policy decision.

## Canonical sources and precedence

Product scope and execution order: the [current index](docs/roadmap/00-index.md) and tasks. The [post-PR14 reconciliation](docs/roadmap/23-post-pr14-reconciliation.md) is historical evidence, not current implementation instructions. Numerical definitions: [feature database](schema/graphology_feature_database_v1.json). Interpretation semantics: [T26 handoff](schema/graphology_interpretation/v1/README.md), source JSON and compiler, not prose examples in an older roadmap. T26 is reviewed and inactive; do not rebuild it or activate traditional packs as part of another task.

Before content work read [research index](research/graphology/README.md) and [research handoff](research/graphology/DATABASE_HANDOFF.md). Preserve the frozen `research/graphology/foundations-v0.1/` bytes. Source fidelity, empirical validity, feasibility, within-sample salience and rarity stay separate. A roadmap schema/prompt sketch does not override reviewed production fields.

T00 and [T00A](docs/roadmap/06-agent-backlog.md#t00a) are historically DONE with their recorded PR #10/#12 evidence. Preserve the supported dependency/build configuration (see [requirements](requirements/README.md#supported-build-configuration)); a new dependency finding creates new scoped evidence or reopens the affected task rather than rewriting the old completion record.

## Testing and completion

The [test matrix](docs/roadmap/16-testing-evals-and-quality-gates.md) lists current versus planned commands. Existing core commands include:

```bash
python tools/generate_feature_contract.py --check
python tools/compile_premium_interpretation_db.py --check
python tools/validate_graphology_database.py
python tools/check_graphology_research.py
python tools/test_graphology_research.py
ruff check src tests tools
python -m compileall -q src
python -m pytest -q
python docs/roadmap/plan_tools.py --check
```

Use the complete current CI workflow, not this abbreviated list, for exact-head verification. Preserve hash-locked dependencies, no-dependency local installs, marker/build policy checks and installed-wheel smoke. New services extend isolation and lock policy without forcing provider SDKs into Free. Never represent a proposed test name as a completed test.

Before completion inspect cross-owner access, duplicate/reordered events, crash-after-grant, missing/zero/constant inputs, version drift, projection/export parity, consent withdrawal, backup restoration and rollout reversal. Every PR includes: task ID, baseline, changed contracts, commands/results, fixture and release versions, owner-gate status, rollback and follow-up findings. Use [PR handoff guidance](docs/roadmap/20-end-to-end-build-sequence.md).

Human gates cover provider accounts/contracts/regions/spend, prices and terms, participant rights, calibration, traditional activation, native signing, store review and public release. Agents may implement disabled adapters, mocks, tooling and draft copy. They cannot manufacture approvals, testers, payments or release evidence.
