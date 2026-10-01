from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from qualify_supabase_identity import (
    QualificationError,
    SOURCE_REVISION,
    _api_key_kind,
    _fetch_jwks,
    _refresh_access_token,
    qualify,
    validate_receipt,
)

ISSUER = "https://project.supabase.invalid/auth/v1"
AUDIENCE = "authenticated"
ROLE = "authenticated"
SUBJECT = "11111111-1111-4111-8111-111111111111"
SESSION_1 = "22222222-2222-4222-8222-222222222222"
SESSION_2 = "33333333-3333-4333-8333-333333333333"
T0 = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
COMMIT = "a" * 40


def key_and_jwk(kid: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    raw = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return key, {**raw, "kid": kid, "alg": "RS256", "use": "sig"}


def token(
    key,
    *,
    kid: str,
    iat: datetime,
    auth_time: datetime,
    session_id: str,
    **overrides,
) -> str:
    ts = int(iat.timestamp())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": ts,
        "exp": ts + 3600,
        "role": ROLE,
        "aal": "aal1",
        "session_id": session_id,
        "is_anonymous": False,
        "amr": [{"method": "oauth", "timestamp": int(auth_time.timestamp())}],
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def fixture():
    old_key, old_jwk = key_and_jwk("k1")
    new_key, new_jwk = key_and_jwk("k2")
    pre_rotation_jwks = {"keys": [old_jwk, new_jwk]}
    final_jwks = {"keys": [old_jwk, new_jwk]}
    original_auth = T0 - timedelta(seconds=10)
    initial = token(old_key, kid="k1", iat=T0, auth_time=original_auth, session_id=SESSION_1)
    refreshed_at = T0 + timedelta(minutes=5)
    refreshed = token(
        old_key,
        kid="k1",
        iat=refreshed_at,
        auth_time=original_auth,
        session_id=SESSION_1,
    )
    reauth_at = T0 + timedelta(minutes=10)
    reauth = token(new_key, kid="k2", iat=reauth_at, auth_time=reauth_at, session_id=SESSION_2)
    return pre_rotation_jwks, final_jwks, initial, refreshed, reauth


def qualify_fixture(**overrides):
    pre_rotation_jwks, jwks, initial, refreshed, reauth = fixture()
    values = {
        "project_alias": "synthetic-supabase",
        "evidence_kind": "SYNTHETIC_TEST",
        "project_binding": "QUALIFICATION_ONLY",
        "princess_commit": COMMIT,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "role": ROLE,
        "custom_access_token_hook": "disabled",
        "anonymous_sign_in_policy": "disabled",
        "oauth_server_status": "disabled",
        "pre_rotation_jwks": pre_rotation_jwks,
        "jwks": jwks,
        "initial_token": initial,
        "refreshed_token": refreshed,
        "reauth_token": reauth,
        "refresh_source": "SUPPLIED_SYNTHETIC_REFRESH",
        "refresh_response_expires_in_s": 3600,
    }
    values.update(overrides)
    return qualify(**values)


def test_synthetic_qualification_proves_refresh_rotation_reauth_and_emits_redacted_receipt():
    pre_rotation_jwks, jwks, initial, refreshed, reauth = fixture()
    receipt = qualify(
        project_alias="synthetic-supabase",
        evidence_kind="SYNTHETIC_TEST",
        project_binding="QUALIFICATION_ONLY",
        princess_commit=COMMIT,
        issuer=ISSUER,
        audience=AUDIENCE,
        role=ROLE,
        custom_access_token_hook="disabled",
        anonymous_sign_in_policy="disabled",
        oauth_server_status="disabled",
        pre_rotation_jwks=pre_rotation_jwks,
        jwks=jwks,
        initial_token=initial,
        refreshed_token=refreshed,
        reauth_token=reauth,
        refresh_source="SUPPLIED_SYNTHETIC_REFRESH",
        refresh_response_expires_in_s=3600,
    )
    validate_receipt(receipt)
    assert receipt["version"] == "supabase-identity-qualification/3"
    assert receipt["project_binding"] == "QUALIFICATION_ONLY"
    assert receipt["source_revision"] == SOURCE_REVISION
    assert receipt["same_session_initial_refresh"] is True
    assert receipt["refresh_auth_time_unchanged"] is True
    assert receipt["reauth_new_session"] is True
    assert receipt["signing_key_rotation_observed"] is True
    assert receipt["pre_rotation_signing_kid"] == "k1"
    assert receipt["post_rotation_signing_kid"] == "k2"
    assert receipt["access_token_lifetime_s"] == 3600
    assert receipt["logout_fence_refresh_rejected"] is True
    assert receipt["logout_fence_reauth_accepted"] is True
    rendered = json.dumps(receipt, sort_keys=True)
    for secret in (initial, refreshed, reauth, SUBJECT, SESSION_1, SESSION_2, ISSUER):
        assert secret not in rendered


def test_refresh_must_keep_session_and_authentication_time():
    old_key, old_jwk = key_and_jwk("k1")
    new_key, new_jwk = key_and_jwk("k2")
    jwks = {"keys": [old_jwk, new_jwk]}
    initial = token(old_key, kid="k1", iat=T0, auth_time=T0, session_id=SESSION_1)
    refresh_at = T0 + timedelta(minutes=5)
    wrong_session = token(
        old_key,
        kid="k1",
        iat=refresh_at,
        auth_time=T0,
        session_id=str(uuid4()),
    )
    reauth_at = T0 + timedelta(minutes=10)
    reauth = token(new_key, kid="k2", iat=reauth_at, auth_time=reauth_at, session_id=SESSION_2)
    with pytest.raises(QualificationError, match="refresh_session_continuity_failed"):
        qualify_fixture(
            pre_rotation_jwks=jwks,
            jwks=jwks,
            initial_token=initial,
            refreshed_token=wrong_session,
            reauth_token=reauth,
        )

    changed_auth = token(
        old_key,
        kid="k1",
        iat=refresh_at,
        auth_time=refresh_at,
        session_id=SESSION_1,
    )
    with pytest.raises(QualificationError, match="refresh_changed_auth_time"):
        qualify_fixture(
            pre_rotation_jwks=jwks,
            jwks=jwks,
            initial_token=initial,
            refreshed_token=changed_auth,
            reauth_token=reauth,
        )


def test_reauth_must_be_newer_new_session_and_new_signing_key():
    old_key, old_jwk = key_and_jwk("k1")
    new_key, new_jwk = key_and_jwk("k2")
    jwks = {"keys": [old_jwk, new_jwk]}
    initial = token(old_key, kid="k1", iat=T0, auth_time=T0, session_id=SESSION_1)
    refresh_at = T0 + timedelta(minutes=5)
    refreshed = token(old_key, kid="k1", iat=refresh_at, auth_time=T0, session_id=SESSION_1)
    reauth_at = T0 + timedelta(minutes=10)
    same_session = token(new_key, kid="k2", iat=reauth_at, auth_time=reauth_at, session_id=SESSION_1)
    with pytest.raises(QualificationError, match="reauth_new_session_not_observed"):
        qualify_fixture(
            pre_rotation_jwks=jwks,
            jwks=jwks,
            initial_token=initial,
            refreshed_token=refreshed,
            reauth_token=same_session,
        )

    same_key_reauth = token(
        old_key,
        kid="k1",
        iat=reauth_at,
        auth_time=reauth_at,
        session_id=SESSION_2,
    )
    with pytest.raises(QualificationError, match="signing_key_rotation_not_observed"):
        qualify_fixture(
            pre_rotation_jwks=jwks,
            jwks=jwks,
            initial_token=initial,
            refreshed_token=refreshed,
            reauth_token=same_key_reauth,
        )


@pytest.mark.parametrize("hook", ["enabled", "unknown"])
def test_custom_access_token_hook_must_be_explicitly_disabled(hook):
    with pytest.raises(QualificationError, match="custom_access_token_hook_not_qualified"):
        qualify_fixture(custom_access_token_hook=hook)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("anonymous_sign_in_policy", "unknown", "anonymous_sign_in_policy_unreviewed"),
        ("oauth_server_status", "unknown", "oauth_server_status_unreviewed"),
    ],
)
def test_account_policy_values_must_be_inspected_not_assumed(field, value, code):
    with pytest.raises(QualificationError, match=code):
        qualify_fixture(**{field: value})


def test_project_binding_distinguishes_qualification_project_from_runtime_profile():
    receipt = qualify_fixture()
    assert receipt["project_binding"] == "QUALIFICATION_ONLY"

    managed = qualify_fixture(
        evidence_kind="MANAGED_PROJECT",
        project_binding="INTENDED_RUNTIME_PROFILE",
        refresh_source="LIVE_PROVIDER_REFRESH",
    )
    assert managed["project_binding"] == "INTENDED_RUNTIME_PROFILE"

    with pytest.raises(QualificationError, match="synthetic_cannot_bind_runtime_profile"):
        qualify_fixture(project_binding="INTENDED_RUNTIME_PROFILE")


def test_managed_project_requires_live_refresh_witness():
    with pytest.raises(QualificationError, match="managed_project_requires_live_refresh"):
        qualify_fixture(evidence_kind="MANAGED_PROJECT")
    assert qualify_fixture(
        evidence_kind="MANAGED_PROJECT",
        refresh_source="LIVE_PROVIDER_REFRESH",
    )["refresh_source"] == "LIVE_PROVIDER_REFRESH"


def test_access_token_lifetime_is_account_evidence_and_must_be_stable():
    old_key, old_jwk = key_and_jwk("k1")
    new_key, new_jwk = key_and_jwk("k2")
    jwks = {"keys": [old_jwk, new_jwk]}
    original_auth = T0 - timedelta(seconds=10)
    initial = token(old_key, kid="k1", iat=T0, auth_time=original_auth, session_id=SESSION_1)
    refresh_at = T0 + timedelta(minutes=5)
    refreshed = token(
        old_key,
        kid="k1",
        iat=refresh_at,
        auth_time=original_auth,
        session_id=SESSION_1,
    )
    reauth_at = T0 + timedelta(minutes=10)
    bad_reauth = token(
        new_key,
        kid="k2",
        iat=reauth_at,
        auth_time=reauth_at,
        session_id=SESSION_2,
        exp=int(reauth_at.timestamp()) + 1800,
    )
    with pytest.raises(QualificationError, match="access_token_lifetime_drift"):
        qualify_fixture(
            pre_rotation_jwks=jwks,
            jwks=jwks,
            initial_token=initial,
            refreshed_token=refreshed,
            reauth_token=bad_reauth,
        )


def test_live_jwks_fetch_reuses_bounded_redirect_refusing_source():
    def ok(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": []})

    assert _fetch_jwks(ISSUER, transport=httpx.MockTransport(ok)) == {"keys": []}

    def redirect(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.invalid/jwks.json"})

    with pytest.raises(QualificationError, match="jwks_request_failed"):
        _fetch_jwks(ISSUER, transport=httpx.MockTransport(redirect))


def test_live_refresh_refuses_redirects_and_bounds_response_body():
    calls = []

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.invalid/token"})

    with pytest.raises(QualificationError, match="refresh_redirect_refused"):
        _refresh_access_token(
            ISSUER,
            api_key="sb_publishable_test",
            refresh_token="refresh-secret",
            transport=httpx.MockTransport(redirect),
        )
    assert calls == [ISSUER + "/token?grant_type=refresh_token"]

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"pad":"' + b"x" * 5000 + b'"}')

    with pytest.raises(QualificationError, match="refresh_response_too_large"):
        _refresh_access_token(
            ISSUER,
            api_key="sb_publishable_test",
            refresh_token="refresh-secret",
            transport=httpx.MockTransport(oversized),
            max_response_bytes=4096,
        )


def test_live_refresh_disables_ambient_httpx_environment(monkeypatch):
    import qualify_supabase_identity as cli

    _, _, _, refreshed, _ = fixture()
    real_client = httpx.Client
    seen = {}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": refreshed, "expires_in": 3600})

    def client_factory(*args, **kwargs):
        seen.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(cli.httpx, "Client", client_factory)
    access, expires_in = cli._refresh_access_token(
        ISSUER,
        api_key="sb_publishable_test",
        refresh_token="refresh-secret",
    )
    assert access == refreshed and expires_in == 3600
    assert seen["trust_env"] is False
    assert seen["follow_redirects"] is False


@pytest.mark.parametrize(
    "status,code",
    [
        (429, "refresh_rate_limited"),
        (503, "refresh_unavailable"),
        (403, "refresh_http_error"),
    ],
)
def test_live_refresh_http_failures_are_safe_and_typed(status, code):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"private upstream detail")

    with pytest.raises(QualificationError) as err:
        _refresh_access_token(
            ISSUER,
            api_key="sb_publishable_test",
            refresh_token="refresh-secret",
            transport=httpx.MockTransport(handler),
        )
    assert str(err.value) == code
    assert "private upstream detail" not in str(err.value)
    assert "refresh-secret" not in str(err.value)


def test_live_refresh_transport_errors_are_redacted():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refresh-secret upstream detail", request=request)

    with pytest.raises(QualificationError) as err:
        _refresh_access_token(
            ISSUER,
            api_key="sb_publishable_test",
            refresh_token="refresh-secret",
            transport=httpx.MockTransport(handler),
        )
    assert str(err.value) == "refresh_request_failed"
    assert "refresh-secret" not in str(err.value)


def test_live_refresh_uses_low_privilege_api_key_and_returns_only_access_token():
    _, _, _, refreshed, _ = fixture()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apikey")
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": refreshed,
                "refresh_token": "rotated-refresh-secret",
                "expires_in": 3600,
                "token_type": "bearer",
            },
        )

    access, expires_in = _refresh_access_token(
        ISSUER,
        api_key="sb_publishable_test",
        refresh_token="refresh-secret",
        transport=httpx.MockTransport(handler),
    )
    assert access == refreshed and expires_in == 3600
    assert seen["apikey"] == "sb_publishable_test"
    assert "grant_type=refresh_token" in seen["url"]
    assert "refresh-secret" in seen["body"]
    assert "rotated-refresh-secret" not in json.dumps(seen)


def test_elevated_api_keys_are_rejected_before_network():
    assert _api_key_kind("sb_publishable_test") == "publishable"
    legacy_anon = jwt.encode({"role": "anon"}, "legacy", algorithm="HS256")
    assert _api_key_kind(legacy_anon) == "legacy_anon"
    for value in (
        "sb_secret_test",
        jwt.encode({"role": "service_role"}, "legacy", algorithm="HS256"),
    ):
        with pytest.raises(QualificationError, match="elevated_api_key_not_allowed"):
            _api_key_kind(value)


def test_receipt_validator_rejects_scope_or_witness_tampering():
    receipt = qualify_fixture()
    for field, value in (
        ("production_activation", True),
        ("provider_selection_claim", True),
        ("logout_fence_refresh_rejected", False),
        ("signing_key_rotation_observed", False),
        ("source_revision", "0" * 40),
        ("project_binding", "UNKNOWN"),
    ):
        changed = dict(receipt)
        changed[field] = value
        with pytest.raises(QualificationError):
            validate_receipt(changed)


def test_cli_requires_explicit_gate_and_file_only_synthetic_credentials(tmp_path, monkeypatch):
    import qualify_supabase_identity as cli

    pre_rotation_jwks, jwks, initial, refreshed, reauth = fixture()
    pre_jwks_path = tmp_path / "jwks-before.json"
    jwks_path = tmp_path / "jwks-after.json"
    pre_jwks_path.write_text(json.dumps(pre_rotation_jwks), encoding="utf-8")
    jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
    paths = []
    for name, value in (("initial", initial), ("refresh", refreshed), ("reauth", reauth)):
        path = tmp_path / f"{name}.jwt"
        path.write_text(value, encoding="utf-8")
        paths.append(path)
    output = tmp_path / "receipt.json"
    argv = [
        "--project-alias",
        "synthetic-supabase",
        "--evidence-kind",
        "SYNTHETIC_TEST",
        "--project-binding",
        "QUALIFICATION_ONLY",
        "--issuer",
        ISSUER,
        "--audience",
        AUDIENCE,
        "--role",
        ROLE,
        "--custom-access-token-hook",
        "disabled",
        "--anonymous-sign-ins",
        "disabled",
        "--oauth-server",
        "disabled",
        "--pre-rotation-jwks-file",
        str(pre_jwks_path),
        "--jwks-file",
        str(jwks_path),
        "--initial-token-file",
        str(paths[0]),
        "--refreshed-token-file",
        str(paths[1]),
        "--reauth-token-file",
        str(paths[2]),
        "--output",
        str(output),
    ]
    monkeypatch.delenv("PRINCESS_SUPABASE_QUALIFY", raising=False)
    assert cli.main(argv) == 2
    assert not output.exists()
    monkeypatch.setenv("PRINCESS_SUPABASE_QUALIFY", "1")
    monkeypatch.setattr(cli, "_repo_commit", lambda: COMMIT)
    assert cli.main(argv) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["result"] == "PASS"
    assert all(secret not in output.read_text(encoding="utf-8") for secret in (initial, refreshed, reauth))


def test_managed_cli_sequences_live_refresh_then_rotation_then_reauth(tmp_path, monkeypatch):
    import builtins
    import qualify_supabase_identity as cli

    pre_rotation_jwks, jwks, initial, refreshed, reauth = fixture()
    initial_path = tmp_path / "initial.jwt"
    refresh_path = tmp_path / "refresh.token"
    api_key_path = tmp_path / "publishable.key"
    reauth_path = tmp_path / "reauth.jwt"
    output = tmp_path / "receipt.json"
    initial_path.write_text(initial, encoding="utf-8")
    refresh_path.write_text("refresh-secret", encoding="utf-8")
    api_key_path.write_text("sb_publishable_test", encoding="utf-8")
    reauth_path.write_text("stale-token", encoding="utf-8")

    class Tty:
        @staticmethod
        def isatty():
            return True

    jwks_values = iter((pre_rotation_jwks, jwks))
    monkeypatch.setenv("PRINCESS_SUPABASE_QUALIFY", "1")
    monkeypatch.setattr(cli.sys, "stdin", Tty())
    monkeypatch.setattr(cli, "_repo_commit", lambda: COMMIT)
    monkeypatch.setattr(cli, "_fetch_jwks", lambda issuer: next(jwks_values))
    monkeypatch.setattr(
        cli,
        "_refresh_access_token",
        lambda issuer, *, api_key, refresh_token: (refreshed, 3600),
    )

    def confirm():
        reauth_path.write_text(reauth, encoding="utf-8")
        return ""

    monkeypatch.setattr(builtins, "input", confirm)
    argv = [
        "--project-alias",
        "managed-supabase",
        "--evidence-kind",
        "MANAGED_PROJECT",
        "--project-binding",
        "QUALIFICATION_ONLY",
        "--issuer",
        ISSUER,
        "--audience",
        AUDIENCE,
        "--role",
        ROLE,
        "--custom-access-token-hook",
        "disabled",
        "--anonymous-sign-ins",
        "disabled",
        "--oauth-server",
        "disabled",
        "--api-key-file",
        str(api_key_path),
        "--initial-token-file",
        str(initial_path),
        "--refresh-token-file",
        str(refresh_path),
        "--reauth-token-file",
        str(reauth_path),
        "--output",
        str(output),
    ]
    assert cli.main(argv) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["evidence_kind"] == "MANAGED_PROJECT"
    assert receipt["project_binding"] == "QUALIFICATION_ONLY"
    assert receipt["refresh_source"] == "LIVE_PROVIDER_REFRESH"
    assert receipt["signing_key_rotation_observed"] is True
