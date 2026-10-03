# Data, ownership and lifecycle invariants

Read this before changing jobs, purchases, deletion or recovery. The implementation source remains authoritative; [migrations](../../migrations/README.md), [API](../reference/api.md), [mobile lifecycle](mobile-lifecycle.md) and [runbooks](../runbooks/README.md) provide the concrete entry points.

## Capture, analysis and report

```text
reserve upload → signed PUT → immutable completion/capture
  → service_processing permission → idempotent analysis start
  → leased extraction → evidence + report → authorized view
```

Upload reservations consume quota. A lost reservation response can leave an expiring orphaned slot; it is not a fully deduplicated business operation. Completion retries converge only for the same verified digest. Analysis start deduplicates for the intended capture/configuration. Neither an upload ticket nor a 202 response proves the report exists.

Published measurements and evidence refer to immutable input/processed digests and explicit coordinate frames. A source image is served through current report authorization, not a client-supplied object key. Image retention is optional and separate from service processing. Erasing an original may leave an authorized measurement report; deleting the capture removes access to associated reports and queues erasure.

`ReportDocument` is saved content. `ReportViewModel` is a current authorization-filtered view. Availability of images, Premium and grants is live state and must be rechecked; an immutable snapshot does not freeze permission forever. Comparison currently reads latest authorized same-owner revisions and returns an unsaved result. Partner grants and persisted pair deliverables remain separate work.

## Principals and guest transfer

The application owns principal IDs, while an identity adapter verifies credentials. A client never authorizes itself by decoding token claims. Guest transfer proves both guest and account credentials, updates relational ownership and purges guest-local state. Historical analysis provenance may retain the original owner identity; current access must use the live relational owner rather than reinterpret immutable provenance as authorization.

Local sign-out, application logout-everywhere, provider-global session revocation and asynchronous account erasure are distinct. The native session epoch discards late results after credential/principal change. Reinstall or a second device can discover account-backed runs only with valid access to the relevant principal; a lost guest credential is not recoverable merely because the API has a run-list endpoint.

## Permission and retention

Purpose, version, scope, decision and policy/notice lineage belong to the permission ledger. Purchase is not AI-processing permission. Retention, optional contribution, partner comparison and ordinary sharing are not interchangeable. Request IDs prevent a retried decision from appending a later duplicate that could reverse a newer choice.

Draft policy authorizes synthetic local/test scenarios only. Current coded timers and draft retention contracts are not an approved public retention policy. Withdrawal has immediate authorization effects; byte erasure and outbox processing may complete later. Report 202 deletion responses as requested, not completed.

## Store payment, credit and Premium

```text
store charge / transaction
    → provider verification
    → durable financial identity + credit grant
    → Apple client finish / Google completion owner
    → credit reserved for one intended Premium operation
    → bounded provider attempt → validation → saved overlay + credit spend
                                      └─ failure/revocation → release/reconciliation
```

A store charge may occur before Premium generation. Releasing a reservation is not a store refund. Refunding after a credit was spent requires the approved commercial/access policy; do not invent it in support text.

Uniqueness and idempotency protect application grants/publication. They do not prove exactly-once external execution. A timeout can mean the provider accepted work. Record ambiguous outcomes, retain deterministic attempt identities, bound exposure and reconcile. Never perform an extra model call simply because a screen remounted, a report reopened or an export was requested.

`complete-pending` returns successful completions during that invocation. It is not the remaining backlog count. A zero result can reflect no work, or failed completion attempts. Closure requires outstanding-state/provider verification, not interpreting zero as all clear.

## Leases and outbox

Workers use bounded leases/fencing and short publication transactions. A former worker cannot publish after another claimant takes ownership, permission changes, deletion or cancellation. Outbox rows persist state-change follow-up; failures stay pending for bounded retry/reconciliation. Each worker's exact retry policy belongs to its implementation, not a universal retry promise.

An incident kill switch stops only the capability behavior specified by its implementation. Pending notifications may be consumed while disabled; disabling generation does not prove a provider has cancelled already accepted work. Keep read/export/refund/reconciliation semantics explicit.

## Deletion, restore and rollback

Capture/account/permission/session changes are also recorded in a separate append-only tombstone log. The API writes a fast-path tombstone after commit; erasure processing retries the durable follow-up before dispatch. A restore must not roll that log back with the database.

Before restored traffic: replay tombstones, investigate unreadable entries, perform ordinary verified erasure, reconcile payment state and qualify restored Premium attempt identities. Unsupported/uncertain attempt lookup fails closed rather than reissuing paid work. Run the choreography against selected real providers before making production RPO/RTO claims.

Application rollback keeps the database at the forward candidate schema and uses a separately built previous application artifact. Drain/fence incompatible in-flight work; do not downgrade a populated database or erase financial/tombstone history. The existing synthetic rollback drill does not select a production host or prove all future schema changes compatible.

Downloaded PDFs/images cannot be recalled from recipients. Revocation ends future issuance from our systems and erases our derivatives as required; do not promise remote deletion of a file already shared elsewhere.