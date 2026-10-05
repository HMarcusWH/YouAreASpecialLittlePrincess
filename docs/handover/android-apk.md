# Android developer-handoff APK quick start

This page is the shortest path for installing the current Inktrospect Android handoff build and running the deterministic Free journey against a local backend.

The APK is **not committed to the Git tree**. It is a generated GitHub Actions artifact built from merged `main` by [Native foundation](../../.github/workflows/native.yml). Keeping the ~100 MB binary out of Git avoids treating a generated development build as source.

## Current merged-main APK

| Item | Value |
|---|---|
| Source commit | `c10fc4346ce433acb34fb6f0640010604ea158ab` |
| Native workflow run | [37245428939](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37245428939) |
| Artifact | [inktrospect-android-handoff-c10fc4346ce433acb34fb6f0640010604ea158ab](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37245428939/artifacts/11319039065) |
| APK inside artifact | `inktrospect-handoff-c10fc4346ce4.apk` |
| APK SHA-256 | `d07dd980992eddbb8d2a9c88dd54835dc0b4fa22de44c1488a7437f1ae23d2b6` |
| Artifact ZIP SHA-256 | `e578eef1b50b34022a659c142ebef278ec78428d24674b25da7f974b2f423b4a` |
| Artifact retention | 30 days; this one expires 2026-11-04 |

The artifact download is a ZIP containing the APK, its `.sha256` sidecar, `BUILDINFO.json` and `HANDOFF.md`. GitHub may require you to be signed in to download Actions artifacts.

If this exact artifact has expired, open the latest successful **Native foundation** run on `main` and download the artifact named `inktrospect-android-handoff-<full-main-sha>`. Do not use the similarly named `inktrospect-android-dev-client-...` artifact: that is the Metro/dev-client build.

## Install the APK

You can copy the APK to an Android phone and allow **Install unknown apps**, or install with ADB:

```bash
adb devices
adb install -r inktrospect-handoff-c10fc4346ce4.apk
```

This is a development/debug-signed handoff build, not a Google Play binary. It embeds the Hermes application bundle and does not need Metro.

The APK is built to call `http://127.0.0.1:8000`. It will launch without a backend, but **Start privately** cannot create a guest session until that address reaches the local Inktrospect API.

## Local backend quick start

The reviewed backend setup targets **Linux x86_64**, Python 3.12, PostgreSQL 16, Docker, `psql`, Bash and curl. For all details and safety notes, use [local setup](../development/local-setup.md).

Check out the same source used for the APK:

```bash
git checkout c10fc4346ce433acb34fb6f0640010604ea158ab
```

Create the locked Python environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps \
  -r requirements/app-py312.lock
.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation -e '.[dev]'
.venv/bin/python tools/verify_ci_lock.py requirements/app-py312.lock \
  --manifest requirements/app-py312.txt \
  --allow 'special-little-princess-graphology==0.1.0'

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD/apps/api"
```

Start the disposable local PostgreSQL service, migrate it and create the non-owner API/worker logins:

```bash
docker compose -f infra/local/compose.yaml up -d

LOCAL_ADMIN='postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_local'

PRINCESS_MIGRATION_DATABASE_URL="$LOCAL_ADMIN" \
  .venv/bin/python -m princess_app.adapters.postgres.migrate upgrade

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
```

Start the API in one terminal:

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

.venv/bin/python -m uvicorn --factory princess_api.compose:app_from_environment \
  --host 127.0.0.1 --port 8000
```

Start the deterministic analysis worker in another terminal:

```bash
export PYTHONPATH="$PWD/src:$PWD/apps/api"

PRINCESS_ENV=local \
PRINCESS_COMPONENT=analysis_worker \
PRINCESS_DATABASE_URL='postgresql://princess_local_worker:local-only-worker@127.0.0.1:5432/princess_local' \
PRINCESS_STORAGE_READ_KEY='local-storage-key-handover' \
PRINCESS_LOCAL_STORAGE_DIR="$PWD/.local-storage" \
PRINCESS_TOMBSTONE_DIR="$PWD/.local-tombstones" \
.venv/bin/python apps/workers/analysis/run_worker.py
```

Confirm the API is alive:

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Both should return `{"status":"ok"}`.

## Connect a physical Android phone

Enable USB debugging, attach exactly one device and forward the APK's loopback API address to the development computer:

```bash
adb devices
adb reverse tcp:8000 tcp:8000
adb reverse --list
```

Then launch Inktrospect. **Start privately** should create the local guest session, and a synthetic or explicitly authorized handwriting image can traverse the real deterministic Free analysis path to a saved Dossier.

Repeat `adb reverse tcp:8000 tcp:8000` after the phone restarts or reconnects.

If the app launches but **Start privately** shows **Something went wrong**, first check:

```bash
curl --fail http://127.0.0.1:8000/health/ready
adb reverse --list
```

The handoff APK has no production backend fallback. A different API origin requires another build.

## Scope

This APK is qualified as a standalone developer handoff on one API-36 emulator. It is not production-signed, a Play candidate, physical-device qualification, real identity/payment/push evidence, or T31 completion. Use synthetic or explicitly authorized test data only.
