from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from qualify_supabase_identity import (
    QualificationError, SOURCE_REVISION, qualify, validate_receipt,
)

ISSUER = "https://project.supabase.invalid/auth/v1"
AUDIENCE = "authenticated"
ROLE = "authenticated"
SUBJECT = "11111111-1111-4111-8111-111111111111"
SESSION_1 = "22222222-2222-4222-8222-222222222222"
SESSION_2 = "33333333-3333-4333-8333-333333333333"
T0 = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def key_and_jwks():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    raw = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return key, {"keys": [{**raw, "kid": "k1", "alg": "RS256", "use": "sig"}]}


def token(key, *, iat: datetime, auth_time: datetime, session_id: str) -> str:
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
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


def fixture():
    key, jwks = key_and_jwks()
    initial = token(key, iat=T0, auth_time=T0 - timedelta(seconds=10), session_id=SESSION_1)
    refreshed_at = T0 + timedelta(minutes=5)
    refreshed = token(key, iat=refreshed_at, auth_time=T0 - timedelta(seconds=10), session_id=SESSION_1)
    reauth_at = T0 + timedelta(minutes=10)
    reauth = token(key, iat=reauth_at, auth_time=reauth_at, session_id=SESSION_2)
    return jwks, initial, refreshed, reauth


def qualify_fixture(**overrides):
    jwks, initial, refreshed, reauth = fixture()
    values = {
        "project_alias": "synthetic-supabase",
        "evidence_kind": "SYNTHETIC_TEST",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "role": ROLE,
        "custom_access_token_hook": "disabled",
        "jwks": jwks,
        "initial_token": initial,
        "refreshed_token": refreshed,
        "reauth_token": reauth,
    }
    values.update(overrides)
    return qualify(**values)


def test_synthetic_qualification_proves_refresh_vs_reauth_and_emits_redacted_receipt():
    jwks, initial, refreshed, reauth = fixture()
    receipt = qualify(
        project_alias="synthetic-supabase",
        evidence_kind="SYNTHETIC_TEST",
        issuer=ISSUER,
        audience=AUDIENCE,
        role=ROLE,
        custom_access_token_hook="disabled",
        jwks=jwks,
        initial_token=initial,
        refreshed_token=refreshed,
        reauth_token=reauth,
    )
    validate_receipt(receipt)
    assert receipt["source_revision"] == SOURCE_REVISION
    assert receipt["same_session_initial_refresh"] is True
    assert receipt["refresh_auth_time_unchanged"] is True
    assert receipt["reauth_new_session"] is True
    assert receipt["logout_fence_refresh_rejected"] is True
    assert receipt["logout_fence_reauth_accepted"] is True
    rendered = json.dumps(receipt, sort_keys=True)
    for secret in (initial, refreshed, reauth, SUBJECT, SESSION_1, SESSION_2, ISSUER):
        assert secret not in rendered


def test_refresh_must_keep_session_and_authentication_time():
    key, jwks = key_and_jwks()
    initial = token(key, iat=T0, auth_time=T0, session_id=SESSION_1)
    refresh_at = T0 + timedelta(minutes=5)
    wrong_session = token(key, iat=refresh_at, auth_time=T0, session_id=str(uuid4()))
    reauth_at = T0 + timedelta(minutes=10)
    reauth = token(key, iat=reauth_at, auth_time=reauth_at, session_id=SESSION_2)
    with pytest.raises(QualificationError, match="refresh_session_continuity_failed"):
        qualify_fixture(jwks=jwks, initial_token=initial, refreshed_token=wrong_session, reauth_token=reauth)

    changed_auth = token(key, iat=refresh_at, auth_time=refresh_at, session_id=SESSION_1)
    with pytest.raises(QualificationError, match="refresh_changed_auth_time"):
        qualify_fixture(jwks=jwks, initial_token=initial, refreshed_token=changed_auth, reauth_token=reauth)


def test_reauth_must_be_newer_new_session_same_subject():
    key, jwks = key_and_jwks()
    initial = token(key, iat=T0, auth_time=T0, session_id=SESSION_1)
    refresh_at = T0 + timedelta(minutes=5)
    refreshed = token(key, iat=refresh_at, auth_time=T0, session_id=SESSION_1)
    reauth_at = T0 + timedelta(minutes=10)
    same_session = token(key, iat=reauth_at, auth_time=reauth_at, session_id=SESSION_1)
    with pytest.raises(QualificationError, match="reauth_new_session_not_observed"):
        qualify_fixture(jwks=jwks, initial_token=initial, refreshed_token=refreshed, reauth_token=same_session)


@pytest.mark.parametrize("hook", ["enabled", "unknown"])
def test_custom_access_token_hook_must_be_explicitly_disabled(hook):
    with pytest.raises(QualificationError, match="custom_access_token_hook_not_qualified"):
        qualify_fixture(custom_access_token_hook=hook)


def test_receipt_validator_rejects_scope_or_witness_tampering():
    receipt = qualify_fixture()
    for field, value in (
        ("production_activation", True),
        ("provider_selection_claim", True),
        ("logout_fence_refresh_rejected", False),
        ("source_revision", "0" * 40),
    ):
        changed = dict(receipt)
        changed[field] = value
        with pytest.raises(QualificationError):
            validate_receipt(changed)


def test_cli_requires_explicit_gate_and_never_accepts_token_values_on_argv(tmp_path, monkeypatch):
    import qualify_supabase_identity as cli

    jwks, initial, refreshed, reauth = fixture()
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(jwks), encoding="utf-8")
    paths = []
    for name, value in (("initial", initial), ("refresh", refreshed), ("reauth", reauth)):
        path = tmp_path / f"{name}.jwt"
        path.write_text(value, encoding="utf-8")
        paths.append(path)
    output = tmp_path / "receipt.json"
    argv = [
        "--project-alias", "synthetic-supabase",
        "--evidence-kind", "SYNTHETIC_TEST",
        "--issuer", ISSUER,
        "--audience", AUDIENCE,
        "--role", ROLE,
        "--custom-access-token-hook", "disabled",
        "--jwks-file", str(jwks_path),
        "--initial-token-file", str(paths[0]),
        "--refreshed-token-file", str(paths[1]),
        "--reauth-token-file", str(paths[2]),
        "--output", str(output),
    ]
    monkeypatch.delenv("PRINCESS_SUPABASE_QUALIFY", raising=False)
    assert cli.main(argv) == 2
    assert not output.exists()
    monkeypatch.setenv("PRINCESS_SUPABASE_QUALIFY", "1")
    assert cli.main(argv) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["result"] == "PASS"
    assert all(token not in output.read_text(encoding="utf-8") for token in (initial, refreshed, reauth))
