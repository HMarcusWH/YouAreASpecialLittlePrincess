# Local development setup

Run commands from the repository root unless a step says otherwise. Use **synthetic data only** with local/test fake providers. This guide is derived from the checked-in lockfiles, manifests and runners; a fresh receiving-maintainer run is recorded separately in [acceptance](../handover/acceptance.md). Do not interpret a documented recipe as a new device/provider approval.

## Host and toolchain profiles

| Work | Supported evidence / prerequisites |
|---|---|
| Core Python tests | Reviewed Linux x86_64 locks for Python 3.10–3.12; see [requirements](../../requirements/README.md) |
| Backend and integration | Python 3.12 on Linux x86_64, PostgreSQL 16, `psql`, Bash, curl and the reviewed app lock; Docker is an alternative for the database/runtime |
| Native JavaScript | Node version from [.node-version](../../.node-version), Corepack and the exact `packageManager` in [package.json](../../package.json), frozen pnpm lock |
| Android native build | Reviewed JDK/Android SDK/Gradle configuration, system dependencies and the package matrix in [COMPATIBILITY.md](../../apps/mobile/COMPATIBILITY.md) |
| iOS native build | macOS and the Xcode/pods/deployment matrix in the native compatibility record; iOS is not built on Linux |
| Windows or ARM backend | No new lock/platform qualification is asserted. Use the reviewed Linux x86_64 runtime/host, or qualify the new host deliberately; do not force Linux wheel hashes onto macOS/Windows/ARM |

The repository's version pins are reproduction inputs, not recommendations to install an unverified latest release. Expo Go is not sufficient for these native modules. Start with local native development builds; signing, physical devices and store accounts have separate owner gates.

## 1. Install the backend on Linux x86_64

Python 3.12 and the system tools above must already be installed. Do not install the optional learned `signature` extra for Free. Start with a new virtual environment; an existing environment with unrelated packages is not an exact locked install.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements/app-py312.lock
.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation -e '.[dev]'
.venv/bin/python tools/verify_ci_lock.py requirements/app-py312.lock --manifest requirements/app-py312.txt --allow 'special-little-princess-graphology==0.1.0'
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD/apps/api"
```

`princess_app` is source-tree application code, not part of the Free wheel. An editable core installation alone does not provide the backend dependencies or make the API importable without the source paths. In each new shell, activate this environment and set the source paths again before using an unqualified `python` command.

For core-only work, replace the app lock with the `requirements/ci-py310`, `ci-py311` or `ci-py312` lock matching the reviewed interpreter/architecture, then use the core checks in [testing](testing.md). Do not mix locks in the same environment and call it an exact locked environment.

## 2. Start the disposable local database and migrate

**Mutating local setup.** The database in this recipe is `princess_local` on loopback port 5432. Never substitute a production host or dump. The documented passwords below are local-only examples, not production credentials. Run the following as one Bash block; a failed readiness check must stop before migration.

```bash
(
set -euo pipefail
docker compose -f infra/local/compose.yaml up -d
LOCAL_ADMIN='postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_local'
db_ready=0
for attempt in {1..30}; do
  if PGCONNECT_TIMEOUT=2 psql "$LOCAL_ADMIN" -Atqc 'SELECT 1' >/dev/null 2>&1; then
    db_ready=1
    break
  fi
  sleep 1
done
if [ "$db_ready" != 1 ]; then
  printf '%s\n' 'Local PostgreSQL did not become ready; inspect compose logs and stop here.' >&2
  exit 1
fi
PRINCESS_MIGRATION_DATABASE_URL="$LOCAL_ADMIN" .venv/bin/python -m princess_app.adapters.postgres.migrate upgrade
psql "$LOCAL_ADMIN" -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_local_api') THEN
    CREATE ROLE princess_local_api LOGIN PASSWORD 'local-only-api';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_local_worker') THEN
    CREATE ROLE princess_local_worker LOGIN PASSWORD 'local-only-worker';
  END IF;
END $$;
GRANT princess_app TO princess_local_api;
GRANT princess_worker TO princess_local_worker;
SQL
)
```

Only the setup/migration connection is an owner/admin. API and worker logins must not own tables or have superuser/BYPASSRLS. Existing roles are not silently reset by the SQL above; use the passwords actually established on a reused disposable cluster. Read [migrations](../../migrations/README.md) before changing role ownership.

## 3. Start the API

Choose the API origin **as reached by the client**. For a physical phone use the development host's reachable LAN address, not the phone's loopback. The API advertises this origin in signed upload URLs. The native config must allow the same origin. The default below listens on loopback only.

```bash
export PRINCESS_ENV=local
export PRINCESS_COMPONENT=api
export PRINCESS_DATABASE_URL='postgresql://princess_local_api:local-only-api@127.0.0.1:5432/princess_local'
export PRINCESS_SESSION_SECRET='local-session-secret-handover'
export PRINCESS_IDENTITY_AUDIENCE='princess-api'
export PRINCESS_STORAGE_SIGNING_KEY='local-storage-key-handover'
export PRINCESS_LOCAL_STORAGE_DIR="$PWD/.local-storage"
export PRINCESS_TOMBSTONE_DIR="$PWD/.local-tombstones"
export PRINCESS_PUBLIC_API_BASE='http://127.0.0.1:8000'
export PYTHONPATH="$PWD/src:$PWD/apps/api"
.venv/bin/python -m uvicorn --factory princess_api.compose:app_from_environment --host 127.0.0.1 --port 8000
```

For a phone, replace `127.0.0.1` in `PRINCESS_PUBLIC_API_BASE` with the approved development LAN address and start uvicorn with `--host 0.0.0.0`. That exposes the development API to the network: restrict it to a trusted development network/firewall and never expose fake identity publicly. When backend and native tooling are on different hosts, only the API must be reachable from the device; do not expose the PostgreSQL port.

In another terminal, read-only checks:

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:8000/v1/consent-notices
```

Liveness/readiness return `{"status":"ok"}` when the relevant process/database check passes. The notice response is a catalogue, not a permission grant. Draft notices authorize synthetic local/test use only.

## 4. Start the analysis/erasure worker

In a separate terminal, at the same checkout and with the same private storage/tombstone directories:

```bash
export PYTHONPATH="$PWD/src:$PWD/apps/api"
PRINCESS_ENV=local PRINCESS_COMPONENT=analysis_worker \
  PRINCESS_DATABASE_URL='postgresql://princess_local_worker:local-only-worker@127.0.0.1:5432/princess_local' \
  PRINCESS_STORAGE_READ_KEY='local-storage-key-handover' \
  PRINCESS_LOCAL_STORAGE_DIR="$PWD/.local-storage" PRINCESS_TOMBSTONE_DIR="$PWD/.local-tombstones" \
  .venv/bin/python apps/workers/analysis/run_worker.py
```

The worker performs deterministic analysis and its erasure/retention work. Without the worker, an accepted run may remain queued. Do not start unnecessary paid/provider workers to make Free work.

## 5. Install the JavaScript workspace and renderer dependencies

Activate the pinned Node version using your installed version manager, then:

```bash
node --version
corepack enable
corepack install
pnpm install --frozen-lockfile
pnpm --filter @princess/mobile compat:check
EXPO_OFFLINE=1 pnpm --filter @princess/mobile exec expo install --check
pnpm typecheck
```

For browser/render tests or PDF exports:

```bash
pnpm --filter @princess/web exec playwright install --with-deps chromium
pnpm --filter @princess/render run build
```

The Playwright installation may install system packages; use a disposable/approved development machine. The [export runtime](../../infra/runtime/README.md) provides the alternative packaged Chromium boundary. A source-tree export worker uses the built renderer and its pinned browser installation; the optional `PRINCESS_CHROMIUM` variable selects an approved executable when that installation needs an override. The relevant source is [run_worker.py](../../apps/workers/export/run_worker.py). Never substitute an arbitrary browser URL.

Start the export worker in a separate terminal using the worker connection and same storage:

```bash
export PYTHONPATH="$PWD/src:$PWD/apps/api"
PRINCESS_ENV=local PRINCESS_COMPONENT=export_worker \
  PRINCESS_DATABASE_URL='postgresql://princess_local_worker:local-only-worker@127.0.0.1:5432/princess_local' \
  PRINCESS_STORAGE_READ_KEY='local-storage-key-handover' \
  PRINCESS_LOCAL_STORAGE_DIR="$PWD/.local-storage" \
  .venv/bin/python apps/workers/export/run_worker.py
```

## 6. Launch the native development build

On the Android development host or the macOS iOS host, install the same JS workspace. Set the same device-reachable API origin as the API advertises. The following loopback example is only appropriate when the simulator/client can reach that host loopback:

```bash
export INKTROSPECT_APP_VARIANT=development
export INKTROSPECT_BACKEND_ENV=local
export INKTROSPECT_API_BASE='http://127.0.0.1:8000'
pnpm --filter @princess/mobile config:public
pnpm --filter @princess/mobile android
```

On macOS with the reviewed Xcode/pods matrix, use `pnpm --filter @princess/mobile ios` instead. A physical device normally needs the LAN origin. Android emulator host aliases, a remote Linux backend and Windows/WSL networking must be checked from the actual client; do not assume `localhost` denotes the backend. See [troubleshooting](troubleshooting.md).

Build-time variables feed native configuration; changing identifiers, plugins or native permissions requires rebuilding, not only refreshing JavaScript. Staging/store configuration deliberately rejects development identity and unsafe origins. Selecting a store variant does not provision signing/accounts or authorize a release.

Use a synthetic specimen, create a guest, review the displayed draft choices, capture/select the specimen and wait for the saved report. Exercise retained and non-retained image states deliberately. Development account entry is not a real provider login.

## 7. Automated native-controller journey

**Destructive: drops and recreates `princess_test`.** Stop other test processes using that database. This runner refuses non-loopback targets, requires `/postgres` at port 5432 and explicit opt-in. It starts its own API/workers and creates synthetic samples; it does not launch the native UI.

```bash
PYTHON=.venv/bin/python \
  PRINCESS_E2E_ADMIN_URL='postgresql://princess_admin:local-only-admin@127.0.0.1:5432/postgres' \
  PRINCESS_E2E_ALLOW_RESET=1 PRINCESS_E2E_EXPORTS=1 \
  tools/run_mobile_journey.sh
```

Do not run this concurrently with the web journey or backend tests using `princess_test`. The real app-driving/device exercise remains separate acceptance work.

## Shutdown and deletion

Use Ctrl-C in API/worker/native-dev terminals. `docker compose -f infra/local/compose.yaml stop` preserves the development database. **Destructive cleanup:** `docker compose -f infra/local/compose.yaml down -v` removes its local database volume. Application-private `.local-storage` and `.local-tombstones` directories are separate; delete them only after verifying they contain this disposable development data and all processes are stopped. Never put either into Git. Do not use a documentation cleanup command against production evidence or tombstones.
