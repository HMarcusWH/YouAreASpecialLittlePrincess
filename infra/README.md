# Environments and local setup (T28)

`infra/` holds **non-secret** environment composition. Secret values never enter Git; manifests list only secret *names*.

## Environment manifests

`infra/environments/<environment>.json` declares, for `local`, `test`, `preview`, `staging` and `production`:

- the provider mode of every server-side connector port (`fake`, `sandbox` or `live`);
- the environment's database name (`princess_<environment>`);
- kill switches (`premium_generation`, `commerce`, `uploads`, `sharing`, `notifications`);
- for every deployable component, the secret names it may read and the egress destinations it may reach.

`princess_app.config.parse_manifest` rejects fakes in production, live adapters in local/test/preview, a secret or egress destination outside the reviewed component matrix (for example a model key on the analysis worker or any secret in a public web/native bundle), and a database name belonging to another environment. `load_runtime_config` also rejects missing secrets, test-looking credentials in production, live-looking credentials elsewhere, and a database URL naming another environment's database.

Staging and production reference `sandbox`/`live` adapters that later tasks implement; their kill switches keep uploads, Premium, commerce, sharing and notifications off until those adapters and the owner gates exist.

```bash
python tools/check_environments.py          # validate every manifest
```

## Local development

Everything runs with fakes, synthetic fixtures and a local PostgreSQL 16:

```bash
# Option A: Docker (image pinned by digest)
docker compose -f infra/local/compose.yaml up -d
# Option B: an installed PostgreSQL 16 cluster
sudo -u postgres psql -c "CREATE ROLE princess_admin LOGIN SUPERUSER PASSWORD 'local-only-admin';"
sudo -u postgres psql -c "CREATE DATABASE princess_local OWNER princess_admin;"
sudo -u postgres psql -c "CREATE DATABASE princess_test OWNER princess_admin;"

# Backend environment (Python 3.12, hash-locked)
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements/app-py312.lock
.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation -e '.[dev]'
.venv/bin/python tools/verify_ci_lock.py requirements/app-py312.lock --manifest requirements/app-py312.txt \
    --allow "special-little-princess-graphology==0.1.0"

# JavaScript workspace (Node 22.22+, pnpm pinned through packageManager)
corepack enable && pnpm install --frozen-lockfile
pnpm typecheck && pnpm test
```

Teardown: `docker compose -f infra/local/compose.yaml down -v`, or drop `princess_local`/`princess_test`.

The local admin password above is a documented development-only value for a loopback-bound database; it is not a secret and is refused by the production manifest rules.

## Dependency environments

| Environment | Manifest / lock | Contents |
|---|---|---|
| Free numerical library | `requirements/ci-py3{10,11,12}.{txt,lock}` | Core only; `princess_app` is excluded from the wheel |
| Backend application | `requirements/app-py312.{txt,lock}` | The exact core pins plus FastAPI, SQLAlchemy, Alembic, psycopg, httpx, PyJWT/cryptography. No model, payment or cloud SDK |
| JavaScript workspace | `package.json`, `pnpm-lock.yaml` | Exact versions only; pnpm pinned with a SHA-512 in `packageManager` |

Provider SDKs are added by the task that implements each real adapter, with their own reviewed pins, and never to the Free library.

## Database migrations and the API (T02)

Migrations are reviewed Alembic revisions under `migrations/versions/`, run with a migration-role URL (never the runtime role):

```bash
PRINCESS_MIGRATION_DATABASE_URL=postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_local \
  .venv/bin/python -m princess_app.adapters.postgres.migrate upgrade
```

`0001_product_plane` creates the `app` schema and the `princess_app` group role. The runtime login role must be a member of `princess_app`, and must not own the tables, be a superuser or hold `BYPASSRLS`. Every transaction sets `princess.principal_id` locally, and row-level security scopes principals, assets, runs, measurements, regions, evidence, reports, permissions, jobs and outbox rows to that principal. Measurements, regions, evidence, report revisions and permission events can be inserted but never updated or deleted by the runtime role. Composite `(owner_id, id)` foreign keys prevent cross-owner or cross-run links. The downgrade refuses to drop a populated schema.

Backend integration tests use a real PostgreSQL database and connect as a separate non-owner role:

```bash
PRINCESS_TEST_DATABASE_URL=postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_test \
  .venv/bin/python -m pytest -q tests_app
```

The API factory is `princess_api.compose:app_from_environment` (`uvicorn --factory`). Identity remains fake-only after the ADR-002 owner selected Supabase Auth: the exact managed project/account/profile and processor gate still require qualification before runtime composition. The generic OIDC verifier remains implemented and tested, but no production issuer is configured.

## Intake and the analysis worker (T04)

The upload flow runs in this order:

1. `POST /v1/uploads` reserves an upload slot and returns the upload URL (presigned or signed).
2. The client PUTs the bytes to that URL.
3. `POST /v1/uploads/{id}/complete` sends the SHA-256. The server promotes the bytes to an immutable version, sniffs the real format, rejects pixel bombs or animated files from the header, and records a **capture**. It does not start a run.
4. `POST /v1/me/permissions` records a `service_processing` grant for that capture.
5. `POST /v1/analyses` idempotently creates one run and job per capture and configuration.

The worker then claims a leased job, decodes within limits, runs the zero-AI engine, and builds the evidence and report outside any transaction. It publishes in one short transaction only if all of these still hold:

- its fencing token is current;
- the lease has not expired;
- the job was not cancelled;
- the capture was not deleted;
- the `service_processing` permission epoch has not changed.

Deletion or withdrawal ends the job. Repeatedly crashing workers exhaust after a bounded number of attempts, and the run is marked failed.

Admission and completion details:

- Reservations are counted under a per-owner lock (3 per day, 20 with an accepted challenge). A challenge token is checked against the server-owned action `upload` and site `PRINCESS_CHALLENGE_SITE`; the client sends only the token.
- One completion at a time holds a slot (`COMPLETING`). A retry converges only when it declares the same SHA-256; a wrong digest leaves the slot open, and unsafe bytes are erased and the slot rejected.
- A worker refuses a run requested under other engine settings (`analysis_config_mismatch`).
- Guest transfer cancels the guest's queued and running analyses (`owner_transferred`). The account records its own permissions and resubmits.

Retention (T03 `retention.json`, still a draft pending owner review) is applied by the erasure consumer that runs inside the analysis worker process:

- Deleting a capture, or withdrawing `service_processing` for it, tombstones the capture and its reports and erases every object version.
- When an analysis finishes, the original is erased unless an `image_retention` grant covers the capture. Withdrawing `image_retention` queues the same check. The report and its measurements are kept.
- Erasure is verified before an outbox event is marked dispatched; an unverified erasure is retried.
- Bytes that fail inspection at completion move the upload to `REJECTED` and queue an `upload.rejected` erasure in the same transaction, so a failed delete is retried rather than stranded.
- Withdrawing or denying `service_processing` or `image_retention` queues `permission.withdrawn` in the same transaction as the decision. The API applies the effects at once, and the erasure worker re-applies them (idempotently) if the process died in between.
- A deleted capture's bytes are erased and verified first; then `app.erase_capture_records` (migration `0006_durable_erasure`) removes its runs, measurements, regions, evidence, reports, exports and Premium overlays, and releases any open Premium reservation. The capture row stays as the tombstone.
- A capture's `asset.deleted_at` is set only after its bytes are verified erased; access ends earlier, with the capture tombstone. A completed capture that never went on to an analysis (for example, the browser closed before the permission was recorded) gets a retention review after 24 hours (a draft value pending the owner; `app.review_idle_captures`).
- Withdrawal effects follow the current permission, so a replayed or late withdrawal never deletes a capture granted since.
- Cancelling an analysis queues the same retention review as every other terminal path. Upload slots that expire unused, or whose completion crashed, are revoked and their bytes erased (`app.expire_upload_slots`, swept by the erasure worker).
- Account deletion (`account.deletion_requested`) erases every remaining asset of the account and verifies it. Only then does `app.erase_deleted_account` (migration `0004_erasure_admission`) delete its uploads, captures, runs, measurements, reports and Premium overlays. Consent history, the financial ledger and the principal tombstone stay as accountability and accounting records.

Guest creation is capped globally per minute (`PRINCESS_GUEST_ADMISSIONS_PER_MINUTE`, default 300; over the cap the API answers 429 with `Retry-After`). Per-network limits belong at the edge. Request bodies for payment webhooks (256 KiB) and the local upload route (20 MB) are refused with 413 before they are buffered.

Only JPEG and PNG are accepted (≤ 20 MB, ≤ 24 MP, ≤ 12 000 px per side). HEIC, GIF, WebP, SVG and archives are rejected with explicit codes, and mobile clients convert HEIC to JPEG before upload.

Local runs use the filesystem object store (`PRINCESS_LOCAL_STORAGE_DIR`, default `.local-storage/`), which is shared by the API and `apps/workers/analysis/run_worker.py`. Its upload URLs are HMAC-signed paths served by `PUT /v1/dev/uploads/{id}`, which exists only in local, test and preview (never staging or production). A real S3-compatible adapter waits on the ADR-004 provider decision, and composition refuses non-fake storage until it exists.

## Report exports: PDF and share cards (T21)

Migration `0005_report_exports` adds `report_export`. Components:

- `apps/render` (the `render_worker` boundary) is Node plus offline Chromium. It gets one authorized projection on stdin and nothing else: no database, no storage key, no model key, JavaScript off, every request aborted. Documents render the `EXPORT` projection (A4 or Letter, tagged PDF). Cards render a `SHARE` projection limited to the sections the owner picked (1080×1080 or 1080×1920 PNG). Build it with `pnpm --filter @princess/render run build`.
- `apps/workers/export/run_worker.py` (component `export_worker`: database and object store, no model key) claims export jobs. It derives the projection from the saved report and runs the renderer as a child with a scrubbed environment. It checks the output type and size, stores the bytes as an `EXPORT` asset, and publishes, fenced on the job lease, a live owner and report, and an unchanged projection.
- `POST /v1/report-exports` (`report_id`, `layout`, and `sections` for cards; cards also need the `sharing` switch), `GET /v1/report-exports/{id}` and `GET /v1/report-exports/{id}/file`. Re-exporting never calls a model.

Share cards also need a current `ordinary_sharing` grant (scope `SHARE_GRANT`). It is named in the request and re-checked at publication and on every retrieval, so withdrawing it revokes and erases the card. Each render attempt writes to an asset ID derived from the export and the job's fencing token, so bytes left by a crashed worker are found and erased when the job is reclaimed or gives up. An owner can start at most 20 renders per rolling day, completed ones included.

The cache key is the digest of the authorized projection (without its generation time), the layout, the template and, for cards, the grant. Anything that changes what may be shown yields a new key: an erased original, an erased Premium payload or a new revision. Retrieval re-derives the key, and a stale export is revoked and its bytes queued for erasure (`asset.erasure_requested`). Deleting a capture revokes its reports' exports, and account erasure removes them with the other assets. A file the owner already downloaded cannot be recalled; the status DTO says so. The source image is not embedded yet, so every export carries the "source image omitted" notice.

## Notifications: push and mail (T24)

Migration `0008_notifications` adds `push_installation`, `notification_preference`, `notification_delivery` and `mail_suppression`.

- `POST /v1/me/push-installations` (`device_token`, `platform` `apns`/`fcm`, `app_environment`, `locale`) binds a device to the signed-in principal. A build for another backend environment is refused. Registering the same token again returns the same binding. A token registered by another account moves to that account, and anything still queued for the previous one is dropped. Each principal keeps at most 10 bindings (oldest dropped). `GET` lists bindings without tokens, and `DELETE /v1/me/push-installations/{id}` is the logout/account-switch call.
- `GET`/`PUT /v1/me/notification-preferences` (`mail_report_ready`, `locale`). Mail is opt-in and needs an account; guests get push only.
- The API role can register and delete bindings but can never read a token back. Only the notification worker's role reads tokens.
- `apps/workers/notifications/run_worker.py` (component `notification_worker`: database plus mail/push providers, nothing else) turns each `report.ready` outbox event into delivery records and marks the event dispatched in the same transaction. Its delivery key, derived from the event and target, is also the provider delivery key, so a replayed event or a second worker plans nothing new. Before each send it re-reads the account, report, binding, opt-in and suppression. Notices carry a generic kind, an opaque report ID and an `app://` link only. Transient failures and refused provider credentials back off (30 s doubling, at most 5 attempts). Notices older than 24 h are dropped. `unregistered` or `environment_mismatch` retires the binding. An ambiguous mail send is retried on the same key only when the provider deduplicates on it; an ambiguous push is not retried. With the `notifications` switch off, events are consumed without sending. Delivery records are kept 30 days (draft).
- A guest's bindings move to the account when the guest signs in (`0009`), so account erasure also removes them, along with preferences, delivery records and suppressions. Capture erasure removes its report's delivery records.

Only fake mail and push adapters compose today. Live mail waits on the ADR-007 provider decision, and APNs/FCM on native signing accounts (T29–T31). The API never calls a provider.

## Commerce ledger and metered Premium (T19)

Migration `0003_commerce_ledger` adds the internal ledger. Every rail — web checkout, StoreKit and Play — feeds the same tables:

- `payment_account` holds our opaque per-account token (a UUID). Providers carry it back as the attested account: the Stripe client reference, Apple `appAccountToken` or Play obfuscated account ID. `GET /v1/me/payment-account` hands it to native clients.
- `provider_event` is the verified webhook inbox. It stores the event ID, type and body SHA-256, and no account data.
- `financial_transaction` is unique on `(rail, environment, transaction_ref)`, so each financial identity is granted at most once. `credit_lot` keeps the origin rail. `credit_reservation` is unique per intended Premium operation. `ledger_entry` is insert-only (`GRANT`, `RESERVE`, `RELEASE`, `SPEND`, `REVOKE`, `REFUND_AFTER_SPEND`), and balances are derived from lots.
- `premium_overlay` stores the validated packet and output of a published Premium revision. Withdrawing or denying `third_party_ai_processing` erases both, in the transaction that records the decision (a trigger on `permission_event`); the digests remain as the tombstone and the overlay reads as revoked.

Rules the code enforces (`src/princess_app/application/commerce.py`, `adapters/postgres/commerce.py`):

- Only a server-verified `PURCHASED` observation grants credits. It must come from this deployment's environment, be a catalog product on that rail, and carry the account's own token. A checkout redirect, a client flag or event arrival order never grants. Pending, wrong-environment, unknown-product and foreign-account purchases grant nothing.
- Each owner's grants, refunds, reservations and releases serialize on a per-owner advisory lock, so two devices cannot both reserve the last credit.
- Play consumption (or acknowledgement for non-consumables) follows the durable grant. If it fails, the grant stands and `CommerceService.complete_pending` retries it. Apple transactions are finished by the client after the claim response says so. Stripe needs no completion.
- `POST /v1/reports/{id}/premium` needs an account, open sales (`commerce` and `premium_generation` kill switches), a current `third_party_ai_processing` grant for the report, and an eligible credit. It reserves the credit and creates the job in one transaction; repeating the same request returns the same job.
- The Premium worker publishes the overlay revision and spends the reservation in one transaction. That transaction is fenced on the job lease, the permission epoch, account deletion, report deletion or revision, and a live reservation. A refused, failed or fenced attempt releases the credit. A transient or ambiguous provider outcome is retried once, then released, so the customer is never charged twice for one deliverable.
- `GET /v1/reports/{id}/premium` returns the purchased overlay (answers, soft fields, omissions) while it is unlocked; report reads resolve Premium access and source-image availability on every request. Neither ever calls a model.
- A refund revokes the unspent credit and any active reservation and cancels the reservation's queued or leased job, which blocks the provider call or publication. After a spend it records `REFUND_AFTER_SPEND`. Who keeps access to delivered Premium content after a refund is an owner decision. Late notifications for a deleted account grant nothing.
- By default, credits can be spent only on their origin platform (web credits on web, and so on). Cross-store portability needs an approved, dated policy record.

Reconciliation runbook (fakes plus the production-disabled Stripe/Apple/Google adapters; live composition is still gated):

1. Missed or delayed webhooks: run `CommerceService.reconcile(rail, since, ctx)`. It re-reads authoritative provider state and applies it idempotently, so refunds and settled pending purchases converge.
2. Grants whose store completion is outstanding: run `complete_pending` with the worker login. Alert on the age of the oldest `financial_transaction` with `completed_at IS NULL`.
3. A payment that arrives after account deletion grants nothing and triggers `request_refund_if_supported`; the provider event outcome is `owner_deleted_refund_requested`, or `owner_deleted_refund_pending` when the refund request failed and needs an operator.
4. A Premium job whose final permitted attempt lost its lease (a crashed worker) is failed by the worker's `reap` step and its credit is released; it is never claimed again.
5. Reservations stuck in `RESERVED` belong to live Premium jobs. Check the job state before releasing anything by hand, and use `release_reservation` so the ledger entry is written.
4. Never delete ledger rows. Corrections are compensating entries.

Scheduling these loops (which process, how often, alerts) belongs to T24. PR #35 implements the Stripe base adapter and PR #36 adds separately approved Stripe refund requests plus production-disabled App Store Server API and Play Developer API adapters. Composition still refuses every non-fake PaymentProvider. Real provider-account sandbox/TestFlight/license-test evidence, prices, tax/refund/storefront policy and processor approval remain blocked on `price_account_terms_before_charges` and `processor_retention_contracts`.


## Provider-neutral runtime images (T24)

`infra/runtime/` now defines the source-tree backend/export image boundary,
fixed component dispatcher, fail-closed composition preflight, database-only
readiness probe and disposable role-separated smoke topology. The runtime Python
lock is a reviewed Python 3.12/Linux x86_64 subset of the existing application
lock and excludes build/test tooling.

This is packaging/qualification evidence, not a hosting decision. Current
production provider modes still intentionally fail startup where live adapters
are not approved/composed. See [runtime topology](runtime/README.md).


## Provider-neutral restore rehearsal (T24)

`infra/recovery/` now rehearses a real PostgreSQL custom-format
`pg_dump`/`pg_restore` cycle using only synthetic test data. PostgreSQL is
rolled back while the object/tombstone plane deliberately stays at the newer
point in time. The drill proves that an old database really resurrects a
deleted capture, account and permission grant, then runs the ordinary
`princess_api.ops replay-tombstones` and erasure machinery to remove that
resurrection again. A second replay must be idempotent.

The generated `recovery-receipt/1` contains only hashes, timings and counts.
CI timings are observations, **not** approved production RPO/RTO values. This
does not select a managed PostgreSQL host or object/tombstone provider and does
not prove their PITR, retention, version-deletion or regional guarantees.


## Provider-neutral operational posture (T24)

`infra/operations/` defines `operational-snapshot/1` and a fixed alert-policy
contract. Migration `0011_operational_snapshot` adds a SECURITY DEFINER
aggregate function that returns only bounded counts, ages and attempt maxima.
The normal API role still cannot raw-read another tenant's rows; unconstrained
job kinds/outbox topics are collapsed to reviewed categories before leaving
PostgreSQL.

`python -m princess_api.ops snapshot` and `check --policy ...` deliberately
avoid composing external providers, so they remain usable during provider
incidents. `verify-disabled` proves reviewed manifest switches are off but
cannot mutate them. Runtime CI exercises a passing synthetic policy and then
injects a stale queue item and requires the same policy to fail with a fixed
alert code.

No production alert threshold, exporter, dashboard vendor, pager route or SLO
is selected by this slice.


## Release/rollback qualification (T24)

`infra/release/` contains the provider-neutral application rollout contract. CI generates an exact
`runtime-release/1` for the candidate and rollback-base checkouts, migrates the database forward with the
candidate migration artifact, and proves that the immediately previous API/Free-analysis runtime can run on that
forward schema. The database is never downgraded as part of application rollback.

The qualification also replays the real #38 → #39 additive migration witness (`0010_provider_attempt` →
`0011_operational_snapshot`) with the #38 runtime on both sides of the migration. Receipts are CI artifacts,
not committed release declarations. See [release qualification](release/README.md).
