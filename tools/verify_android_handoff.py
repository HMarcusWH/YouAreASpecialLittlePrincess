#!/usr/bin/env python3
"""Verify a standalone Android developer-handoff APK and record its qualified build evidence.

Standard library only. ``verify`` fails closed unless the APK is a structurally valid ZIP with a
non-trivial embedded application bundle (``assets/index.android.bundle``) and an embedded Expo
configuration that names the expected development identity and local API. Without
``--static-only`` it also requires the decoded merged manifest (``apkanalyzer manifest print``)
and the ``apksigner verify --verbose --print-certs`` report, and checks the non-debuggable,
development-cleartext, launcher, permission and debug-signing boundaries. ``record`` writes
BUILDINFO.json and HANDOFF.md only from a verified summary and supplied toolchain facts.

This is a developer-handoff boundary check, not production signing, store or security review.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
BUNDLE = "assets/index.android.bundle"
APP_CONFIG = "assets/app.config"
# Hermes bytecode files start with this 64-bit magic number, stored little-endian.
HERMES_MAGIC = (0x1F1903C103BC1FC6).to_bytes(8, "little")
# Identifiers of the non-development variants in apps/mobile/app.config.ts; a handoff never carries them.
FORBIDDEN_PACKAGES = frozenset({"se.inktrospect", "se.inktrospect.staging"})
FORBIDDEN_VARIANTS = frozenset({"staging", "store"})
HANDOFF_BACKENDS = frozenset({"local", "test"})
DEFAULT_FORBIDDEN_PERMISSIONS = (
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.READ_MEDIA_AUDIO",
    "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
)
# The picker library's legacy storage pair is deliberately kept for Android 7-9 camera capture,
# but only when capped at API 32 (see apps/mobile/app.config.ts).
CAPPED_LEGACY_PERMISSIONS = frozenset({
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
})
LEGACY_MAX_SDK = 32
SCHEMA_VERSION = "android-handoff-buildinfo/1"


class HandoffError(Exception):
    """A fail-closed verification finding."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HandoffError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def check_handoff_api(raw: Any) -> str:
    """A handoff API origin is a non-blank HTTP(S) loopback/private origin with no credentials or query."""
    _require(isinstance(raw, str) and raw.strip() != "", "runtime.apiBaseUrl is blank")
    parts = urlsplit(raw)
    _require(parts.scheme in {"http", "https"}, f"runtime.apiBaseUrl scheme is not HTTP(S): {raw!r}")
    _require(parts.hostname is not None and parts.username is None and parts.password is None
             and not parts.query and not parts.fragment, f"runtime.apiBaseUrl is not a plain origin: {raw!r}")
    assert parts.hostname is not None
    _require(_private_host(parts.hostname),
             f"runtime.apiBaseUrl is not a loopback/private development origin: {raw!r}")
    return raw


def read_apk(path: Path, *, min_apk_bytes: int, min_bundle_bytes: int) -> dict[str, Any]:
    _require(path.is_file(), f"APK not found: {path}")
    size = path.stat().st_size
    _require(size >= min_apk_bytes, f"APK is implausibly small ({size} bytes < {min_apk_bytes})")
    _require(zipfile.is_zipfile(path), "APK is not a valid ZIP archive")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            bad = archive.testzip()
            _require(bad is None, f"APK entry fails its CRC check: {bad}")
            _require("AndroidManifest.xml" in names, "APK has no AndroidManifest.xml")
            _require(any(re.fullmatch(r"classes\d*\.dex", name) for name in names), "APK has no classes.dex")
            # The regression this guards: a dev-client/debug APK expects Metro and embeds no application bundle.
            _require(BUNDLE in names, f"APK has no embedded application bundle ({BUNDLE}); it would require Metro")
            bundle = archive.read(BUNDLE)
            _require(APP_CONFIG in names, f"APK has no embedded application configuration ({APP_CONFIG})")
            raw_config = archive.read(APP_CONFIG)
    except zipfile.BadZipFile as error:
        raise HandoffError(f"APK is not a readable ZIP archive: {error}") from None
    _require(len(bundle) >= min_bundle_bytes,
             f"embedded bundle is implausibly small ({len(bundle)} bytes < {min_bundle_bytes})")
    try:
        config = json.loads(raw_config.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise HandoffError(f"embedded application configuration does not parse: {error}") from None
    _require(isinstance(config, dict), "embedded application configuration is not an object")
    return {
        "apk_bytes": size,
        "apk_sha256": sha256_file(path),
        "bundle_bytes": len(bundle),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "bundle_format": "hermes" if bundle.startswith(HERMES_MAGIC) else "javascript",
        "config": config,
    }


def check_config(config: dict[str, Any], expected: argparse.Namespace) -> dict[str, Any]:
    android = config.get("android") if isinstance(config.get("android"), dict) else {}
    extra = config.get("extra") if isinstance(config.get("extra"), dict) else {}
    runtime = extra.get("runtime") if isinstance(extra.get("runtime"), dict) else None
    _require(runtime is not None, "embedded configuration has no extra.runtime object")
    assert runtime is not None
    package = android.get("package")
    variant = runtime.get("variant")
    backend = runtime.get("backendEnvironment")
    # Policy first, so a wrong expectation can never bless a staging/store binary.
    _require(package not in FORBIDDEN_PACKAGES, f"embedded package is a non-development identity: {package!r}")
    _require(variant not in FORBIDDEN_VARIANTS, f"embedded runtime.variant is not a development build: {variant!r}")
    _require(variant == "development", f"embedded runtime.variant must be development: {variant!r}")
    _require(backend in HANDOFF_BACKENDS, f"embedded runtime.backendEnvironment is not local/test: {backend!r}")
    api = check_handoff_api(runtime.get("apiBaseUrl"))
    _require(runtime.get("devIdentity") is True, "embedded runtime.devIdentity is not true")
    _require(runtime.get("linkHosts") == [], f"embedded runtime.linkHosts must be empty: {runtime.get('linkHosts')!r}")
    for origin in runtime.get("uploadOrigins") or []:
        check_handoff_api(origin)
    actual = {
        "name": config.get("name"), "package": package, "version": config.get("version"),
        "scheme": config.get("scheme"), "variant": variant, "backend": backend, "api_base": api,
    }
    for key, value in actual.items():
        want = getattr(expected, key)
        _require(value == want, f"embedded {key} is {value!r}, expected {want!r}")
    _require(runtime.get("linkSchemes") == [expected.scheme],
             f"embedded runtime.linkSchemes is {runtime.get('linkSchemes')!r}, expected {[expected.scheme]!r}")
    return actual


def _manifest_root(text: str) -> ET.Element:
    start = text.find("<manifest")
    _require(start >= 0, "decoded manifest has no <manifest> element")
    try:
        root = ET.fromstring(text[start:])
    except ET.ParseError as error:
        raise HandoffError(f"decoded manifest does not parse: {error}") from None
    _require(root.tag == "manifest", "decoded manifest root is not <manifest>")
    return root


def _int_attr(element: ET.Element | None, name: str) -> int | None:
    value = None if element is None else element.get(ANDROID_NS + name, element.get(name))
    return int(value) if value is not None and re.fullmatch(r"\d+", value) else None


def check_manifest(text: str, expected: argparse.Namespace) -> dict[str, Any]:
    root = _manifest_root(text)
    _require(root.get("package") == expected.package,
             f"manifest package is {root.get('package')!r}, expected {expected.package!r}")
    version = root.get(ANDROID_NS + "versionName")
    _require(version == expected.version, f"manifest versionName is {version!r}, expected {expected.version!r}")
    sdk = root.find("uses-sdk")
    min_sdk, target_sdk = _int_attr(sdk, "minSdkVersion"), _int_attr(sdk, "targetSdkVersion")
    compile_sdk = _int_attr(root, "compileSdkVersion") or _int_attr(root, "platformBuildVersionCode")
    _require(min_sdk == expected.min_sdk, f"manifest minSdkVersion is {min_sdk}, expected {expected.min_sdk}")
    _require(target_sdk == expected.target_sdk,
             f"manifest targetSdkVersion is {target_sdk}, expected {expected.target_sdk}")
    _require(compile_sdk == expected.compile_sdk,
             f"manifest compile SDK is {compile_sdk}, expected {expected.compile_sdk}")
    application = root.find("application")
    _require(application is not None, "manifest has no <application>")
    assert application is not None
    debuggable = application.get(ANDROID_NS + "debuggable", "false")
    _require(debuggable == "false", f"application is debuggable ({debuggable}); a handoff must not need Metro")
    cleartext = application.get(ANDROID_NS + "usesCleartextTraffic")
    _require(cleartext == "true",
             f"application usesCleartextTraffic is {cleartext!r}; the development handoff must reach the local HTTP API")
    launcher = False
    for activity in [*application.findall("activity"), *application.findall("activity-alias")]:
        for intent in activity.findall("intent-filter"):
            actions = {a.get(ANDROID_NS + "name") for a in intent.findall("action")}
            categories = {c.get(ANDROID_NS + "name") for c in intent.findall("category")}
            if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in categories:
                _require(activity.get(ANDROID_NS + "exported") == "true", "launcher activity is not exported")
                launcher = True
    _require(launcher, "manifest has no exported MAIN/LAUNCHER activity")
    permissions: dict[str, int | None] = {}
    for element in root.findall("uses-permission"):
        name = element.get(ANDROID_NS + "name")
        if name:
            permissions[name] = _int_attr(element, "maxSdkVersion")
    present = sorted(set(permissions) & set(expected.forbid_permission))
    _require(not present, f"manifest requests forbidden permissions: {', '.join(present)}")
    for name in sorted(CAPPED_LEGACY_PERMISSIONS & set(permissions)):
        cap = permissions[name]
        _require(cap is not None and cap <= LEGACY_MAX_SDK, f"{name} is not capped at maxSdkVersion {LEGACY_MAX_SDK}")
    return {"min_sdk": min_sdk, "target_sdk": target_sdk, "compile_sdk": compile_sdk, "debuggable": False,
            "uses_cleartext_traffic": True, "permissions": sorted(permissions)}


def check_signature(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    _require("Verifies" in lines, "apksigner did not report that the APK verifies")
    schemes = sorted(match.group(1) for line in lines
                     if (match := re.fullmatch(r"Verified using (v[\d.]+) scheme \(.*\): true", line)))
    _require(any(scheme in {"v2", "v3", "v3.1"} for scheme in schemes),
             "APK is not verified by an APK Signature Scheme v2/v3 block")
    signers = [line for line in lines if line.startswith("Number of signers:")]
    _require(signers == ["Number of signers: 1"], f"expected exactly one signer: {signers!r}")
    dn = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("Signer #1 certificate DN:")), None)
    digest = next((line.split(":", 1)[1].strip().lower() for line in lines
                   if line.startswith("Signer #1 certificate SHA-256 digest:")), None)
    _require(dn is not None and digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
             "apksigner report has no signer DN/SHA-256 certificate digest")
    assert dn is not None
    components = {part.split("=", 1)[0].strip(): part.split("=", 1)[1].strip()
                  for part in dn.split(",") if "=" in part}
    # Only the generated Android debug key is acceptable here; any other key would be mislabelled.
    _require(components.get("CN") == "Android Debug",
             f"signer is not the generated Android debug identity (DN {dn!r}); refusing to label it a handoff")
    return {"signing_class": "android_debug_key", "signing_certificate_dn": dn,
            "signing_certificate_sha256": digest, "signature_schemes": schemes}


def verify(args: argparse.Namespace) -> dict[str, Any]:
    apk = read_apk(Path(args.apk), min_apk_bytes=args.min_apk_bytes, min_bundle_bytes=args.min_bundle_bytes)
    _require(apk["bundle_format"] == args.bundle_format or args.bundle_format == "any",
             f"embedded bundle format is {apk['bundle_format']}, expected {args.bundle_format}")
    summary: dict[str, Any] = {
        "apk_file": Path(args.apk).name, "apk_bytes": apk["apk_bytes"], "apk_sha256": apk["apk_sha256"],
        "js_bundle_embedded": True, "js_bundle_bytes": apk["bundle_bytes"],
        "js_bundle_sha256": apk["bundle_sha256"], "js_bundle_format": apk["bundle_format"],
        **check_config(apk["config"], args),
    }
    if args.static_only:
        _require(not (args.manifest_xml or args.signature_report),
                 "--static-only cannot be combined with manifest/signature evidence")
        summary["scope"] = "static_only"
        return summary
    _require(bool(args.manifest_xml), "--manifest-xml is required unless --static-only is explicit")
    _require(bool(args.signature_report), "--signature-report is required unless --static-only is explicit")
    summary.update(check_manifest(Path(args.manifest_xml).read_text(encoding="utf-8"), args))
    summary.update(check_signature(Path(args.signature_report).read_text(encoding="utf-8")))
    summary["scope"] = "complete"
    return summary


_FORBIDDEN_RECORD_TEXT = re.compile(r"(/home/|/Users/|/runner/|/tmp/|postgres(ql)?://|bearer|authorization|"
                                    r"password|secret|token=|sig=|signature=|X-Amz-)", re.IGNORECASE)


def buildinfo(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    _require(summary.get("scope") == "complete", "BUILDINFO needs a complete (not static-only) verification summary")
    apk = Path(args.apk)
    _require(sha256_file(apk) == summary["apk_sha256"], "APK changed after verification")
    _require(re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is not None, "source commit is not a full SHA")
    _require(args.journey_passed, "BUILDINFO is only written after the packaged emulator journey passed")
    _require(re.fullmatch(r"[0-9a-f]{64}", args.maestro_archive_sha256) is not None, "Maestro archive digest invalid")
    info = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "developer_handoff",
        "release_candidate": False,
        "source_commit": args.source_commit,
        "workflow_run_id": args.workflow_run_id,
        "workflow_run_attempt": args.workflow_run_attempt,
        "apk_file": args.apk_name,
        "apk_bytes": summary["apk_bytes"],
        "apk_sha256": summary["apk_sha256"],
        "package": summary["package"],
        "version": summary["version"],
        "app_variant": summary["variant"],
        "backend_environment": summary["backend"],
        "api_base_url": summary["api_base"],
        "gradle_variant": args.gradle_variant,
        "metro_required": False,
        "js_bundle_embedded": summary["js_bundle_embedded"],
        "js_bundle_format": summary["js_bundle_format"],
        "js_bundle_sha256": summary["js_bundle_sha256"],
        "android_debuggable": summary["debuggable"],
        "uses_cleartext_traffic": summary["uses_cleartext_traffic"],
        "min_sdk": summary["min_sdk"],
        "target_sdk": summary["target_sdk"],
        "compile_sdk": summary["compile_sdk"],
        "signing_class": summary["signing_class"],
        "signing_certificate_sha256": summary["signing_certificate_sha256"],
        "signature_schemes": summary["signature_schemes"],
        "maestro_version": args.maestro_version,
        "maestro_archive_sha256": args.maestro_archive_sha256,
        "android_system_image": args.system_image,
        "android_system_image_revision": args.system_image_revision,
        "emulator_version": args.emulator_version,
        "adb_version": args.adb_version,
        "qualification": "packaged_free_journey_passed_on_emulator",
        "qualification_data": "synthetic_only",
    }
    _require(info["gradle_variant"] == "release" and info["android_debuggable"] is False
             and info["js_bundle_embedded"] is True, "only a non-debuggable release-variant APK is a handoff")
    for key, value in info.items():
        _require(not (isinstance(value, str) and _FORBIDDEN_RECORD_TEXT.search(value)),
                 f"BUILDINFO field {key} looks like a private path, credential or signed URL")
    return info


def handoff_markdown(info: dict[str, Any]) -> str:
    short = info["source_commit"][:12]
    return f"""# Inktrospect Android developer handoff

This is a development handoff binary.

| Field | Value |
|---|---|
| Source commit | `{info['source_commit']}` |
| APK | `{info['apk_file']}` (SHA-256 `{info['apk_sha256']}`) |
| Package / version | `{info['package']}` / `{info['version']}` |
| Build | Gradle `{info['gradle_variant']}` variant, `debuggable={str(info['android_debuggable']).lower()}`, embedded {info['js_bundle_format']} bundle; Metro is not required |
| Runtime | `{info['app_variant']}` variant, `{info['backend_environment']}` backend at `{info['api_base_url']}` |
| Signing | `{info['signing_class']}`, certificate SHA-256 `{info['signing_certificate_sha256']}` |
| Qualification | Synthetic Free journey on `{info['android_system_image']}` revision `{info['android_system_image_revision']}` with Maestro `{info['maestro_version']}` |

The signer is the generated Android debug keystore from the Expo/React Native template. It is not a
private publisher key and says nothing about who built the file; verify the SHA-256 above against
`BUILDINFO.json` and the workflow run instead.

## Run it

1. Clone the repository and check out exactly `{info['source_commit']}` (the `source_commit` in `BUILDINFO.json`).
2. Follow `docs/development/local-setup.md` on a supported host: locked backend, local PostgreSQL, migrations and roles.
3. Start the local API and the analysis worker from that checkout.
4. Keep the API on host `127.0.0.1:8000`.
5. Start the API with `PRINCESS_PUBLIC_API_BASE=http://127.0.0.1:8000` so issued upload URLs use the same origin.
6. Start an Android emulator or attach a USB-debuggable device (API level {info['min_sdk']} or newer).
7. Forward the device's port 8000 to the host: `adb reverse tcp:8000 tcp:8000`
8. Install: `adb install -r inktrospect-handoff-{short}.apk`
9. Launch Inktrospect. No Metro server, `expo start` or development launcher is needed.
10. Use only synthetic or explicitly authorized test data.

`adb reverse` has to be repeated after the device restarts or reconnects. The configuration is fixed
at build time: a different API origin requires a new build, not a setting.

It is not:
- Play Store signed;
- a Play production candidate;
- production identity;
- live Premium/model approval;
- live payment evidence;
- production push;
- full physical-device qualification;
- T31 completion.

## Design reference

The v3 UX reference is committed under `docs/design/artifacts/2026-10-04-v3/`. Verify it with
`sha256sum -c SHA256SUMS`, extract it outside the checkout, and compare it against the current source
rather than extracting it over the repository. Current repository contracts and tests take precedence.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="fail-closed APK verification")
    check.add_argument("apk")
    check.add_argument("--name", required=True)
    check.add_argument("--package", required=True)
    check.add_argument("--version", required=True)
    check.add_argument("--scheme", required=True)
    check.add_argument("--variant", required=True)
    check.add_argument("--backend", required=True)
    check.add_argument("--api-base", required=True)
    check.add_argument("--min-sdk", type=int, required=True)
    check.add_argument("--target-sdk", type=int, required=True)
    check.add_argument("--compile-sdk", type=int, required=True)
    check.add_argument("--bundle-format", choices=("hermes", "javascript", "any"), default="hermes")
    check.add_argument("--min-apk-bytes", type=int, default=1_000_000)
    check.add_argument("--min-bundle-bytes", type=int, default=100_000)
    check.add_argument("--forbid-permission", action="append", default=None)
    check.add_argument("--manifest-xml", help="output of `apkanalyzer manifest print`")
    check.add_argument("--signature-report", help="output of `apksigner verify --verbose --print-certs`")
    check.add_argument("--static-only", action="store_true",
                       help="check only APK structure and embedded configuration")
    check.add_argument("--summary-out")
    record = commands.add_parser("record", help="write BUILDINFO.json and HANDOFF.md from a verified summary")
    record.add_argument("apk")
    record.add_argument("--summary", required=True)
    record.add_argument("--apk-name", required=True)
    record.add_argument("--source-commit", required=True)
    record.add_argument("--workflow-run-id", required=True)
    record.add_argument("--workflow-run-attempt", required=True)
    record.add_argument("--gradle-variant", required=True)
    record.add_argument("--maestro-version", required=True)
    record.add_argument("--maestro-archive-sha256", required=True)
    record.add_argument("--system-image", required=True)
    record.add_argument("--system-image-revision", required=True)
    record.add_argument("--emulator-version", required=True)
    record.add_argument("--adb-version", required=True)
    record.add_argument("--journey-passed", action="store_true")
    record.add_argument("--out-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            if args.forbid_permission is None:
                args.forbid_permission = list(DEFAULT_FORBIDDEN_PERMISSIONS)
            summary = verify(args)
            text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
            if args.summary_out:
                Path(args.summary_out).write_text(text, encoding="utf-8")
            print(text, end="")
            print(f"PASS: {summary['scope']} Android handoff verification of {summary['apk_file']}", file=sys.stderr)
            return 0
        summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
        info = buildinfo(summary, args)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "BUILDINFO.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (out / "HANDOFF.md").write_text(handoff_markdown(info), encoding="utf-8")
        print(f"PASS: recorded BUILDINFO.json and HANDOFF.md for {info['apk_file']}", file=sys.stderr)
        return 0
    except HandoffError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(f"FAIL: unreadable verification input: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
