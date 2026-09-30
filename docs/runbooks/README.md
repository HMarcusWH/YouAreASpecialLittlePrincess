# Runbooks (T24)

Status: **DRAFT.** These cover the mechanisms that exist in the code today, with commands you can run against a local or staging database. No hosting, alerting or paging provider has been chosen yet. Every step that depends on one is marked **PENDING DEPLOYMENT** instead of guessed. Alert owners and escalation channels are owner decisions ([18](../roadmap/18-observability-support-and-cost-control.md)).

Conventions:
- `$API_ENV` is the API component's environment (`PRINCESS_ENV`, `PRINCESS_COMPONENT=api`, `PRINCESS_DATABASE_URL`, …).
- SQL runs as a migration or operator role, never as an owner.
- Queries return counts, IDs and codes only. None of them selects handwriting, report documents, Premium text or feedback comments.

## 1. Worker outage and lease recovery (analysis, Premium, export)

- **Trigger:** jobs pile up in `QUEUED`, or leases expire repeatedly.
- **Diagnose:**
  ```sql
  SELECT kind, state, count(*), min(created_at) AS oldest, max(attempts) AS max_attempts
  FROM app.job GROUP BY kind, state ORDER BY kind, state;
  ```
- **Act:** restart the worker process. Recovery needs no manual steps. A job whose lease expired is reclaimed with a new fencing token. A job that used its last attempt is failed with `attempts_exhausted` and never leased again. A Premium job's credit is then released, and an analysis queues its retention review. A stale worker cannot publish.
- **Verify:** the oldest `QUEUED` age falls, and `attempts_exhausted` counts stay flat.
- **PENDING DEPLOYMENT:** process supervisor commands and the dashboards for queue age.

## 2. Missing, duplicate or late payment notifications

- **Trigger:** a customer reports a purchase without credit, or `financial_transaction` rows sit with `completed_at IS NULL`.
- **Act (idempotent):**
  ```sh
  $API_ENV python -m princess_api.ops reconcile --rail stripe --since-hours 48
  $API_ENV python -m princess_api.ops complete-pending
  ```
  Reconciliation re-reads the provider's authoritative state. It never grants from a client flag or a redirect.
- **Payments after account deletion:**
  ```sql
  SELECT rail, event_id, received_at FROM app.provider_event WHERE outcome LIKE '%owner_deleted_refund_pending%';
  ```
  Each row is a payment whose automatic refund request failed. Refund it in the provider console, then run `reconcile`.
- **Verify:** `complete-pending` reports `0`, and the provider shows the refund.

## 3. Model outage or runaway cost

- **Act:** turn off the `premium_generation` kill switch in the environment manifest and redeploy the API. Free, reads, exports and webhooks keep working. Queued Premium jobs run at most twice. Refused, failed or fenced attempts release their credit.
- **Diagnose:**
  ```sql
  SELECT state, last_error, count(*) FROM app.job WHERE kind = 'premium' GROUP BY 1, 2;
  SELECT state, count(*) FROM app.credit_reservation GROUP BY 1;
  ```
- **Note:** an ambiguous provider timeout may have executed and billed on the provider side. That cost is ours and bounded by the spend budget. The customer is charged only on publication.

## 4. Deletion and erasure verification

- **Trigger:** a deletion request older than the approved window (the window is owner-pending).
- **Diagnose:**
  ```sql
  SELECT topic, count(*), min(created_at) AS oldest FROM app.outbox_event
  WHERE dispatched_at IS NULL GROUP BY topic;
  ```
- **Act:** erasure events stay pending until `verify_deletion` succeeds, and the erasure worker retries them every pass. Do not mark events dispatched by hand. A capture's derived rows are removed only after its bytes are verified gone (`app.erase_capture_records`), and an account's rows only after all of its assets are (`app.erase_deleted_account`).
- **Verify:** no `capture.deletion_requested`, `account.deletion_requested`, `asset.erasure_requested` or `upload.rejected` event is older than the window.

## 5. Export template rollback

- **Act:** revert the renderer commit and redeploy the export worker. The template version is part of every export's cache key, so new requests render with the restored template. Exports whose projection is no longer authorized are revoked and erased when next retrieved. Re-exporting never calls a model.

## 6. Feedback retention

```sh
$API_ENV python -m princess_api.ops expire-feedback
```
This deletes report feedback past `expires_at` (a draft 180-day period, owner-pending). Only the `princess_support` role may read feedback, and it sees the feedback columns only.

## 7. Database restore without undoing deletions, withdrawals or revocations

Every account and capture deletion, every permission withdrawal or denial, and every "log out everywhere" is also written to an append-only tombstone log kept outside the database (`PRINCESS_TOMBSTONE_DIR`, a JSONL file locally). The API writes the tombstone right after it commits the change. The erasure worker writes it again before it processes the change's outbox event, and that event stays pending until the write succeeds. Deletions also tombstone the guests merged into the account, because a backup from before the merge holds the guest's copy. A restore never rolls the log back.

After restoring a backup, **before the environment serves traffic**:
```sh
$API_ENV python -m princess_api.ops replay-tombstones
```
The command prints four counts:
- `reapplied`: changes the restored database had lost, now applied again. Deletions are re-queued for erasure, withdrawals re-recorded and propagated, and revocations re-applied with the devices bound before them dropped.
- `already`: the restored database reflects the change, or holds a newer decision. A permission granted again after a withdrawal is never re-withdrawn.
- `unknown`: the subject is not in the restored database.
- `unreadable`: log lines that do not parse. One torn write from a crash costs one line and never hides the entries after it. A non-zero count needs investigation against the log's own copies before traffic resumes.

The command is idempotent. Then start the erasure worker. Byte erasure is idempotent, so objects that are already gone verify at once.

- **Also run:** `reconcile` and `complete-pending` (section 2), because payments made after the backup point are recovered from the provider's authoritative state rather than replayed.
- **Before resuming Premium workers**, run the restored-attempt check with the Premium worker environment:
  ```sh
  $PREMIUM_ENV python apps/workers/premium/run_worker.py --reconcile-restored
  ```
  The command checks each deterministic provider-attempt identity through the configured model connector before any restored Premium job is allowed to run again. A provider-confirmed prior execution is recorded in the sanitized `provider_attempt` journal, the restored job is failed and its reserved credit is returned; no second model generation is issued. If lookup is unsupported or uncertain, the job also fails closed and its credit is returned. Only a provider that can authoritatively report every possible bounded attempt as absent leaves that job safe to resume. Run the command again to confirm it is idempotent before starting ordinary Premium workers.
- The local/test fake advertises authoritative attempt lookup so the restore choreography is executable in CI. The current OpenAI `store=false` adapter does not advertise it and therefore cannot certify restored Premium work; live Premium remains gated until an approved provider configuration proves compatible authoritative lookup or an equivalent reviewed idempotency mechanism.
- Single-device logout and feedback withdrawal are queued atomically to the erasure outbox and recorded in the external tombstone log before those events are dispatched. Restore replay removes only rows that existed at the recorded withdrawal time, so a later deliberate re-registration or feedback resubmission is preserved.
- **Provider-neutral rehearsal implemented:** `infra/recovery/run_restore_drill.py` performs a real synthetic PostgreSQL custom-format backup/restore. It deliberately leaves object/tombstone storage at the newer point in time, proves the old database resurrected a deleted capture/account/permission, replays the existing tombstones, reruns ordinary erasure, verifies the object stays erased and requires a second replay to make no new changes. CI stores only the privacy-safe `recovery-receipt/1`.
- **PENDING DEPLOYMENT:** choose the managed PostgreSQL and object/tombstone providers, approve RPO/RTO from their actual capabilities, bind this choreography to their backup/PITR/version-deletion mechanisms and retain a provider-backed timed restore drill.

## 8. Mail or push outage, revoked provider key, suppression review

Notices never carry business state, so an outage only delays or drops them.
```sh
$NOTIFY_ENV python apps/workers/notifications/run_worker.py once     # one pass; counts by channel and state
$NOTIFY_ENV python apps/workers/notifications/run_worker.py suppress --recipient <principal_id> --reason COMPLAINT
$NOTIFY_ENV python apps/workers/notifications/run_worker.py unsuppress --recipient <principal_id>
```
(`$NOTIFY_ENV` = the `notification_worker` component's environment.)

- **Provider outage:** failures back off and give up after 5 attempts. Notices older than 24 h are dropped rather than sent late. No action is needed beyond watching the `notification.delivery` metric (`outcome=retry`/`failed`, `error_code`).
- **Revoked or rotated provider key:** sends fail as `provider_auth` and back off. Set the `notifications` kill switch off (pending events are consumed without sending, so no backlog floods out later), rotate the secret, redeploy only the notification worker and switch back on.
- **Bounces and complaints:** a provider-reported suppression is recorded automatically. Record others with `suppress`, and lift one only after support review. Signed bounce/complaint webhooks arrive with the ADR-007 provider.
- **PENDING DEPLOYMENT:** live mail/APNs/FCM adapters, alert thresholds and the named on-call owner.

## 9. Not yet covered (T24 later slices)

- Key rotation and compromise beyond the notification worker.
- Store rollout halt.
- Account and identity recovery (ADR-002).

Each needs its provider or hosting decision before it can list real commands.


## Runtime startup/readiness qualification

The provider-neutral T24 image boundary lives under `infra/runtime/`.
`entrypoint.py` first runs the same fail-closed preflight used by
`probe.py startup`; a manifest that is structurally valid but names provider
modes the current role cannot compose is not considered ready.

For API diagnosis, `/health/live` proves only that the process responds and
`/health/ready` checks PostgreSQL only. Do not add provider calls to either
route. Worker readiness uses `python infra/runtime/probe.py database`.
Production host/registry/alert commands remain **PENDING DEPLOYMENT** until
those providers are selected and qualified.


## Provider-neutral operational posture and halt verification

The backend runtime exposes three read-only operator commands:

```sh
$API_ENV python -m princess_api.ops snapshot
$API_ENV python -m princess_api.ops check --policy <reviewed-policy.json>
$API_ENV python -m princess_api.ops verify-disabled --switch commerce --switch premium_generation
```

`snapshot` emits `operational-snapshot/1`: fixed aggregate queue/outbox,
notification, commerce, Premium-attempt and export observations; current schema
revision; reviewed capability switches; and tombstone-log presence/readability.
It contains no principal/report/job/payment/object IDs or provider payloads.

`check` evaluates only allowlisted dimensions/measures/operators. It does not
run arbitrary SQL or expressions and never changes business state.
`verify-disabled` is a store/incident-halt proof only: manifest/redeployment
remains the authority and there is intentionally no operator command that can
enable a capability.

The checked-in test policy has synthetic thresholds solely for CI. **PENDING
DEPLOYMENT:** staging/production thresholds, named alert owners/escalation,
dashboard/export destination and edge/global limits must be approved from
actual deployed behavior; do not copy CI thresholds into an SLO.
