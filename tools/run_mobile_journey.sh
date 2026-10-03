#!/usr/bin/env bash
# Live native-client journey against a disposable local/test API and workers.
# Drives the mobile app's real composition (session, journal, capture workflow,
# runner, controllers) in Node; device I/O uses Node stand-ins. This is
# development-API evidence, not device, simulator, UI or store evidence.
# Required: PRINCESS_E2E_ADMIN_URL ending in /postgres and PRINCESS_E2E_ALLOW_RESET=1.
# Optional: PRINCESS_E2E_EXPORTS=1 with PRINCESS_CHROMIUM to include the PDF export worker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
: "${PRINCESS_E2E_ADMIN_URL:?set PRINCESS_E2E_ADMIN_URL to the disposable PostgreSQL admin /postgres URL}"
if [[ "${PRINCESS_E2E_ALLOW_RESET:-}" != "1" ]]; then
  echo "REFUSE: PRINCESS_E2E_ALLOW_RESET=1 is required before resetting princess_test" >&2
  exit 2
fi
"$PY" - "$PRINCESS_E2E_ADMIN_URL" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if url.scheme not in {"postgresql", "postgresql+psycopg"}:
    raise SystemExit("REFUSE: E2E admin URL must be PostgreSQL")
if url.hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("REFUSE: E2E database must be local/disposable")
if (url.port or 5432) != 5432:
    raise SystemExit("REFUSE: E2E runner currently supports only local PostgreSQL port 5432")
if url.path != "/postgres" or url.query or url.fragment:
    raise SystemExit("REFUSE: E2E admin URL must target exactly /postgres")
PY
ADMIN="$PRINCESS_E2E_ADMIN_URL"
DB_ADMIN="${ADMIN%/postgres}/princess_test"
WORK="$(mktemp -d)"
PORT="${PRINCESS_E2E_PORT:-8010}"
cleanup() {
  kill "${API_PID:-}" "${WORKER_PID:-}" "${EXPORT_PID:-}" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

psql "$ADMIN" -v ON_ERROR_STOP=1 -qc "DROP DATABASE IF EXISTS princess_test WITH (FORCE)" -c "CREATE DATABASE princess_test"
PRINCESS_MIGRATION_DATABASE_URL="$DB_ADMIN" "$PY" -m princess_app.adapters.postgres.migrate upgrade
psql "$DB_ADMIN" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_e2e_api') THEN
    CREATE ROLE princess_e2e_api LOGIN PASSWORD 'e2e-only-api'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_e2e_worker') THEN
    CREATE ROLE princess_e2e_worker LOGIN PASSWORD 'e2e-only-worker'; END IF;
END $$;
GRANT princess_app TO princess_e2e_api;
GRANT princess_worker TO princess_e2e_worker;
SQL

# Two programmatically drawn synthetic pages: no person's handwriting is involved.
"$PY" - "$WORK/sample.png" "$WORK/sample2.png" <<'PY'
import sys, cv2, numpy as np
for path, angle, lines in ((sys.argv[1], 2.0, ("synthetic writing sample", "for the native journey", "not a real person")),
                           (sys.argv[2], -3.0, ("a second synthetic page", "drawn by a program", "for comparison only"))):
    image = np.full((360, 900), 245, np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(image, line, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, 25, 3, cv2.LINE_AA)
    matrix = cv2.getRotationMatrix2D((450, 180), angle, 1.0)
    image = cv2.warpAffine(image, matrix, (900, 360), borderValue=245)
    if not cv2.imwrite(path, image):
        raise SystemExit("failed to write synthetic sample")
PY

export PRINCESS_ENV=test PRINCESS_LOCAL_STORAGE_DIR="$WORK/storage" PYTHONPATH="$ROOT/src:$ROOT/apps/api"
# The phone talks to the API directly, so upload URLs are issued on the API origin.
PRINCESS_COMPONENT=api PRINCESS_DATABASE_URL="postgresql://princess_e2e_api:e2e-only-api@127.0.0.1:5432/princess_test" \
  PRINCESS_SESSION_SECRET=local-session-secret-e2e PRINCESS_IDENTITY_AUDIENCE=princess-api \
  PRINCESS_STORAGE_SIGNING_KEY=local-storage-key-e2e PRINCESS_PUBLIC_API_BASE="http://127.0.0.1:$PORT" \
  "$PY" -m uvicorn --factory princess_api.compose:app_from_environment --port "$PORT" --log-level warning &
API_PID=$!

if [[ "${PRINCESS_E2E_EXPORTS:-}" == "1" ]]; then
  (cd "$ROOT" && pnpm --filter @princess/render run build >/dev/null)
  PRINCESS_COMPONENT=export_worker \
    PRINCESS_DATABASE_URL="postgresql://princess_e2e_worker:e2e-only-worker@127.0.0.1:5432/princess_test" \
    PRINCESS_STORAGE_READ_KEY=local-storage-key-e2e "$PY" "$ROOT/apps/workers/export/run_worker.py" &
  EXPORT_PID=$!
fi

WORKER_GATE="$WORK/start-analysis-worker"
(
  while [[ ! -f "$WORKER_GATE" ]]; do
    kill -0 "$API_PID" 2>/dev/null || exit 1
    sleep 0.1
  done
  exec env PRINCESS_ENV=test PRINCESS_LOCAL_STORAGE_DIR="$WORK/storage" PYTHONPATH="$ROOT/src:$ROOT/apps/api" \
    PRINCESS_COMPONENT=analysis_worker \
    PRINCESS_DATABASE_URL="postgresql://princess_e2e_worker:e2e-only-worker@127.0.0.1:5432/princess_test" \
    PRINCESS_STORAGE_READ_KEY=local-storage-key-e2e \
    "$PY" "$ROOT/apps/workers/analysis/run_worker.py"
) &
WORKER_PID=$!

ready=0
for _ in $(seq 1 100); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API exited before readiness" >&2
    exit 1
  fi
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/health/live"; then ready=1; break; fi
  sleep 0.2
done
if [[ "$ready" != "1" ]]; then echo "API did not become ready" >&2; exit 1; fi

mkdir -p "$WORK/client"
cd "$ROOT/apps/mobile"
PRINCESS_E2E_API="http://127.0.0.1:$PORT" \
PRINCESS_E2E_SAMPLE="$WORK/sample.png" \
PRINCESS_E2E_SAMPLE_2="$WORK/sample2.png" \
PRINCESS_E2E_WORKER_GATE="$WORKER_GATE" \
PRINCESS_E2E_WORK_DIR="$WORK/client" \
  node scripts/live-journey.ts
