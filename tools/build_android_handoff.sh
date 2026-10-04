#!/usr/bin/env bash
# Build and statically qualify the standalone Android developer-handoff APK (Gradle release variant, embedded bundle).
# The handoff is the existing development variant with the local backend at device loopback http://127.0.0.1:8000
# (reached through `adb reverse tcp:8000 tcp:8000`). It is development/debug signed by the generated CNG project and
# is not Play signing, a store candidate or device qualification. Requires a frozen `pnpm install`, a JDK and an
# Android SDK (ANDROID_HOME) with build-tools and cmdline-tools. Only the generated apps/mobile/android/ is replaced.
# Optional: ANDROID_HANDOFF_OUT (evidence directory), ANDROID_HANDOFF_ARCHITECTURES (e.g. x86_64 for a faster
# local emulator-only build), ANDROID_HANDOFF_BUILD_TOOLS, ANDROID_HANDOFF_ALLOW_CUSTOM_API=1 (another
# loopback/private development origin; the verifier still refuses public origins).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
REVIEWED_API="http://127.0.0.1:8000"
MOBILE="$ROOT/apps/mobile"
ANDROID="$MOBILE/android"

export INKTROSPECT_APP_VARIANT="${INKTROSPECT_APP_VARIANT:-development}"
export INKTROSPECT_BACKEND_ENV="${INKTROSPECT_BACKEND_ENV:-local}"
export INKTROSPECT_API_BASE="${INKTROSPECT_API_BASE:-$REVIEWED_API}"
if [[ "$INKTROSPECT_APP_VARIANT" != "development" ]]; then
  echo "REFUSE: the developer handoff is the development variant only; staging/store are not handoff builds" >&2
  exit 2
fi
if [[ "$INKTROSPECT_BACKEND_ENV" != "local" ]]; then
  echo "REFUSE: the developer handoff targets the local backend (INKTROSPECT_BACKEND_ENV=local)" >&2
  exit 2
fi
if [[ "$INKTROSPECT_API_BASE" != "$REVIEWED_API" && "${ANDROID_HANDOFF_ALLOW_CUSTOM_API:-}" != "1" ]]; then
  echo "REFUSE: the reviewed handoff API is $REVIEWED_API (device loopback through adb reverse);" \
       "set ANDROID_HANDOFF_ALLOW_CUSTOM_API=1 only for another loopback/private development origin" >&2
  exit 2
fi
for name in INKTROSPECT_UPLOAD_ORIGINS INKTROSPECT_LINK_HOSTS; do
  if [[ -n "${!name:-}" ]]; then
    echo "REFUSE: $name is not part of the developer handoff build contract" >&2
    exit 2
  fi
done

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$SDK" || ! -d "$SDK" ]]; then
  echo "ANDROID_HOME (or ANDROID_SDK_ROOT) must name the Android SDK" >&2
  exit 2
fi
APKANALYZER="$SDK/cmdline-tools/latest/bin/apkanalyzer"
BUILD_TOOLS="${ANDROID_HANDOFF_BUILD_TOOLS:-$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort -V | tail -n 1)}"
APKSIGNER="$SDK/build-tools/$BUILD_TOOLS/apksigner"
for tool in "$APKANALYZER" "$APKSIGNER"; do
  if [[ ! -x "$tool" ]]; then echo "missing Android SDK tool: $tool" >&2; exit 2; fi
done
if [[ ! -x "$MOBILE/node_modules/.bin/expo" ]]; then
  echo "Install the frozen JavaScript workspace first: pnpm install --frozen-lockfile" >&2
  exit 2
fi

echo "== Clean CNG/prebuild ($INKTROSPECT_APP_VARIANT / $INKTROSPECT_BACKEND_ENV / $INKTROSPECT_API_BASE)"
(cd "$ROOT" && pnpm --filter @princess/mobile prebuild:android)
OUT="${ANDROID_HANDOFF_OUT:-$ANDROID/handoff}"
mkdir -p "$OUT"

echo "== Inspect the generated Gradle project, manifest and public config"
(cd "$MOBILE" && node_modules/.bin/expo config --type public --json) > "$OUT/expo-public-config.json"
"$PY" - "$ANDROID" "$OUT/expo-public-config.json" "$INKTROSPECT_API_BASE" <<'PY'
import json, re, sys
from pathlib import Path
android, config_path, api = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
gradle = (android / "app/build.gradle").read_text(encoding="utf-8")
def fail(message):
    raise SystemExit(f"FAIL: generated project: {message}")
if "applicationId 'se.inktrospect.development'" not in gradle:
    fail("applicationId is not se.inktrospect.development")
if re.search(r"^\s*debuggableVariants\s*=", gradle, re.MULTILINE):
    fail("react.debuggableVariants is configured; release must stay a bundled, non-debuggable variant")
signing = re.search(r"signingConfigs\s*\{(.*?)\n    \}", gradle, re.DOTALL)
release = re.search(r"buildTypes\s*\{.*?\brelease\s*\{(.*?)\n        \}", gradle, re.DOTALL)
if not signing or re.findall(r"^\s{8}(\w+)\s*\{", signing.group(1), re.MULTILINE) != ["debug"]:
    fail("expected exactly the generated debug signing config")
if "storeFile file('debug.keystore')" not in signing.group(1) or not (android / "app/debug.keystore").is_file():
    fail("the generated debug keystore is missing")
if not release or "signingConfig = signingConfigs.debug" not in release.group(1):
    fail("the release build type is not signed by the generated debug key")
manifest = (android / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
if 'android:usesCleartextTraffic="true"' not in manifest:
    fail("the main manifest does not allow development cleartext")
config = json.loads(config_path.read_text(encoding="utf-8"))
runtime = config["extra"]["runtime"]
expected = {"variant": "development", "backendEnvironment": "local", "apiBaseUrl": api, "devIdentity": True,
            "linkHosts": [], "uploadOrigins": []}
for key, value in expected.items():
    if runtime.get(key) != value:
        fail(f"public config runtime.{key} is {runtime.get(key)!r}, expected {value!r}")
if config["android"]["package"] != "se.inktrospect.development" or config["version"] != "0.1.0":
    fail("public config package/version drifted")
print("generated project: development package, debug-key release signing, no debuggable release, cleartext manifest")
PY

echo "== assembleRelease"
gradle_args=(:app:assembleRelease --no-daemon)
if [[ -n "${ANDROID_HANDOFF_ARCHITECTURES:-}" ]]; then
  gradle_args+=("-PreactNativeArchitectures=$ANDROID_HANDOFF_ARCHITECTURES")
fi
(cd "$ANDROID" && ./gradlew "${gradle_args[@]}")

mapfile -t apks < <(find "$ANDROID/app/build/outputs/apk/release" -maxdepth 1 -type f -name '*.apk' | sort)
if [[ "${#apks[@]}" -ne 1 || "$(basename "${apks[0]}")" != "app-release.apk" ]]; then
  printf 'expected exactly app-release.apk, found: %s\n' "${apks[*]:-none}" >&2
  exit 1
fi
APK="${apks[0]}"

echo "== Android SDK tool evidence"
analyze() { "$APKANALYZER" "$@" 2>/dev/null; }
analyze manifest print "$APK" > "$OUT/manifest.xml"
{
  echo "application-id=$(analyze manifest application-id "$APK")"
  echo "version-name=$(analyze manifest version-name "$APK")"
  echo "min-sdk=$(analyze manifest min-sdk "$APK")"
  echo "target-sdk=$(analyze manifest target-sdk "$APK")"
  echo "debuggable=$(analyze manifest debuggable "$APK")"
} > "$OUT/apkanalyzer.txt"
cat "$OUT/apkanalyzer.txt"
expected_analysis=$'application-id=se.inktrospect.development\nversion-name=0.1.0\nmin-sdk=24\ntarget-sdk=36\ndebuggable=false'
if [[ "$(cat "$OUT/apkanalyzer.txt")" != "$expected_analysis" ]]; then
  echo "FAIL: apkanalyzer manifest values differ from the handoff contract" >&2
  exit 1
fi
"$APKSIGNER" verify --verbose --print-certs "$APK" > "$OUT/apksigner.txt"
grep -E '^(Verifies|Verified using|Number of signers|Signer #1 certificate (DN|SHA-256))' "$OUT/apksigner.txt"

echo "== Repository verifier"
"$PY" "$ROOT/tools/verify_android_handoff.py" verify "$APK" \
  --name Inktrospect --package se.inktrospect.development --version 0.1.0 --scheme inktrospect-dev \
  --variant development --backend local --api-base "$INKTROSPECT_API_BASE" \
  --min-sdk 24 --target-sdk 36 --compile-sdk 36 \
  --manifest-xml "$OUT/manifest.xml" --signature-report "$OUT/apksigner.txt" \
  --summary-out "$OUT/verification.json" > /dev/null
(cd "$(dirname "$APK")" && sha256sum "$(basename "$APK")") | tee "$OUT/app-release.apk.sha256"
echo "QUALIFIED_APK=$APK"
