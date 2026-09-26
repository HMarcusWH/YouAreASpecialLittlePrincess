# Connector implementation index

[Roadmap index](../roadmap/00-index.md) · [Module/import boundaries](../roadmap/09-connectors-and-provider-boundaries.md) · [Decisions](../roadmap/19-provider-decision-register.md) · [Task briefs](../roadmap/06-agent-backlog.md).

A connector is an adapter between an application-owned typed port and an external system. It is not an SDK object exposed as our domain model. T27 establishes ports, error taxonomy, fakes and contract fixtures; owning tasks add the real adapters. All paths in these specifications are planned implementation targets.

| Port ID used by tasks | Specification | Owning integration |
|---|---|---|
| IdentityProvider | [Identity](identity.md) | T02; web/native transports T17/T29–T31 |
| ObjectStore | [Private objects](object-storage.md) | T04; restricted consumers T15/T21/T24 |
| PremiumModelProvider | [Premium model](premium-model.md) | T15/T16 |
| PaymentProvider | [Payments and store verification](payments.md) | T19 |
| NativePurchaseClient | [Payments and store verification](payments.md) | T29 compatibility; T30/T31 clients |
| TransactionalMailer | [Email](email.md) | T02 identity coordination; T24 operational mail |
| PushProvider | [Push](push.md) | T29–T31/T24 |
| AbuseChallengeProvider | [Abuse protection](abuse-challenge.md) | T04/T29–T31 |
| AnalyticsSink | [Analytics](analytics.md) | T17/T20/T22/T24 |
| TelemetryExporter | [Telemetry](telemetry.md) | T28/T24 |

## Common coding contract

Use internal DTOs for requests, verified observations and typed errors. Every operation has a bounded deadline, correlation ID, explicit environment and documented retry owner. Include an idempotency key only where the port/provider supports a real semantic deduplication contract; do not imply that adding a header guarantees exactly-once execution.

Adapters normalize provider responses, not business entitlement. State-changing business rows and outbox records commit inside the application transaction. Network calls occur outside long database transactions. Webhook validation precedes normalization; a durable inbox precedes asynchronous processing. Reconciliation is a first-class operation whenever events can be lost or arrive out of order.

Every connector ships: a fake with injected time/failure/state, provider capability profile, configuration schema, credential/data-flow list, success/error mappings, contract tests, safe observability, sandbox evidence, production gate and replacement/deletion procedure. Defaults must not accidentally send email, push, charges or model requests to live services.

## Capability profiles, not lowest-common-denominator guesses

A provider advertises verified support for signed upload methods/checksums, refund types, transaction history, idempotency windows, webhook signatures, region configuration and deletion behavior. Unsupported operations fail explicitly. Do not claim that all S3-compatible products implement every S3 policy, that every payment event has the same fields, or that all push providers guarantee delivery.

Direct SDK imports belong under `src/princess_app/adapters/<provider>/`; provider-specific native bridges belong under `apps/mobile/src/platform/`. The core numerical library, product schemas and report formatting helpers import neither. All browser/native server secrets are prohibited.

## Contract test harness

Run the same internal port cases against fakes and sandbox adapters where feasible. Include invalid credentials, wrong environment, expired proof, malformed payload, replay, duplicate business operation, retry-after, throttling, timeout after remote acceptance, revocation and resource deletion. Fakes must reproduce ambiguous outcomes, not simply raise a generic error before every action. Exact live sandbox tests are opt-in, owner-approved and redacted.

See [test gates](../roadmap/16-testing-evals-and-quality-gates.md) and [environment rules](../roadmap/15-environments-deployment-and-secrets.md). Native app-store readiness adds actual signed-device and store evidence; passing Python fake tests is not sufficient.
