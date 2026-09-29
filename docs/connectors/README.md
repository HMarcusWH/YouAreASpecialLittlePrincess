# Connector implementation index

[Roadmap index](../roadmap/00-index.md) · [Module/import boundaries](../roadmap/09-connectors-and-provider-boundaries.md) · [Decisions](../roadmap/19-provider-decision-register.md) · [Task briefs](../roadmap/06-agent-backlog.md).

A connector is an adapter between an application-owned typed port and an external system. It is not an SDK object exposed as our domain model. T27 established ports, error taxonomy, fakes and contract fixtures; owning tasks add or qualify real adapters. Some provider-independent and disabled adapters now exist, while production provider selection/activation remains separately gated. Specifications describe both implemented seams and downstream activation requirements.

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

## Implemented seams (T27)

The ports, fakes and conformance harness exist. Several adapter implementations also exist in disabled/provider-independent form; that is not production approval. Production provider decisions in [19](../roadmap/19-provider-decision-register.md) remain pending until their task-specific evidence/gates are satisfied.

| Port | Protocol and DTOs | Fake (standard library only) | Fake capability profile |
|---|---|---|---|
| IdentityProvider | `src/princess_app/ports/identity.py` | `FakeIdentityProvider` | verify, revoke session, provider account deletion; expiry, audience, key rotation and revocation states |
| ObjectStore | `src/princess_app/ports/storage.py` | `FakeObjectStore` | presigned PUT, immutable versions, server copy, download tickets, hard delete; **no** size enforcement at upload and **no** provider SHA-256 unless configured |
| PremiumModelProvider | `src/princess_app/ports/model.py` | `FakePremiumModel` | structured output, image input, no provider storage, authoritative fake `attempt_lookup`; explicit responder, no default success |
| PaymentProvider | `src/princess_app/ports/payments.py` | `FakePaymentProvider` (Stripe-, Apple-, Google-shaped rails) | per rail: web checkout/refund (Stripe), proof verification (stores), server consume/acknowledge (Google only), signed events, lookup, reconcile |
| NativePurchaseClient | `src/princess_app/ports/payments.py` | `FakeNativePurchaseClient` | returns store proofs; Apple finish is client-side after the server grant |
| TransactionalMailer | `src/princess_app/ports/messaging.py` | `FakeMailer` | template/variable allowlist, bounded provider idempotency window, suppression |
| PushProvider | `src/princess_app/ports/messaging.py` | `FakePushProvider` | stateless targets, generic payloads, token invalidation, environment mismatch, duplicate delivery |
| AbuseChallengeProvider | `src/princess_app/ports/abuse.py` | `FakeAbuseChallenge` | action/site binding, expiry, replay, outage → `UNAVAILABLE` |
| AnalyticsSink | `src/princess_app/ports/analytics.py` | `FakeAnalyticsSink` | versioned event/property allowlist (`analytics-events/1`), consent and disable switch |
| TelemetryExporter | `src/princess_app/ports/telemetry.py` | `FakeTelemetryExporter` | attribute allowlist and redaction; `BufferedTelemetry` drops rather than blocks |

T19 PR #35 adds the disabled Stripe adapter. PR #36 completes the code-side provider set: Stripe refund requests are separately capability-gated; `src/princess_app/adapters/apple/AppleAppStorePaymentProvider` verifies signed StoreKit/App Store material and Notification History; `src/princess_app/adapters/google/GooglePlayPaymentProvider` verifies ProductPurchaseV2, authenticated RTDN, consume/acknowledge and Voided Purchases backfill. All use already-reviewed backend HTTP/JWT/cryptography dependencies and application composition still refuses every non-fake PaymentProvider until T19's owner/provider gates are approved.

Shared semantics live in `src/princess_app/ports/base.py`: the typed failure taxonomy (`InvalidInput`, `Unauthenticated`, `NotAuthorized`, `NotFound`, `Conflict`, `Unsupported`, `RateLimited`, `TransientUnavailable`, `DeadlineExceeded`, `PermanentFailure`, `AmbiguousOutcome`), `CallContext` (correlation ID, explicit environment, absolute UTC deadline, optional semantic dedupe key), `CapabilityProfile`, and `provider_errors()` which translates SDK exceptions without chaining the original. The environment/mode matrix composes fakes only into local/test/preview and requires live adapters in production; a fake constructed for production raises.

Fakes script failures per operation through `FaultPlan`, including `after_effect=True` for "the remote side executed, the caller saw a timeout". Latency past the call deadline also yields `AmbiguousOutcome` after the effect.

Run the harness with:

```bash
python -m pytest -q tests/connector_contracts tests/test_architecture_boundaries.py
```

`tests/test_architecture_boundaries.py` reads imports from the AST and enforces the import directions in [09](../roadmap/09-connectors-and-provider-boundaries.md): the numerical core, contracts, ports, domain, application and fakes cannot import provider SDKs, SQL or HTTP frameworks, and only `princess_app.adapters.<provider>` may. The learned `princess_graphology.signature` extra is the one declared exception and nothing else may import it.
