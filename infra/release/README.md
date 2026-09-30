# T24 application release and rollback qualification

Status: **provider-neutral qualification tooling, not production deployment approval**.

This directory answers one narrow release question:

> Can the candidate database be migrated forward first, the candidate application be deployed, and the application then be rolled back to the immediately previous runtime without downgrading the database?

The v1 rollout model is migration-first:

```text
OLD APP + OLD DB
        |
        v
MIGRATE DATABASE FORWARD
        |
        v
OLD APP + NEW DB        <- must work
        |
        v
DEPLOY NEW APP
        |
        v
NEW APP + NEW DB        <- must work
        |
        | application rollback
        v
OLD APP + NEW DB        <- must still work
```

Application rollback never invokes a database downgrade. Alembic downgrade support remains migration-development tooling, not the production rollback mechanism. This matters especially for deletion tombstones, financial history, newer rows, provider-attempt journals and revocations.

## Artifacts

- `runtime-release/1` is generated from an exact source checkout. It records the source SHA, Alembic head, product/measurement/interpretation authorities, report-format authorities, public method+route surface and runtime build hashes.
- `release-policy/1` fixes migration-first rollout, the no-database-downgrade invariant and the required `DRAINED_OR_FENCED` queue state.
- `rollout-qualification/1` records static compatibility plus the executed runtime/database pair tests.
- `compatibility-witnesses.json` pins reviewed historical expand witnesses. The first witness is real: #38 at `0010_provider_attempt`, followed by the #39 `0011_operational_snapshot` additive migration.

Generated manifests and receipts are CI artifacts. They are not committed because they contain the exact candidate SHA.

## Compatibility gates

Static qualification requires:

1. the product-contract major to remain readable by the previous runtime;
2. every previous public `METHOD /v1/path` operation to remain present in the candidate;
3. the candidate to read the previous report writer's template;
4. the previous runtime to read the candidate report writer's template;
5. both artifacts to target the same reviewed runtime platform.

Route presence is deliberately called **route-surface compatibility**, not full API compatibility. It does not prove request/response semantic compatibility. T01 remains the authority for product DTOs, and dynamic Free smoke proves the concrete rollback path exercised here.

There is no minimum-client-build negotiation in the repository today. `contract_version=1.0.0`, FastAPI `0.1.0` and the native scaffold `0.1.0` must not be reinterpreted as client support windows.

## Dynamic qualification

The current rollback lane keeps the database at the candidate head and executes:

```text
candidate runtime writes report
        ->
rollback-base runtime reads it and writes another report
        ->
candidate runtime reads the base-written report
```

Both runtimes also execute fresh provider-free Free analysis against the candidate schema. Candidate-only queued work must be drained or fenced before rollback because durable job payloads do not yet have an independent compatibility contract.

The historical lane executes the actual old release sequence:

```text
#38 image migrates a fresh DB -> 0010
#38 Free smoke
candidate migration image upgrades the same DB -> 0011
#38 Free smoke again
```

No database downgrade occurs in either lane.

## Scope limits

`rollout-qualification/1` covers the API, Free analysis worker and report persistence/read path. It does **not** claim compatibility for arbitrary candidate-created in-flight jobs, Premium provider execution, export/Chromium worker rollback, mail/push/payment/live-provider behavior, native build compatibility, or production hosting/registry/network/secret-manager binding.
