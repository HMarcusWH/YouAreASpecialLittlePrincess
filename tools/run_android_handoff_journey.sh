#!/usr/bin/env bash
# Packaged Android journey: the exact standalone handoff APK on a booted emulator/device, driven by Maestro 2.11.0.
# Installs the given release-variant APK, picks a synthetic page through the real system Photo Picker, analyses it
# against a disposable local API and deterministic analysis worker, force-stops and relaunches the app, and proves
# by exact database counts that the same capture/run/report completed into the saved Dossier. Synthetic data only.
# No Metro, Premium worker, payment, push or model provider is started. This is emulator evidence for one device,
# not physical-device, store or T31 qualification.
# Required: PRINCESS_E2E_ADMIN_URL ending in /postgres, PRINCESS_E2E_ALLOW_RESET=1, adb, maestro 2.11.0, psql, curl,
# the locked backend environment (PYTHON) and one booted device. Host ports 8000 and 8081 must be free.
# Optional: PRINCESS_HANDOFF_EVIDENCE_DIR keeps bounded synthetic-only logs, Maestro debug output and assertions.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
: "${PRINCESS_E2E_ADMIN_URL:?set PRINCESS_E2E_ADMIN_URL to the disposable PostgreSQL admin /postgres URL}"
if [[ "${PRINCESS_E2E_ALLOW_RESET:-}" != "1" ]]; then
  echo "REFUSE: PRINCESS_E2E_ALLOW_RESET=1 is required before resetting princess_test" >&2
  exit 2
fi
APK="${1:-}"
if [[ -z "$APK" || ! -f "$APK" ]]; then
  echo "usage: $0 <path to the qualified app-release.apk>" >&2
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

APP_ID="se.inktrospect.development"
API="http://127.0.0.1:8000"
MAESTRO_VERSION="2.11.0"
ADB="${ADB:-adb}"
MAESTRO="${MAESTRO:-maestro}"
FLOWS="$ROOT/apps/mobile/e2e/maestro"
SAMPLE="$FLOWS/resources/synthetic-writing.png"
ADMIN="$PRINCESS_E2E_ADMIN_URL"
DB_ADMIN="${ADMIN%/postgres}/princess_test"
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
for tool in "$ADB" "$MAESTRO" psql curl; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 2; }
done
reported="$(timeout 120 "$MAESTRO" --version 2>/dev/null | tail -n 1 | tr -d '[:space:]')"
if [[ "$reported" != "$MAESTRO_VERSION" ]]; then
  echo "REFUSE: the flows are qualified with Maestro $MAESTRO_VERSION, found '$reported'" >&2
  exit 2
fi
port_open() { "$PY" -c 'import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$1"; }
if port_open 8000; then echo "REFUSE: host port 8000 is already serving; stop the other API first" >&2; exit 2; fi
# Nothing may answer where a dev client would look for Metro: the APK has to run without it.
if port_open 8081; then echo "REFUSE: host port 8081 is serving (Metro?); the handoff must run without it" >&2; exit 2; fi

WORK="$(mktemp -d)"
LOGS="${PRINCESS_HANDOFF_EVIDENCE_DIR:-$WORK/evidence}"
mkdir -p "$LOGS"
adb_() { timeout "${ADB_TIMEOUT:-60}" "$ADB" "$@"; }
cleanup() {
  status=$?
  if [[ "$status" -ne 0 ]]; then
    # Bounded synthetic-only diagnostics, also printed to the job log: on-screen texts, table counts, redacted
    # request lines and app error lines. Credentials, upload signatures and bearer values are removed.
    redact() { sed -E 's#(postgres(ql)?(\+psycopg)?://)[^@/ ]*@#\1***@#g; s#(sig|token|signature)=[^& "]*#\1=***#g;
                       s#[Bb]earer [A-Za-z0-9._~+/=-]+#Bearer ***#g; /[Aa]uthorization/d'; }
    echo "== Failure diagnostics (synthetic data only)"
    timeout 90 "$MAESTRO" ${ANDROID_SERIAL:+--device "$ANDROID_SERIAL"} hierarchy \
      > "$LOGS/hierarchy-on-failure.json" 2>/dev/null || true
    "$PY" - "$LOGS/hierarchy-on-failure.json" <<'PY' || true
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
seen = []
def walk(node):
    attributes = node.get("attributes", {}) if isinstance(node, dict) else {}
    for key in ("text", "accessibilityText", "resource-id"):
        value = attributes.get(key)
        if value and f"{key}={value}" not in seen:
            seen.append(f"{key}={value}")
    for child in (node.get("children") or []) if isinstance(node, dict) else []:
        walk(child)
try:
    walk(json.loads(raw[raw.index("{"):]))
    print("on-screen:", *seen[:100], sep="\n  ")
except (ValueError, KeyError) as error:
    print(f"hierarchy unavailable: {error}")
PY
    psql "$DB_ADMIN" -XAtq -F ' ' -c "SELECT 'upload', count(*) FROM app.upload UNION ALL SELECT 'capture', count(*)
      FROM app.capture UNION ALL SELECT 'permission_event', count(*) FROM app.permission_event UNION ALL
      SELECT 'analysis_run:' || status, count(*) FROM app.analysis_run GROUP BY status UNION ALL
      SELECT 'report', count(*) FROM app.report" 2>&1 | tee "$LOGS/db-state-on-failure.txt" || true
    adb_ logcat -d -b crash 2>/dev/null | redact > "$LOGS/logcat-crash.txt" || true
    adb_ logcat -d -s ReactNativeJS:V 2>/dev/null | redact | tail -n 40 | tee "$LOGS/logcat-reactnativejs.txt" || true
    for name in api worker; do
      if [[ -f "$WORK/$name.log" ]]; then
        redact < "$WORK/$name.log" | tail -n 200 > "$LOGS/$name-tail.log" || true
        echo "-- $name log tail"
        tail -n 60 "$LOGS/$name-tail.log" || true
      fi
    done
  fi
  kill "${API_PID:-}" "${WORKER_PID:-}" 2>/dev/null || true
  timeout 20 "$ADB" reverse --remove tcp:8000 >/dev/null 2>&1 || true
  rm -f "$SAMPLE"
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

echo "== Static check: the APK embeds its bundle and targets $API"
"$PY" "$ROOT/tools/verify_android_handoff.py" verify "$APK" \
  --name Inktrospect --package "$APP_ID" --version 0.1.0 --scheme inktrospect-dev \
  --variant development --backend local --api-base "$API" \
  --min-sdk 24 --target-sdk 36 --compile-sdk 36 --static-only > /dev/null
APK_SHA="$(sha256sum "$APK" | cut -d' ' -f1)"

echo "== Device"
adb_ wait-for-device
if [[ "$(adb_ shell getprop sys.boot_completed | tr -d '\r')" != "1" ]]; then
  echo "the device has not finished booting" >&2
  exit 1
fi
locale="$(adb_ shell getprop persist.sys.locale | tr -d '\r')"
locale="${locale:-$(adb_ shell getprop ro.product.locale | tr -d '\r')}"
if [[ "$locale" != en-* ]]; then
  echo "REFUSE: the flows assert English copy; the device locale is '$locale'" >&2
  exit 2
fi

echo "== Disposable database princess_test"
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

# One programmatically drawn synthetic page (same method as tools/run_mobile_journey.sh); no person's handwriting.
mkdir -p "$(dirname "$SAMPLE")"
"$PY" - "$SAMPLE" <<'PY'
import sys, cv2, numpy as np
image = np.full((360, 900), 245, np.uint8)
for i, line in enumerate(("synthetic writing sample", "for the native journey", "not a real person")):
    cv2.putText(image, line, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, 25, 3, cv2.LINE_AA)
matrix = cv2.getRotationMatrix2D((450, 180), 2.0, 1.0)
image = cv2.warpAffine(image, matrix, (900, 360), borderValue=245)
if not cv2.imwrite(sys.argv[1], image):
    raise SystemExit("failed to write synthetic sample")
PY

# The installed app was built for the `local` backend. The server's environment manifest binds `local` to the
# developer's princess_local database, which this runner must never reset; `test` has the identical provider
# composition (fakes, draft notices for synthetic data, development identity) and is bound to princess_test.
export PRINCESS_ENV=test PRINCESS_LOCAL_STORAGE_DIR="$WORK/storage" PRINCESS_TOMBSTONE_DIR="$WORK/tombstones"
export PYTHONPATH="$ROOT/src:$ROOT/apps/api"
echo "== API on 127.0.0.1:8000 (the APK's device loopback origin through adb reverse)"
PRINCESS_COMPONENT=api PRINCESS_DATABASE_URL="postgresql://princess_e2e_api:e2e-only-api@127.0.0.1:5432/princess_test" \
  PRINCESS_SESSION_SECRET=local-session-secret-e2e PRINCESS_IDENTITY_AUDIENCE=princess-api \
  PRINCESS_STORAGE_SIGNING_KEY=local-storage-key-e2e PRINCESS_PUBLIC_API_BASE="$API" \
  "$PY" -m uvicorn --factory princess_api.compose:app_from_environment --host 127.0.0.1 --port 8000 \
  --log-level info > "$WORK/api.log" 2>&1 &
API_PID=$!

# The analysis worker stays behind a gate until the relaunched app has recovered the queued run.
WORKER_GATE="$WORK/start-analysis-worker"
(
  while [[ ! -f "$WORKER_GATE" ]]; do
    kill -0 "$API_PID" 2>/dev/null || exit 1
    sleep 0.2
  done
  exec env PRINCESS_COMPONENT=analysis_worker \
    PRINCESS_DATABASE_URL="postgresql://princess_e2e_worker:e2e-only-worker@127.0.0.1:5432/princess_test" \
    PRINCESS_STORAGE_READ_KEY=local-storage-key-e2e \
    "$PY" "$ROOT/apps/workers/analysis/run_worker.py"
) > "$WORK/worker.log" 2>&1 &
WORKER_PID=$!

ready=0
for _ in $(seq 1 150); do
  kill -0 "$API_PID" 2>/dev/null || { echo "API exited before readiness" >&2; exit 1; }
  if curl -s -o /dev/null --max-time 2 "$API/health/live"; then ready=1; break; fi
  sleep 0.2
done
if [[ "$ready" != "1" ]]; then echo "API did not become ready" >&2; exit 1; fi

echo "== adb reverse and exact APK installation"
adb_ reverse tcp:8000 tcp:8000
adb_ reverse --list | grep -q "tcp:8000 tcp:8000" || { echo "adb reverse tcp:8000 is not active" >&2; exit 1; }
adb_ uninstall "$APP_ID" >/dev/null 2>&1 || true
ADB_TIMEOUT=300 adb_ install -r "$APK"
installed="$(adb_ shell pm path "$APP_ID" | tr -d '\r' | sed -n 's/^package://p')"
if [[ "$(printf '%s\n' "$installed" | grep -c .)" -ne 1 ]]; then
  echo "expected one installed base APK, got: $installed" >&2
  exit 1
fi
ADB_TIMEOUT=300 adb_ pull "$installed" "$WORK/installed.apk" >/dev/null
INSTALLED_SHA="$(sha256sum "$WORK/installed.apk" | cut -d' ' -f1)"
if [[ "$INSTALLED_SHA" != "$APK_SHA" ]]; then
  echo "installed APK $INSTALLED_SHA is not the qualified APK $APK_SHA" >&2
  exit 1
fi
flags="$(adb_ shell dumpsys package "$APP_ID" | tr -d '\r' | grep -m1 -E '^ +flags=\[' || true)"
if [[ -z "$flags" || "$flags" == *DEBUGGABLE* ]]; then
  echo "the installed package is debuggable or unreadable: $flags" >&2
  exit 1
fi
echo "installed sha256=$INSTALLED_SHA; $flags"

DEVICE_ARGS=()
if [[ -n "${ANDROID_SERIAL:-}" ]]; then DEVICE_ARGS=(--device "$ANDROID_SERIAL"); fi
maestro_flow() {
  local flow="$1"
  adb_ shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1 || true
  echo "== Maestro: $flow"
  timeout --kill-after=30 "${MAESTRO_FLOW_TIMEOUT:-900}" "$MAESTRO" test --no-ansi "${DEVICE_ARGS[@]}" \
    --debug-output "$LOGS/maestro-$flow" --flatten-debug-output "$FLOWS/$flow.yaml"
}
query() { psql "$DB_ADMIN" -XAtq -v ON_ERROR_STOP=1 -c "$1"; }
expect() {
  local label="$1" want="$2" got
  got="$(query "$3")"
  echo "  $label = $got (expected $want)" | tee -a "$LOGS/db-assertions.log"
  if [[ "$got" != "$want" ]]; then echo "FAIL: $label" >&2; exit 1; fi
}
counts() {
  echo "-- $1" >> "$LOGS/db-assertions.log"
  expect "capture count" "$2" "SELECT count(*) FROM app.capture"
  expect "analysis_run count" "$3" "SELECT count(*) FROM app.analysis_run"
  expect "report count" "$4" "SELECT count(*) FROM app.report"
}

maestro_flow free-to-queued
counts "after the first flow, worker gated" 1 1 0
RUN_ID="$(query "SELECT run_id FROM app.analysis_run")"
CAPTURE_ID="$(query "SELECT capture_id FROM app.capture")"
echo "queued run_id=$RUN_ID"
expect "queued run bound to the one capture" 1 \
  "SELECT count(*) FROM app.analysis_run WHERE status = 'QUEUED' AND capture_id = '$CAPTURE_ID'"
expect "service-processing grants" 1 \
  "SELECT count(*) FROM app.permission_event WHERE purpose_id = 'service_processing' AND decision = 'GRANT'"
expect "image-retention grants (optional, not chosen)" 0 \
  "SELECT count(*) FROM app.permission_event WHERE purpose_id = 'image_retention'"

echo "== Process death: force-stop without clearing data"
adb_ shell am force-stop "$APP_ID"
if [[ -n "$(adb_ shell pidof "$APP_ID" | tr -d '\r' || true)" ]]; then
  echo "the app process survived force-stop" >&2
  exit 1
fi
maestro_flow resume-to-queued
counts "after relaunch and recovery, worker still gated" 1 1 0
expect "the recovered run is the same run" "$RUN_ID" "SELECT run_id FROM app.analysis_run"

echo "== Release the analysis worker"
touch "$WORKER_GATE"
maestro_flow queued-to-report
counts "after completion" 1 1 1
expect "report_revision count" 1 "SELECT count(*) FROM app.report_revision"
expect "the report belongs to the same run" "$RUN_ID" "SELECT run_id FROM app.report"
expect "the same run succeeded on the one capture" 1 \
  "SELECT count(*) FROM app.analysis_run WHERE run_id = '$RUN_ID' AND status = 'SUCCEEDED' AND capture_id = '$CAPTURE_ID'"
if port_open 8081; then echo "FAIL: something started serving on port 8081 during the journey" >&2; exit 1; fi

"$PY" - "$LOGS/journey.json" "$APK_SHA" "$INSTALLED_SHA" <<'PY'
import json, sys
json.dump({"apk_sha256": sys.argv[2], "installed_apk_sha256": sys.argv[3], "installed_debuggable": False,
           "metro_port_8081_served": False, "flows": ["free-to-queued", "resume-to-queued", "queued-to-report"],
           "counts_before_worker": {"capture": 1, "analysis_run": 1, "report": 0},
           "counts_final": {"capture": 1, "analysis_run": 1, "report": 1, "report_revision": 1},
           "same_run_recovered": True, "data": "synthetic_only"}, open(sys.argv[1], "w"), indent=2)
PY
echo "PASS: packaged Android handoff journey (exact APK, no Metro, same-run recovery, saved Dossier)"
