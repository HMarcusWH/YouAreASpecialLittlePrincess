# T24 provider-neutral operational posture

This directory defines the **read-only** operational contract that later
dashboard/alert providers consume.

`operational-snapshot/1` is built from:

- the reviewed environment manifest's five existing kill switches;
- fixed cross-tenant aggregate rows returned by
  `app.operational_snapshot(now)`;
- the Alembic revision returned by the separate fixed helper;
- the external tombstone log's presence/count/readability.

The database function is `SECURITY DEFINER` because the normal runtime role is
correctly RLS-scoped. It returns aggregate counts/ages/attempts only. It never
returns principal, job, report, transaction, provider-message, asset or object
identifiers and performs no dynamic SQL. Unconstrained job kinds and outbox
topics are collapsed to reviewed categories before leaving PostgreSQL.

Operator commands:

```sh
$API_ENV python -m princess_api.ops snapshot
$API_ENV python -m princess_api.ops check --policy /opt/princess/infra/operations/alert-policy.test.json
$API_ENV python -m princess_api.ops verify-disabled --switch commerce --switch premium_generation
```

`verify-disabled` is intentionally one-way: it can prove a reviewed manifest
has capabilities disabled, but there is no command or database table that can
enable or disable them. Manifest/redeployment remains the authority.

Only the synthetic **test** alert policy has concrete thresholds. Production
thresholds, dashboard destinations, alert routing and named owners remain
deployment/owner decisions and must be based on observed staging behavior. This
directory does not select an observability vendor and does not create an SLO.


## Telemetry mapping

The provider-neutral operator surface can now map the same bounded snapshot into
the existing `TelemetryExporter` contract:

```sh
$API_ENV python -m princess_api.ops emit-telemetry
$API_ENV python -m princess_api.ops emit-telemetry --policy /opt/princess/infra/operations/alert-policy.test.json
```

The mapping does not query PostgreSQL itself and does not widen the generic
telemetry attribute allowlist. Each of the fixed `VALID_KEYS` dimensions emits
an `operational.count` gauge on every snapshot, using zero when the database
omits an empty group. Non-null ages/attempt counts, the five reviewed capability
states and optional reviewed fired alerts are emitted separately. This prevents
a formerly non-zero queue series from remaining stale merely because the next
snapshot is empty.

Only the existing fake exporter composes in local/test/preview. Sandbox/live
TelemetryExporter modes fail explicitly until ADR-008 selects and qualifies an
actual exporter/dashboard stack. Telemetry remains best effort and never becomes
API readiness or business-state authority.
