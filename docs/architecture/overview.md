# Implemented application architecture

This guide describes the post-#72 source layout. [Current state](../handover/current-state.md) records qualification limits; [provider decisions](../roadmap/19-provider-decision-register.md) records pending activation. A declared production environment is not evidence of a deployed system.

## Process and trust map

```text
Native Expo/RN client ────┐
                         ├── versioned FastAPI boundary ── application use cases
Supporting Next.js client┘              │                         │
                                        │             PostgreSQL ownership/RLS
                                        │              jobs, ledger, outbox,
                                        │              permissions and reports
                                        │                         │
                                 private object store       leased workers
                                 immutable input/export     ├─ analysis + erasure
                                        │                   ├─ Premium attempts
                                        │                   ├─ exports → renderer
                                        │                   └─ notifications
                                        └── external tombstone log
```

The numerical engine is pure `src/princess_graphology/`. Product contracts are `src/princess_contracts/`. The source-tree application lives in `src/princess_app/`; its domain/application/ports do not become clients of arbitrary provider SDKs. Provider adapters and persistence compose at the application edges. See [module boundaries](../roadmap/09-connectors-and-provider-boundaries.md).

## Who owns what

| Component | Authority | Must not do |
|---|---|---|
| Native client | Capture preparation, presentation, session transport, local workflow journal, platform interaction | Re-measure server facts, mint credits, infer authorization from a route, keep provider server secrets |
| Web server/client | Thin cookie/proxy transport and supporting presentation | Direct private SQL or a second billing/model authority |
| FastAPI | Authenticate, resolve current principal, invoke use cases, return scoped projections | Treat client purchase state as a grant, leak raw provider objects or mutable DB rows as contract truth |
| PostgreSQL application role | Principal-scoped transaction state | Own tables, bypass RLS or act as migration/admin role |
| Analysis worker | Deterministic extraction, evidence/report construction, fenced publication and erasure processing | Import learned inference into Free or call a model provider |
| Premium worker | Bounded provider attempt under current permission and reservation | Publish unvalidated model output, replace canonical measurements or blindly repeat ambiguous execution |
| Export worker | Resolve authorized saved projection, store bounded rendered output | Grant disclosure because a client asks for it |
| Renderer child | Offline rendering of its supplied projection | Fetch arbitrary URLs, read the database or call a model |
| Notification worker | Recheck current target/report/preference and deliver permitted generic notification | Make notification payloads authoritative business state |
| Operator | Approved diagnosis/reconciliation/restore | Invent provider observations, manually dispatch erasure, grant unverified credit or discard forward tombstones |

## Core product trace

A client reserves an upload slot, PUTs a bounded derivative and completes with its exact digest. Completion creates a verified capture, not an analysis. The client records the applicable permission and explicitly starts analysis. A worker publishes evidence and an immutable saved report only while its lease, ownership and permission/deletion fences are current. Clients read an authorization-filtered projection and do not regenerate content on reopen.

Store proofs enter one backend ledger. A durable credit grant precedes store finish/consume. Reserving that credit for Premium is a different operation. A validated output becomes a saved overlay; export and reading do not call a model. See [lifecycles](data-and-lifecycles.md) and [API semantics](../reference/api.md).

## Source and runtime packaging

The Free Python distribution includes the numerical core and pure contracts, not `princess_app`. Backend images package the source-tree application, API, workers, migrations, environment/operation configuration and required data files. The notice catalogue is a runtime dependency: `contracts/consent/v1/notices.json` must be present. Export images additionally contain the reviewed Node renderer and Chromium. No dependency upgrade is implied by this handover.

`infra/runtime/entrypoint.py` selects a fixed reviewed component and runs preflight. Manifests validate secret names and declared egress, while preflight/composition also reject unsupported live modes. The API's `/health/live` is process response; `/health/ready` checks the database. A container database probe is not proof that the API process is alive or that a provider can be called.

## Current development composition

Local/test use fake identity/storage/payment/model/messaging boundaries and synthetic material. Some real adapters exist as disabled implementations. Supabase has only a narrowly qualified, protected staging verification composition; this is not native login/refresh or a fully composed staging service. Object storage and payments still reject non-fake modes in current composition. Production hosting and provider recovery remain T24 work.

Use [environment declarations](../reference/environment-matrix.md) to inspect intended configuration and [connectors](../connectors/README.md) for typed errors/capabilities. Do not add a fallback from failed live composition to a fake provider.

## Design and evidence boundaries

One saved document feeds authorized native/web/export views. Native components reuse semantic tokens, formatting, reviewed copy and stored chart observations—not DOM components, client-selected highlights or invented distributions. Missing is not zero; image darkness/thickness remain proxies; empirical/reference/traditional/AI layers remain distinct. The accepted design is [The Dossier](../design/ACCEPTED_DOSSIER_REFERENCE.md), with platform typography fallbacks pending separate asset decisions.

Component entry pages and source locations are indexed in [component navigation](../reference/component-index.md).
