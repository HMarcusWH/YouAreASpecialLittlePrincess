"""Fail-closed checks of the standalone Android handoff verifier, using small synthetic APK-shaped ZIPs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import zipfile

import pytest

import verify_android_handoff as handoff

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
EXPECTED = ["--name", "Inktrospect", "--package", "se.inktrospect.development", "--version", "0.1.0",
            "--scheme", "inktrospect-dev", "--variant", "development", "--backend", "local", "--api-base", API,
            "--min-sdk", "24", "--target-sdk", "36", "--compile-sdk", "36", "--min-apk-bytes", "1"]
MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" android:versionCode="1"
    android:versionName="0.1.0" android:compileSdkVersion="36" package="se.inktrospect.development"
    platformBuildVersionCode="36">
  <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="36" />
  <uses-permission android:name="android.permission.INTERNET" />
  <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="32" />
  <application android:label="@string/app_name" android:usesCleartextTraffic="true">
    <activity android:name=".MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
      </intent-filter>
    </activity>
  </application>
</manifest>
"""
DIGEST = "ab" * 32
SIGNATURE = f"""Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): false
Number of signers: 1
Signer #1 certificate DN: CN=Android Debug, OU=Android, O=Unknown, L=Unknown, ST=Unknown, C=US
Signer #1 certificate SHA-256 digest: {DIGEST}
Signer #1 certificate SHA-1 digest: {'cd' * 20}
"""


def runtime(**overrides):
    value = {"variant": "development", "backendEnvironment": "local", "apiBaseUrl": API, "uploadOrigins": [],
             "devIdentity": True, "linkSchemes": ["inktrospect-dev"], "linkHosts": []}
    value.update(overrides)
    return value


def config(**overrides):
    value = {"name": "Inktrospect", "slug": "inktrospect", "version": "0.1.0", "scheme": "inktrospect-dev",
             "android": {"package": "se.inktrospect.development"}, "extra": {"runtime": runtime()}}
    value.update(overrides)
    return value


def make_apk(path: Path, *, bundle: bytes | None = handoff.HERMES_MAGIC + bytes(200_000),
             app_config: object = None, raw_config: bytes | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-xml")
        archive.writestr("classes.dex", b"dex\n035\x00")
        if bundle is not None:
            archive.writestr(handoff.BUNDLE, bundle)
        if raw_config is not None:
            archive.writestr(handoff.APP_CONFIG, raw_config)
        elif app_config is not False:
            archive.writestr(handoff.APP_CONFIG, json.dumps(config() if app_config is None else app_config))
    return path


def run(tmp_path: Path, apk: Path, *extra: str, manifest: str = MANIFEST, signature: str = SIGNATURE,
        static: bool = False) -> int:
    argv = ["verify", str(apk), *EXPECTED, "--summary-out", str(tmp_path / "summary.json"), *extra]
    if static:
        argv.append("--static-only")
    else:
        (tmp_path / "manifest.xml").write_text(manifest, encoding="utf-8")
        (tmp_path / "signature.txt").write_text(signature, encoding="utf-8")
        argv += ["--manifest-xml", str(tmp_path / "manifest.xml"), "--signature-report", str(tmp_path / "signature.txt")]
    return handoff.main(argv)


def test_complete_development_handoff_passes_and_records_resolved_values(tmp_path, capsys):
    apk = make_apk(tmp_path / "app-release.apk")
    assert run(tmp_path, apk) == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["scope"] == "complete"
    assert (summary["package"], summary["variant"], summary["backend"], summary["api_base"]) == (
        "se.inktrospect.development", "development", "local", API)
    assert summary["js_bundle_embedded"] is True and summary["js_bundle_format"] == "hermes"
    assert (summary["min_sdk"], summary["target_sdk"], summary["compile_sdk"]) == (24, 36, 36)
    assert summary["debuggable"] is False and summary["uses_cleartext_traffic"] is True
    assert summary["signing_class"] == "android_debug_key"
    assert summary["signing_certificate_sha256"] == DIGEST
    assert "PASS" in capsys.readouterr().err


def test_dev_client_apk_without_embedded_bundle_fails(tmp_path, capsys):
    # The critical regression: a Metro-dependent dev-client APK must never qualify as a handoff.
    apk = make_apk(tmp_path / "app-debug.apk", bundle=None)
    assert run(tmp_path, apk) == 1
    assert "no embedded application bundle" in capsys.readouterr().err
    assert run(tmp_path, apk, static=True) == 1


@pytest.mark.parametrize("bundle", [b"", b"x" * 99_999])
def test_trivial_bundle_fails(tmp_path, bundle, capsys):
    assert run(tmp_path, make_apk(tmp_path / "a.apk", bundle=bundle)) == 1
    assert "implausibly small" in capsys.readouterr().err


def test_plain_javascript_bundle_fails_when_hermes_is_expected(tmp_path, capsys):
    apk = make_apk(tmp_path / "a.apk", bundle=b"var __BUNDLE_START_TIME__=0;" + b" " * 200_000)
    assert run(tmp_path, apk) == 1
    assert "expected hermes" in capsys.readouterr().err
    assert run(tmp_path, apk, "--bundle-format", "javascript") == 0


@pytest.mark.parametrize("kwargs, message", [
    ({"app_config": False}, "no embedded application configuration"),
    ({"raw_config": b"{not json"}, "does not parse"),
    ({"raw_config": b"[]"}, "not an object"),
    ({"app_config": config(extra={})}, "no extra.runtime"),
])
def test_missing_or_unparseable_embedded_config_fails(tmp_path, kwargs, message, capsys):
    assert run(tmp_path, make_apk(tmp_path / "a.apk", **kwargs)) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("runtime_overrides, message", [
    ({"apiBaseUrl": ""}, "blank"),
    ({"apiBaseUrl": "https://api.inktrospect.se"}, "not a loopback/private"),
    ({"apiBaseUrl": "http://user:pw@127.0.0.1:8000"}, "not a plain origin"),
    ({"backendEnvironment": "production"}, "not local/test"),
    ({"backendEnvironment": "staging"}, "not local/test"),
    ({"variant": "store"}, "not a development build"),
    ({"variant": "staging"}, "not a development build"),
    ({"devIdentity": False}, "devIdentity"),
    ({"linkHosts": ["inktrospect.se"]}, "linkHosts"),
    ({"uploadOrigins": ["https://storage.example.com"]}, "not a loopback/private"),
])
def test_non_handoff_runtime_is_rejected_even_before_expectations(tmp_path, runtime_overrides, message, capsys):
    apk = make_apk(tmp_path / "a.apk", app_config=config(extra={"runtime": runtime(**runtime_overrides)}))
    assert run(tmp_path, apk) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("package", sorted(handoff.FORBIDDEN_PACKAGES))
def test_production_and_staging_packages_are_rejected(tmp_path, package, capsys):
    apk = make_apk(tmp_path / "a.apk", app_config=config(android={"package": package}))
    assert run(tmp_path, apk) == 1
    assert "non-development identity" in capsys.readouterr().err


def test_a_wrong_expectation_cannot_bless_a_production_url(tmp_path, capsys):
    apk = make_apk(tmp_path / "a.apk", app_config=config(extra={"runtime": runtime(apiBaseUrl="https://api.inktrospect.se")}))
    argv = ["verify", str(apk), *EXPECTED, "--static-only"]
    argv[argv.index("--api-base") + 1] = "https://api.inktrospect.se"
    assert handoff.main(argv) == 1
    assert "not a loopback/private" in capsys.readouterr().err


@pytest.mark.parametrize("flag, value", [("--version", "0.2.0"), ("--api-base", "http://10.0.2.2:8000"),
                                         ("--package", "se.inktrospect.other"), ("--scheme", "inktrospect")])
def test_expected_build_values_must_match_exactly(tmp_path, flag, value, capsys):
    apk = make_apk(tmp_path / "a.apk")
    argv = ["verify", str(apk), *EXPECTED, "--static-only"]
    argv[argv.index(flag) + 1] = value
    assert handoff.main(argv) == 1
    assert "expected" in capsys.readouterr().err


def test_complete_verification_requires_manifest_and_signature_evidence(tmp_path, capsys):
    apk = make_apk(tmp_path / "a.apk")
    assert handoff.main(["verify", str(apk), *EXPECTED]) == 1
    assert "--manifest-xml is required" in capsys.readouterr().err
    assert run(tmp_path, apk, static=True) == 0
    assert json.loads((tmp_path / "summary.json").read_text())["scope"] == "static_only"


def test_structurally_invalid_apks_fail(tmp_path, capsys):
    text = tmp_path / "not.apk"
    text.write_text("not a zip " * 1000)
    assert run(tmp_path, text) == 1
    assert "not a valid ZIP" in capsys.readouterr().err
    assert run(tmp_path, tmp_path / "missing.apk") == 1
    small = make_apk(tmp_path / "small.apk")
    argv = ["verify", str(small), *EXPECTED, "--static-only"]
    argv[argv.index("--min-apk-bytes") + 1] = "10000000"
    assert handoff.main(argv) == 1
    assert "implausibly small" in capsys.readouterr().err


@pytest.mark.parametrize("old, new, message", [
    ('android:usesCleartextTraffic="true"', 'android:usesCleartextTraffic="true" android:debuggable="true"', "debuggable"),
    (' android:usesCleartextTraffic="true"', "", "usesCleartextTraffic"),
    ('android:usesCleartextTraffic="true"', 'android:usesCleartextTraffic="false"', "usesCleartextTraffic"),
    ('android:minSdkVersion="24"', 'android:minSdkVersion="23"', "minSdkVersion"),
    ('android:targetSdkVersion="36"', 'android:targetSdkVersion="35"', "targetSdkVersion"),
    ('android:compileSdkVersion="36"', 'android:compileSdkVersion="35"', "compile SDK"),
    ('package="se.inktrospect.development"', 'package="se.inktrospect"', "manifest package"),
    ('android:versionName="0.1.0"', 'android:versionName="0.1.1"', "versionName"),
    ("android.intent.category.LAUNCHER", "android.intent.category.DEFAULT", "LAUNCHER"),
    ('android:exported="true"', 'android:exported="false"', "not exported"),
    ('android:maxSdkVersion="32"', 'android:maxSdkVersion="33"', "not capped"),
    ('<uses-permission android:name="android.permission.INTERNET" />',
     '<uses-permission android:name="android.permission.READ_MEDIA_IMAGES" />', "READ_MEDIA_IMAGES"),
    ('<uses-permission android:name="android.permission.INTERNET" />',
     '<uses-permission android:name="android.permission.RECORD_AUDIO" />', "RECORD_AUDIO"),
    ("<manifest ", "<manifestx ", "does not parse"),
    ("<manifest ", "<other-root ", "no <manifest>"),
])
def test_manifest_boundaries_fail_closed(tmp_path, old, new, message, capsys):
    assert old in MANIFEST
    assert run(tmp_path, make_apk(tmp_path / "a.apk"), manifest=MANIFEST.replace(old, new)) == 1
    assert message in capsys.readouterr().err


def test_capped_legacy_storage_permission_is_not_rejected():
    # The picker's capped storage pair is deliberate (Android 7-9 camera capture), unlike broad media access.
    assert "android.permission.WRITE_EXTERNAL_STORAGE" in MANIFEST
    assert "android.permission.WRITE_EXTERNAL_STORAGE" not in handoff.DEFAULT_FORBIDDEN_PERMISSIONS


@pytest.mark.parametrize("old, new, message", [
    ("Verifies\n", "", "did not report"),
    ("v2 scheme (APK Signature Scheme v2): true", "v2 scheme (APK Signature Scheme v2): false", "v2/v3"),
    ("Number of signers: 1", "Number of signers: 2", "exactly one signer"),
    ("CN=Android Debug", "CN=Inktrospect Release", "not the generated Android debug identity"),
    (f"SHA-256 digest: {DIGEST}", "SHA-256 digest: nothex", "no signer DN/SHA-256"),
])
def test_signature_must_verify_with_the_debug_identity(tmp_path, old, new, message, capsys):
    assert run(tmp_path, make_apk(tmp_path / "a.apk"), signature=SIGNATURE.replace(old, new)) == 1
    assert message in capsys.readouterr().err


def record_args(tmp_path: Path, apk: Path, **overrides: str) -> list[str]:
    values = {"--summary": str(tmp_path / "summary.json"), "--apk-name": "inktrospect-handoff-0123456789ab.apk",
              "--source-commit": "0123456789abcdef0123456789abcdef01234567", "--workflow-run-id": "1",
              "--workflow-run-attempt": "1", "--gradle-variant": "release", "--maestro-version": "2.11.0",
              "--maestro-archive-sha256": "5384593cb4e7a106489e75a821d157dd43f4e438df6bc308b72e82c685e1283a",
              "--system-image": "system-images;android-36;google_apis;x86_64", "--system-image-revision": "7",
              "--emulator-version": "Android emulator version 36.1.9.0", "--adb-version": "Version 36.0.0",
              "--out-dir": str(tmp_path / "out")}
    values.update(overrides)
    return ["record", str(apk), *[item for pair in values.items() for item in pair], "--journey-passed"]


def test_record_writes_buildinfo_and_handoff_guide_from_verified_values(tmp_path):
    apk = make_apk(tmp_path / "app-release.apk")
    assert run(tmp_path, apk) == 0
    assert handoff.main(record_args(tmp_path, apk)) == 0
    info = json.loads((tmp_path / "out/BUILDINFO.json").read_text())
    assert info["purpose"] == "developer_handoff" and info["release_candidate"] is False
    assert info["gradle_variant"] == "release" and info["metro_required"] is False
    assert info["android_debuggable"] is False and info["js_bundle_embedded"] is True
    assert info["signing_class"] == "android_debug_key" and info["signing_certificate_sha256"] == DIGEST
    assert info["qualification_data"] == "synthetic_only"
    assert info["api_base_url"] == API and info["backend_environment"] == "local"
    for required in ("schema_version", "source_commit", "workflow_run_id", "workflow_run_attempt", "package",
                     "version", "app_variant", "min_sdk", "target_sdk", "compile_sdk", "maestro_version",
                     "maestro_archive_sha256", "android_system_image", "android_system_image_revision",
                     "emulator_version", "adb_version"):
        assert info[required] not in (None, ""), required
    guide = (tmp_path / "out/HANDOFF.md").read_text()
    assert "This is a development handoff binary." in guide
    assert "adb reverse tcp:8000 tcp:8000" in guide
    assert "adb install -r inktrospect-handoff-0123456789ab.apk" in guide
    assert "docs/design/artifacts/2026-10-04-v3/" in guide
    for non_claim in ("Play Store signed", "T31 completion", "live payment evidence", "production push"):
        assert non_claim in guide


def test_record_refuses_unqualified_or_private_inputs(tmp_path, capsys):
    apk = make_apk(tmp_path / "app-release.apk")
    assert run(tmp_path, apk, static=True) == 0
    assert handoff.main(record_args(tmp_path, apk)) == 1
    assert "complete" in capsys.readouterr().err
    assert run(tmp_path, apk) == 0
    assert handoff.main([a for a in record_args(tmp_path, apk) if a != "--journey-passed"]) == 1
    assert handoff.main(record_args(tmp_path, apk, **{"--gradle-variant": "debug"})) == 1
    assert handoff.main(record_args(tmp_path, apk, **{"--source-commit": "main"})) == 1
    assert handoff.main(record_args(tmp_path, apk, **{"--adb-version": "Installed as /home/me/sdk/adb"})) == 1
    capsys.readouterr()
    make_apk(apk, bundle=handoff.HERMES_MAGIC + bytes(300_000))
    assert handoff.main(record_args(tmp_path, apk)) == 1
    assert "changed after verification" in capsys.readouterr().err
    assert not (tmp_path / "out/BUILDINFO.json").exists()


def test_forbidden_packages_match_the_reviewed_app_variants():
    source = (ROOT / "apps/mobile/app.config.ts").read_text(encoding="utf-8")
    ids = dict(re.findall(r'^\s+(development|staging|store): \{ id: "([^"]+)"', source, re.MULTILINE))
    assert ids["development"] == "se.inktrospect.development"
    assert handoff.FORBIDDEN_PACKAGES == {ids["staging"], ids["store"]}
