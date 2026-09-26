# Retention configuration and deletion lineage

[Privacy drafts](README.md) · [retention.json](../../contracts/consent/v1/retention.json) · [deletion_lineage.json](../../contracts/consent/v1/deletion_lineage.json)

Status: draft pending owner review. `legal_claim` is `false` by schema. Retention here is a reviewed **configuration** of what the system does, not a statement of what any law requires.

## Retention classes

Sixteen classes cover originals, derivatives, analysis records, exports, share routes, Premium payloads and provider-side copies. They also cover reference members, pilot originals, annotations, support-case material, analytics, the consent ledger, accounting records, deletion tombstones and operational logs. Each class records:

- whether it can contain handwriting;
- what starts retention and which events end it (withdrawal of the relevant purpose, account deletion, parent deletion, maximum period);
- the maximum period, which is `null` in every class, with `decision_status: PENDING_OWNER_DECISION`. The validator rejects any period that lacks a recorded decision;
- deletion actions, such as deleting every object version, purging caches, revoking before deleting, and writing a tombstone;
- backup behaviour: handwriting-bearing classes must reconcile tombstones before a restored backup serves traffic;
- external copies: none, governed by a processor contract, or held by recipients and therefore irrevocable. The last one must be disclosed before export or sharing.

Accounting records and the consent ledger are retained under their own decided obligations. They must never hold handwriting.

## Deletion lineage

[deletion_lineage.json](../../contracts/consent/v1/deletion_lineage.json) is a DAG of artifact kinds from two roots: `upload_original` and `pilot_capture`. Every derived kind lists its parents, its retention class and what happens when **any** upstream artifact is deleted or its permission is withdrawn:

| Action | Used for |
|---|---|
| `DELETE` | normalized images, crops/overlays/thumbnails, analysis runs, report revisions, Premium payloads, exports, comparisons, annotations, support copies |
| `REVOKE_THEN_DELETE` | share routes, so no window serves stale content |
| `EXCLUDE_AND_REBUILD_OR_RETIRE` | reference members and benchmark artifacts, located through membership lineage |
| `REQUEST_PROCESSOR_DELETION` | provider-side copies; the outcome is recorded, never promised as instant |
| `RETAIN_UNDER_SEPARATE_OBLIGATION` | purchase ledger entries only; the validator forbids it for any handwriting-bearing kind |

The validator checks that roots are declared, parents exist, the graph is acyclic, and every kind is reachable from a root. It also checks that a handwriting-bearing kind is never assigned a retention class that understates handwriting. If a new kind cannot be reached from a root, deletion cannot find it.

## Deletion sequence (for T02/T24)

1. Revoke access first: sessions, share routes, asset tickets and presigned URLs.
2. Record a tombstone and advance the subject's deletion epoch.
3. Cancel queued jobs. Running jobs fail their publication check against the epoch and the current permission.
4. Walk the lineage from the affected roots and apply each node's action, including every object version and cache.
5. Exclude affected reference members from future releases. Then rebuild or retire affected releases according to the owner's `aggregate_after_withdrawal` decision.
6. Request deletion from processors and record the outcome.
7. Before any restored backup serves traffic, reconcile it against the tombstones.

Immutability of report snapshots never overrides deletion or revocation. A deleted report becomes unavailable; it is not silently edited.
