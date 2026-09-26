# 09 — Build boundaries, modules and connector contracts

[Index](00-index.md) · [Data](01-data-architecture.md) · [Connector specifications](../connectors/README.md) · [ADRs](../adr/README.md) · [Task graph](tasks.json).

## Build a modular product, not a forest of services

The implementation default is one application/domain codebase with separately deployed entry points where isolation or resource limits require them. PostgreSQL can initially host product, content and reference schemas under distinct roles. API, analysis, Premium, render and reference workers have different credentials and resource/egress profiles; they are not separate competing definitions of a report.

Planned source layout:

```text
src/princess_graphology/          existing pure numerical library
src/princess_contracts/           generated product DTOs; no I/O
src/princess_app/domain/          entities, value types, state transitions, policies
src/princess_app/application/     use cases, transactions, port orchestration
src/princess_app/ports/           Protocol interfaces using internal DTOs
src/princess_app/adapters/        SQL, storage, identity, billing, model, notifications
apps/api/                        FastAPI composition, HTTP schemas/routes/middleware
apps/workers/analysis/           safe decoding and deterministic extraction entry point
apps/workers/premium/            bounded provider calls, validation and publication
apps/workers/reference/          authorized corpus/release work
apps/web/                        Next.js presentation/session boundary
apps/mobile/                     Expo/React Native application, platform adapters
apps/render/                     Node/Playwright trusted print/card entry point
contracts/product/v1/            source JSON Schemas and semantic fixture cases
contracts/http/                  derived OpenAPI and endpoint compatibility fixtures
packages/contracts/              generated TypeScript DTOs
packages/api-client/              generated HTTP client plus typed transport adapters
packages/report-core/             formatting, chart specs, read-only presentation helpers
packages/report-web/              React DOM report/print components
packages/design-tokens/           shared design values and localization IDs
infra/                           environment manifests; no secrets
```

These directories do not exist merely because this plan names them. Create them only in their owning task. Preserve the existing distributable library while adding packaging boundaries; application dependencies must not become mandatory numerical-library dependencies. T28 records workspace/package locks; T00A's dependency protections must be extended deliberately to each new environment.

## Allowed import directions

Contracts have no runtime I/O. The measurement engine does not import the application. Domain imports contracts/value objects, never SDKs, FastAPI or SQLAlchemy. Application imports domain and ports; adapters implement ports; entry points compose implementations. Clients import generated contracts/API-client/report helpers, not backend internals. Render receives an authorized projection, not a database owner connection. Add architecture tests that reject reversed imports and provider imports in Free.

Do not build an abstract repository for every SQL query merely for symmetry. Introduce ports around meaningful boundaries: identity, asset access, purchases, notifications, model execution, job claim/publication and transaction boundaries. Database repositories can remain internal to the application adapter layer.

## Canonical wire contract pipeline

The existing feature database remains numerical authority. Separately, T01 authors product JSON Schemas with stable IDs, explicit versions, closed object shapes, nullable/missing states and semantic fixture cases. Generate Python DTOs and TypeScript types with a pinned generator. Derive OpenAPI from API routes using those DTOs; compare normalized schema projections in CI. Do not hand-maintain three copies of the same fields.

Semantic validators enforce constraints JSON Schema cannot express: matching run/owner references, original versus processed coordinate frames, canonical units, allowable evidence classes, entitlement-filtered fields, and source-compatible versions. T01 defines a canonical digest representation: UTF-8, stable object-key serialization, finite numbers, explicit defaults and array ordering. Hash the canonical DTO bytes, not incidental Python repr or localized strings.

Default identifiers are opaque server-issued IDs; times are UTC RFC3339; currency amounts are integer minor units plus ISO currency code; measurement units remain canonical. Amounts and credits never use floating point. Browser/mobile display formatting is shared and tested against the same fixture facts.

## Connector port shape

A port returns internal DTOs or typed failures such as `InvalidInput`, `Unauthenticated`, `NotAuthorized`, `NotFound`, `RateLimited(retry_after)`, `TransientUnavailable`, `PermanentFailure` and `AmbiguousOutcome`. Provider exceptions and raw payloads never leak across the boundary. Each call carries correlation ID, operation/dedupe key, deadline and the minimal authorized context. Retain provider request/transaction IDs privately for reconciliation.

Adapters must implement bounded timeouts, explicit retry ownership, redacted structured errors, versioned mappings, fake/test/live modes, schema validation and teardown/deletion behavior. No hidden SDK retries on a metered model request; no synchronous network call inside a long SQL transaction. Verify signatures before normalizing webhook events. A normalized event is not yet a business grant.

## Internal state interfaces

A `UnitOfWork` commits domain rows plus outbox atomically. Job claiming acquires a short lease and monotonically increasing fencing token; work occurs outside the transaction. Publication compares lease token, input/report version, consent/grant epoch and deletion epoch before committing. Lease expiry never entitles a stale worker to publish.

Keep an append-only `provider_event_inbox` unique by provider/environment/event ID, and a separate application ledger. Webhook delivery can be duplicated, reordered or absent. Reconciliation pulls authoritative provider state using opaque transaction references. Do not apply every event in arrival order as though it were a state-machine command.

`Clock`, `IdGenerator` and deterministic random fixtures are injectable for tests. They are small internal interfaces, not hosted services. PostgreSQL queue mechanics are the initial queue adapter; introducing Redis/Celery requires evidence and an ADR, not habit.

## Connector ownership map

| Port | Owner | Specification |
|---|---|---|
| IdentityProvider | T02/T27 | [Identity](../connectors/identity.md) |
| ObjectStore | T04/T27 | [Storage](../connectors/object-storage.md) |
| PremiumModelProvider | T15/T27 | [Model](../connectors/premium-model.md) |
| PaymentProvider and NativePurchaseClient | T19, T30/T31 | [Payments](../connectors/payments.md) |
| TransactionalMailer | T24, identity integration T02 | [Mail](../connectors/email.md) |
| PushProvider | T29–T31/T24 | [Push](../connectors/push.md) |
| AbuseChallengeProvider | T04/T29 | [Abuse](../connectors/abuse-challenge.md) |
| AnalyticsSink | T17/T24 | [Analytics](../connectors/analytics.md) |
| TelemetryExporter | T28/T24 | [Telemetry](../connectors/telemetry.md) |

## Handoff and tests

T27 publishes ports, fake implementations, provider capability profiles and contract-test harnesses. Owning tasks add real adapters without modifying port semantics casually. Contract fixtures cover success, timeout ambiguity, malformed input, bad signatures, retries, revocation, replay, wrong environment and deletion. A fake must reproduce failures and timing; a fake that always returns success is not sufficient.

Every provider decision records data categories, credential scope, region/retention evidence, test endpoints, supported capabilities, SDK pin, owner approval and exit strategy. Provider replacement changes adapter/mapping/configuration, not canonical report or account IDs. Defaults and unresolved procurement are in [19](19-provider-decision-register.md).
