# Environments and local setup (T28)

`infra/` holds **non-secret** environment composition. Secret values never enter Git; manifests list only secret *names*.

## Environment manifests

`infra/environments/<environment>.json` declares, for `local`, `test`, `preview`, `staging` and `production`:

- the provider mode of every server-side connector port (`fake`, `sandbox` or `live`);
- the environment's database name (`princess_<environment>`);
- kill switches (`premium_generation`, `commerce`, `uploads`, `sharing`);
- for every deployable component, the secret names it may read and the egress destinations it may reach.

`princess_app.config.parse_manifest` rejects fakes in production, live adapters in local/test/preview, a secret or egress destination outside the reviewed component matrix (for example a model key on the analysis worker or any secret in a public web/native bundle), and a database name belonging to another environment. `load_runtime_config` also rejects missing secrets, test-looking credentials in production, live-looking credentials elsewhere, and a database URL naming another environment's database.

Staging and production reference `sandbox`/`live` adapters that later tasks implement; their kill switches keep uploads, Premium, commerce and sharing off until those adapters and the owner gates exist.

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

The API factory is `princess_api.compose:app_from_environment` (`uvicorn --factory`). Identity is fake-only until the ADR-002 vendor decision. The OIDC verifier in `princess_app.adapters.oidc` is implemented and tested, but no production issuer is configured.

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

Only JPEG and PNG are accepted (≤ 20 MB, ≤ 24 MP, ≤ 12 000 px per side). HEIC, GIF, WebP, SVG and archives are rejected with explicit codes, and mobile clients convert HEIC to JPEG before upload.

Local runs use the filesystem object store (`PRINCESS_LOCAL_STORAGE_DIR`, default `.local-storage/`), which is shared by the API and `apps/workers/analysis/run_worker.py`. Its upload URLs are HMAC-signed paths served by `PUT /v1/dev/uploads/{id}`, which exists only in local, test and preview (never staging or production). A real S3-compatible adapter waits on the ADR-004 provider decision, and composition refuses non-fake storage until it exists.

## Commerce ledger and metered Premium (T19)

Migration `0003_commerce_ledger` adds the internal ledger. Every rail — web checkout, StoreKit and Play — feeds the same tables:

- `payment_account` holds our opaque per-account token (a UUID). Providers carry it back as the attested account: the Stripe client reference, Apple `appAccountToken` or Play obfuscated account ID. `GET /v1/me/payment-account` hands it to native clients.
- `provider_event` is the verified webhook inbox. It stores the event ID, type and body SHA-256, and no account data.
- `financial_transaction` is unique on `(rail, environment, transaction_ref)`, so each financial identity is granted at most once. `credit_lot` keeps the origin rail. `credit_reservation` is unique per intended Premium operation. `ledger_entry` is insert-only (`GRANT`, `RESERVE`, `RELEASE`, `SPEND`, `REVOKE`, `REFUND_AFTER_SPEND`), and balances are derived from lots.
- `premium_overlay` stores the validated packet and output of a published Premium revision.

Rules the code enforces (`src/princess_app/application/commerce.py`, `adapters/postgres/commerce.py`):

- Only a server-verified `PURCHASED` observation grants credits. It must come from this deployment's environment, be a catalog product on that rail, and carry the account's own token. A checkout redirect, a client flag or event arrival order never grants. Pending, wrong-environment, unknown-product and foreign-account purchases grant nothing.
- Each owner's grants, refunds, reservations and releases serialize on a per-owner advisory lock, so two devices cannot both reserve the last credit.
- Play consumption (or acknowledgement for non-consumables) follows the durable grant. If it fails, the grant stands and `CommerceService.complete_pending` retries it. Apple transactions are finished by the client after the claim response says so. Stripe needs no completion.
- `POST /v1/reports/{id}/premium` needs an account, open sales (`commerce` and `premium_generation` kill switches), a current `third_party_ai_processing` grant for the report, and an eligible credit. It reserves the credit and creates the job in one transaction; repeating the same request returns the same job.
- The Premium worker publishes the overlay revision and spends the reservation in one transaction. That transaction is fenced on the job lease, the permission epoch, account deletion, report deletion or revision, and a live reservation. A refused, failed or fenced attempt releases the credit. A transient or ambiguous provider outcome is retried once, then released, so the customer is never charged twice for one deliverable.
- A refund revokes the unspent credit and any active reservation, which blocks publication. After a spend it records `REFUND_AFTER_SPEND`. Who keeps access to delivered Premium content after a refund is an owner decision. Late notifications for a deleted account grant nothing.
- By default, credits can be spent only on their origin platform (web credits on web, and so on). Cross-store portability needs an approved, dated policy record.

Reconciliation runbook (fakes today; the same calls apply to real adapters):

1. Missed or delayed webhooks: run `CommerceService.reconcile(rail, since, ctx)`. It re-reads authoritative provider state and applies it idempotently, so refunds and settled pending purchases converge.
2. Grants whose store completion is outstanding: run `complete_pending` with the worker login. Alert on the age of the oldest `financial_transaction` with `completed_at IS NULL`.
3. Reservations stuck in `RESERVED` belong to live Premium jobs. Check the job state before releasing anything by hand, and use `release_reservation` so the ledger entry is written.
4. Never delete ledger rows. Corrections are compensating entries.

Scheduling these loops (which process, how often, alerts) belongs to T24. Real Stripe, App Store Server API and Play Developer API adapters, sandbox evidence, prices, tax and refund terms are blocked on `price_account_terms_before_charges` and `processor_retention_contracts`. Composition refuses non-fake payment providers until then.
