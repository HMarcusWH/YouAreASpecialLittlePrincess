"""Static smoke prerequisites for the Railway guest APK; not a live-device substitute."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/railway-guest-apk.yml"


def test_guest_apk_provenance_precedes_any_test_upload():
    src = WORKFLOW.read_text("utf-8")
    verify = src.index('call("GET", "/health/build")')
    admit = src.index('call("POST", "/v1/guest-sessions")')
    reserve = src.index('call("POST", "/v1/uploads"')
    assert verify < admit < reserve
    assert "REVIEWED_RAILWAY_BACKEND_SHA" in src
    assert 'build.get("source_commit_sha") != expected_source' in src
    assert 'build.get("contract_bundle_sha256") != expected_contract' in src
    assert 'observed != expected_config' in src


def test_guest_apk_artifact_proves_client_source_and_binary_hash():
    src = WORKFLOW.read_text("utf-8")
    assert "git rev-parse HEAD > dist/inktrospect-railway-guest-test.source-sha" in src
    assert "sha256sum inktrospect-railway-guest-test.apk" in src
    assert "dist/inktrospect-railway-guest-test.source-sha" in src
    assert "apksigner" in src and "assembleRelease" in src
    assert "INKTROSPECT_REMOTE_GUEST_ONLY" in src


def test_guest_apk_is_opt_in_and_checks_remote_backend_before_install():
    src = WORKFLOW.read_text("utf-8")
    triggers = src.split("permissions:", 1)[0]
    assert src.splitlines()[0] == "name: Inktrospect Railway guest-test APK"
    assert "workflow_dispatch:" in triggers
    assert "  push:" not in triggers
    checkout = src.index("actions/checkout@")
    preflight = src.index("Preflight reviewed Railway commit, config and contracts")
    install = src.index("pnpm install --frozen-lockfile")
    recheck = src.index("Recheck reviewed Railway commit immediately before guest admission")
    guest = src.index("Verify remote HTTPS guest API from GitHub runner")
    assert checkout < preflight < install < recheck < guest
    assert "vars.REVIEWED_RAILWAY_BACKEND_SHA" in src
    assert "build.get(\"analysis_config_sha256\") != config" in src
    assert "build.get(\"contract_bundle_sha256\") != contract" in src
    assert "Railway source changed since build preflight" in src
