# Railway two-service synthetic test deployment

This is a **private, synthetic-only** deployment target, not an authorization to expose public sign-in or process real handwriting.

## Topology

- Railway `Postgres`: PostgreSQL 16, `princess_test`, persistent database volume.
- Railway `db-migrations` **repurposed**: `infra/runtime/Dockerfile` final `railway-test-runtime` target, with a persistent `/data` volume. It supervises the API and deterministic Free analysis worker, each with its own process environment and least-privilege DB account.
- No paid model calls, Premium jobs, purchases, mail or push. A narrowly scoped Railway-managed HTTPS guest-only test domain can be enabled through the separate opt-in below.
- The private S3 bucket is **not wired**: current source only implements shared local filesystem storage. Do not advertise it as active.

## One-shot database setup

Before converting the migrations service, point it at this code and set
`PRINCESS_ENV=test`, `PRINCESS_COMPONENT=migrations`,
`PRINCESS_TEST_BOOTSTRAP=1`, `PRINCESS_MIGRATION_DATABASE_URL` to the migration-owner URL and supply **separate Railway-held secrets**
`PRINCESS_BOOTSTRAP_API_PASSWORD` and `PRINCESS_BOOTSTRAP_WORKER_PASSWORD`.
This performs the existing Alembic upgrade then creates non-superuser logins that inherit the reviewed `princess_app` and `princess_worker` group roles. Do not put these values in Git, logs, or APKs.

## Combined runtime

Remove the migration-owner URL and bootstrap variables before the long-running deploy. Set
`PRINCESS_TEST_STACK=1`, `PRINCESS_ENV=test`,
`PRINCESS_API_DATABASE_URL` and `PRINCESS_WORKER_DATABASE_URL` to the respective role URLs,
`PRINCESS_SESSION_SECRET`, `PRINCESS_IDENTITY_AUDIENCE`,
`PRINCESS_STORAGE_SIGNING_KEY`, `PRINCESS_STORAGE_READ_KEY`,
`PRINCESS_LOCAL_STORAGE_DIR=/data/storage`,
`PRINCESS_TOMBSTONE_DIR=/data/tombstones` and
`PRINCESS_PUBLIC_API_BASE=http://<railway-private-service-name>.railway.internal:8000`.

The supervisor validates each child through `runtime_policy.preflight` and starts the existing fixed entrypoint with strictly curated variables, dropping privileges before network service. The API responds on port 8000; the worker shares the mounted storage directory. A child crash tears down the whole container rather than silently serving unprocessed jobs.

## Guest-only HTTPS test mode (synthetic materials only)

The Railway guest-test deployment sets `PRINCESS_TEST_PUBLIC_GUEST_ONLY=1`, `PRINCESS_GUEST_ADMISSIONS_PER_MINUTE=5` and `PRINCESS_PUBLIC_API_BASE=https://db-migrations-test.up.railway.app`. The supervisor refuses accidental public exposure when the opt-in is absent, and requires an HTTPS origin when present.

The API composes with `guest_only=true` and `dev_identity=None`. All non-guest credentials are rejected, and the `/v1/dev/id-tokens` fake-account issuer is **not registered**. Guests are limited by the durable admission policy and receive independently generated bearer credentials. The signed `/v1/dev/uploads/{upload_id}` local-store upload route remains, because this is an isolated, synthetic-only test environment, not a live object store.

Native test builds set `INKTROSPECT_APP_VARIANT=development`, `INKTROSPECT_BACKEND_ENV=test`, `INKTROSPECT_API_BASE=https://db-migrations-test.up.railway.app` and `INKTROSPECT_REMOTE_GUEST_ONLY=1` so the app has no development account login. `.github/workflows/railway-guest-apk.yml` compiles a separate, debug-key-signed, non-store APK. Keep the reviewed localhost handoff build unchanged.

The public domain and APK **do not authorize human handwriting collection or public launch**. The consent registry is still a draft valid only for synthetic tests. The Railway bucket has not been wired to the backend. Real-user activation requires reviewed notice, identity/abuse controls, storage/deletion operations and independent security review.

## Important gates

- **Never publish the normal synthetic test deployment.** The supervisor refuses `RAILWAY_PUBLIC_DOMAIN` unless the explicit guest-only HTTPS opt-in is set; the opt-in removes the public fake-account issuer, but does not approve real-user use.
- The special guest-only synthetic APK can connect over HTTPS without account identity. An actual user-facing APK remains gated on approved consent, account identity, storage and network qualification. No developer secret is embedded in the APK.
- There is one combined replica. The attached Railway volume is not a multi-replica shared filesystem.
- This test image excludes Chromium/PDF export. The report export worker and real cloud object storage are later gated work.
- Tombstones and images on the same Railway volume are not yet separately protected against restore rollback; the synthetic test environment makes **no production recovery claims**.
- Revert to the pinned previous migration source, remove `PRINCESS_TEST_STACK`, and do not expose a public domain to roll back this deployment.

## Checks

Use Railway deployment state plus deployment logs. Private Railway networking can be used for `GET /health/live` and `GET /health/ready` once a trusted internal client is available; a successful build alone is not proof of an end-to-end Android analysis.
