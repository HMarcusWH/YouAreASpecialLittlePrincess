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
