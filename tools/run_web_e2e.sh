#!/usr/bin/env bash
# Live web journey on a local PostgreSQL 16: API + analysis and export workers + Next.
# Usage: PYTHON=.venv/bin/python PRINCESS_CHROMIUM=/path/to/chrome tools/run_web_e2e.sh
# Needs the princess_admin role from infra/README.md. It runs the "test" environment
# and therefore recreates the princess_test database (the tests_app database).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
ADMIN="postgresql://princess_admin:local-only-admin@127.0.0.1:5432"
WORK="$(mktemp -d)"
cleanup() { kill "${API_PID:-}" "${WORKER_PID:-}" "${EXPORT_PID:-}" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

psql "$ADMIN/postgres" -qc "DROP DATABASE IF EXISTS princess_test WITH (FORCE)" -c "CREATE DATABASE princess_test"
PRINCESS_MIGRATION_DATABASE_URL="$ADMIN/princess_test" "$PY" -m princess_app.adapters.postgres.migrate upgrade
psql "$ADMIN/princess_test" -q <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_e2e_api') THEN
    CREATE ROLE princess_e2e_api LOGIN PASSWORD 'e2e-only-api'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_e2e_worker') THEN
    CREATE ROLE princess_e2e_worker LOGIN PASSWORD 'e2e-only-worker'; END IF;
END $$;
GRANT princess_app TO princess_e2e_api;
GRANT princess_worker TO princess_e2e_worker;
SQL
"$PY" - "$WORK/sample.png" <<'PY'
import sys, cv2, numpy as np
image = np.full((360, 900), 245, np.uint8)
for i, line in enumerate(("synthetic writing sample", "for the web journey", "not a real person")):
    cv2.putText(image, line, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, 25, 3, cv2.LINE_AA)
cv2.imwrite(sys.argv[1], image)
PY

export PRINCESS_ENV=test PRINCESS_LOCAL_STORAGE_DIR="$WORK/storage" PYTHONPATH="$ROOT/src:$ROOT/apps/api"
PRINCESS_COMPONENT=api PRINCESS_DATABASE_URL="postgresql://princess_e2e_api:e2e-only-api@127.0.0.1:5432/princess_test" \
  PRINCESS_SESSION_SECRET=local-session-secret-e2e PRINCESS_IDENTITY_AUDIENCE=princess-api \
  PRINCESS_STORAGE_SIGNING_KEY=local-storage-key-e2e PRINCESS_PUBLIC_API_BASE=http://127.0.0.1:3100/api \
  "$PY" -m uvicorn --factory princess_api.compose:app_from_environment --port 8000 --log-level warning &
API_PID=$!
PRINCESS_COMPONENT=analysis_worker \
  PRINCESS_DATABASE_URL="postgresql://princess_e2e_worker:e2e-only-worker@127.0.0.1:5432/princess_test" \
  PRINCESS_STORAGE_READ_KEY=local-storage-key-e2e "$PY" "$ROOT/apps/workers/analysis/run_worker.py" &
WORKER_PID=$!
(cd "$ROOT" && pnpm --filter @princess/render run build >/dev/null)
PRINCESS_COMPONENT=export_worker \
  PRINCESS_DATABASE_URL="postgresql://princess_e2e_worker:e2e-only-worker@127.0.0.1:5432/princess_test" \
  PRINCESS_STORAGE_READ_KEY=local-storage-key-e2e "$PY" "$ROOT/apps/workers/export/run_worker.py" &
EXPORT_PID=$!

cd "$ROOT/apps/web"
PRINCESS_E2E_API=http://127.0.0.1:8000 PRINCESS_E2E_SAMPLE="$WORK/sample.png" PRINCESS_ENVIRONMENT=test \
  pnpm exec playwright test e2e/live.spec.ts
