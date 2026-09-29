# T24 provider-neutral runtime topology

Status: **qualified packaging target, not production deployment approval**.

The repository has one source-tree application with fixed process roles.  This
directory packages the roles without changing the Free wheel boundary:
`princess_app` remains source-tree application code and is not added to the
`special-little-princess-graphology` distribution.

## Images

- `backend-runtime`: API, analysis worker, Premium worker, notification worker
  and one-shot migrations.  No Node/Chromium or provider SDK is added.
- `export-runtime`: the backend image plus the already-pinned report renderer,
  Node 22.22.2 and its Playwright Chromium.  The Python export worker keeps
  database/storage authority; the child renderer still receives only the
  authorized projection through stdin and runs with the scrubbed environment
  enforced by `SubprocessRenderer`.

The reviewed Python runtime lock is **Python 3.12 / Linux x86_64**.  Building an
ARM image requires a separately reviewed target lock.

Both images use the fixed `entrypoint.py` dispatcher. Environment variables may
select only a reviewed `PRINCESS_COMPONENT`; they cannot supply a command.

## Health and preflight

`runtime_policy.preflight` validates the environment manifest and then checks
the narrower set of provider modes the current code can actually compose. This
is intentionally stricter than parsing `production.json`: the production
target manifest describes desired live providers, while current composition
still rejects several live adapters.

The API exposes unlisted operational routes:

- `/health/live`: process response only, no I/O.
- `/health/ready`: `SELECT 1` against the runtime PostgreSQL role only.

Worker/container database probes use the same `Database.ping()`. Probes never
call identity, object storage, payments, Premium model, mail, push, analytics or
telemetry providers.

## Synthetic smoke topology

`compose.smoke.yaml` is disposable test topology only. It runs PostgreSQL,
reviewed migrations, a separate role bootstrap, then API + analysis + Premium +
export + notification processes with fake providers. The runtime API login is a
member of `princess_app`; the worker login is a member of
`princess_worker`. Neither is the database owner.

The local filesystem store and tombstones use a dedicated writable volume.
Everything else is read-only; temporary/browser state uses tmpfs. No production
credential or provider is required.

This PR does **not** choose a registry, host, object store, OIDC issuer, model,
mailer, push service, telemetry backend, backup provider, DNS/TLS setup or
secret manager.
