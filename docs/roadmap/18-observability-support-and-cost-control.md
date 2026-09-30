# 18 — Operations, support, telemetry and cost control

[Index](00-index.md) · [Environments](15-environments-deployment-and-secrets.md) · [Security](17-security-privacy-and-abuse.md) · [Telemetry connector](../connectors/telemetry.md) · [Analytics connector](../connectors/analytics.md).

## Operational model

T28 adds structured logging/tracing seams and local diagnostics; T24 provides production dashboards, alert routes, support responsibilities and recovery drills. Start with OpenTelemetry-compatible traces/metrics and redacted structured logs. Vendor selection is an ADR, not a reason to couple application code to one dashboard. Product analytics is separate from operational telemetry and restricted financial audit.

Tag safe events with application version, environment, worker type, opaque operation ID, outcome code, latency bucket and provider request correlation where allowed. Do not emit handwriting, signed image URLs, prompts/responses, auth headers, raw store proofs, consent documents or complete feature vectors. Disable report-page session replay/autocapture by default and scrub crash breadcrumbs/screenshots.

## Minimum dashboards and alerts

| Area | Observe | Action |
|---|---|---|
| Intake/Free | rejection codes, decoded sizes, queue age, CPU/memory, feature coverage, completion latency | throttle/cap workers; investigate context-specific failures without logging writing. |
| Jobs | leases, heartbeats, attempts, stale publications, dead-letter age | reconcile/fence; preserve idempotent business results. |
| Premium | reserved budget, actual usage, refusal/invalid output, ambiguous timeouts, provider errors | circuit breaker; stop new paid jobs safely; release/reconcile credits. |
| Commerce | pending verification/completion age, duplicate events, unreconciled transactions, refunds/credit mismatches | reconcile provider state; do not compensate by creating unverified grants. |
| Rendering | queue age, timeout/resource use, template version, failed assets | bounded retry and template rollback; no arbitrary URL browsing. |
| Privacy | overdue deletion, tombstone replay, stale grants, object-version cleanup | block issuance and repair deletion lineage before reopening access. |
| Mobile | version adoption, startup/crash/ANR, purchase recovery, link/push failures | halt phased rollout; maintain compatible API; publish tested fix. |

Thresholds are configuration to benchmark and approve, not invented service-level guarantees. Alert owners and escalation channels must be named before public release.

## Cost model

Every operation has limits for input bytes/pixels, decode/extraction CPU, worker memory, storage/retention, number of export renders, provider images/tokens/output length, attempts and total reservation. Account/day/global spend caps and circuit breakers are server-side. A single paywall does not protect an unmetered PDF or anonymous CPU endpoint.

Price approval includes store/payment fees, taxes, refunds, provider retries, CPU, storage/egress, authentication, email/push, export and support. Compute estimates from current provider terms at approval time; historical token examples are not retail pricing. Reconcile provider usage with actual business attempts and record ambiguous outcomes. No hidden fallback to a more expensive model.

## Runbooks to ship

T24 must deliver actionable runbooks for: worker outage/lease recovery; database migration rollback; object-store outage; model outage/kill switch; duplicate or missing payment notification; native finish/consume retry; failed/refunded Premium; account/identity recovery; deletion and corpus withdrawal; suspected data disclosure; key/signing credential compromise; benchmark/model/template rollback; backup restoration with tombstones; store rejection and rollout halt.

Each runbook specifies trigger, required role, safe diagnostics, commands in the deployed environment, customer impact, data exposure limits, rollback, verification and escalation. Commands are not invented before infrastructure exists. Support views expose minimal metadata by default; accessing a user's writing requires explicit scoped authorization and an audit event.

## Recovery and compatibility

Define and approve RPO/RTO from actual storage/DB capability and test a restore. Record restore artifact, elapsed time, data consistency, ledger reconciliation and tombstone application. Backups are not proof of recoverability. A restored queue must not re-send paid model calls, emails or credits blindly.

Maintain deployment manifests with API/schema/engine/model/prompt/benchmark/rule/template/native-build versions. Old mobile clients remain supported for the documented window. Disable a capability without deleting its evidence/history. Rollback cannot reactivate a withdrawn reference release or leak revoked shares.

## Product analytics contract

Track only allowlisted events such as capture started, upload completed, report opened, offer viewed, checkout started, purchase verified, Premium published, export created, share dialog opened, invitation redeemed and deletion requested/completed. Separate counts at each step; a share-sheet callback is not confirmed social publication. Analytics outage does not block core transactions, and denial of optional tracking does not reduce paid functionality.


## Qualified operational snapshot boundary

T24 now exposes `operational-snapshot/1` from a fixed cross-tenant aggregate
database function plus reviewed manifest/tombstone state. RLS remains in force
for ordinary runtime reads; the SECURITY DEFINER function returns aggregates
only and collapses non-enum job/topic values to `other`.

The snapshot and `operational-alert-policy/1` are exporter-neutral. The
checked-in test policy proves both PASS and ALERT paths in the final runtime
image, including exact fixed alert codes. Production/staging policies are not
checked in with invented thresholds: threshold values, routing, ownership and
retention require deployed evidence and owner/provider decisions.

T24 now maps these already-bounded observations into the existing
TelemetryExporter port without issuing parallel SQL or widening its generic
attribute allowlist. The mapping exports a complete fixed count-gauge universe,
including zero for empty database groups, plus bounded age/attempt, capability
and reviewed fired-alert records. The final backend image exercises the mapping
through the existing fake exporter.

This is still provider-neutral evidence. The actual exporter/dashboard vendor,
sampling/retention, staging/production thresholds, routing and named escalation
owners require ADR-008/provider decisions and deployed evidence; sandbox/live
modes do not silently fall back to the fake exporter.
