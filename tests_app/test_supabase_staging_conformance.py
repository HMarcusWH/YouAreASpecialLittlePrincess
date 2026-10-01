"""Offline tests for the operator-only Supabase staging runtime conformance harness."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import princess_api.compose as compose_module
import princess_app.config_supabase as binding_config
import verify_supabase_staging_runtime as conformance
from princess_app.adapters.fakes import FakeClock
from princess_app.ports.base import InvalidInput

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
SUBJECT = "11111111-1111-4111-8111-111111111111"
SESSION = "22222222-2222-4222-8222-222222222222"
COMMIT = "a" * 40


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key_and_jwk():
    key = ec.generate_private_key(ec.SECP256R1())
    raw = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    return key, {**raw, "kid": "staging-kid", "alg": "ES256", "use": "sig"}


def _world(monkeypatch):
    project_ref = "qualified-staging-ref"
    issuer = f"https://{project_ref}.supabase.co/auth/v1"
    audience = "qualified-audience"
    role = "authenticated"
    manifest_hash = hashlib.sha256(
        (ROOT / "infra" / "environments" / "staging.json").read_bytes()
    ).hexdigest()
    receipt_hash = "2" * 64
    snapshot_hash = "3" * 64
    project_hash = _sha(project_ref)
    source_revision = "4" * 40

    monkeypatch.setattr(binding_config, "QUALIFIED_ENVIRONMENT_MANIFEST_SHA256", manifest_hash)
    monkeypatch.setattr(binding_config, "QUALIFICATION_RECEIPT_SHA256", receipt_hash)
    monkeypatch.setattr(binding_config, "ACCOUNT_SNAPSHOT_SHA256", snapshot_hash)
    monkeypatch.setattr(binding_config, "PROJECT_REF_SHA256", project_hash)
    monkeypatch.setattr(binding_config, "QUALIFIED_ISSUER_SHA256", _sha(issuer))
    monkeypatch.setattr(binding_config, "QUALIFIED_AUDIENCE_SHA256", _sha(audience))
    monkeypatch.setattr(binding_config, "QUALIFIED_ROLE_SHA256", _sha(role))
    monkeypatch.setattr(binding_config, "SOURCE_REVISION", source_revision)

    binding = {
        "version": binding_config.BINDING_VERSION,
        "provider": binding_config.PROVIDER,
        "project_alias": binding_config.PROJECT_ALIAS,
        "project_binding": binding_config.PROJECT_BINDING,
        "environment": binding_config.ENVIRONMENT,
        "provider_mode": binding_config.PROVIDER_MODE,
        "qualification_receipt_sha256": receipt_hash,
        "qualified_environment_manifest_sha256": manifest_hash,
        "account_snapshot_sha256": snapshot_hash,
        "project_ref_sha256": project_hash,
        "source_revision": source_revision,
        "issuer_sha256": _sha(issuer),
        "audience": audience,
        "allowed_role": role,
        "stock_claims_profile": True,
    }

    key, jwk = _key_and_jwk()

    class JwksSource:
        def __init__(self, configured_issuer):
            assert configured_issuer == issuer

        def __call__(self):
            return {"keys": [jwk]}

    monkeypatch.setattr(compose_module, "SupabaseJwksSource", JwksSource)
    return issuer, audience, role, binding, key


def _token(key, issuer, audience, role, *, amr=None, **overrides):
    issued = int(T0.timestamp())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": SUBJECT,
        "iat": issued,
        "exp": issued + 3600,
        "role": role,
        "aal": "aal1",
        "session_id": SESSION,
        "is_anonymous": False,
        "amr": [{"method": "password", "timestamp": issued - 10}] if amr is None else amr,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "staging-kid"})


def test_real_path_shape_composes_verifier_and_identity_service_without_identifier_leak(monkeypatch):
    issuer, audience, role, binding, key = _world(monkeypatch)
    credential = _token(key, issuer, audience, role)
    clock = FakeClock(T0 + timedelta(seconds=30))

    receipt = conformance.run_conformance(
        credential=credential,
        issuer=issuer,
        binding=binding,
        princess_commit=COMMIT,
        clock=clock,
    )

    assert receipt["result"] == "PASS"
    assert receipt["jwks_fetch_observed"] is True
    assert receipt["credential_verified"] is True
    assert receipt["identity_service_authenticated"] is True
    assert receipt["stable_principal_mapping"] is True
    assert receipt["principal_kind"] == "ACCOUNT"
    assert receipt["provider_cleanup_required"] is True
    assert receipt["provider_cleanup_performed_by_tool"] is False

    rendered_receipt = json.dumps(receipt, sort_keys=True)
    safe_index = conformance.render_safe_index(
        receipt,
        receipt_sha256="5" * 64,
        protected_evidence_ref="operator-local:staging-conformance-test",
    )
    for secret in (credential, issuer, SUBJECT, SESSION, "prn_000001"):
        assert secret not in rendered_receipt
        assert secret not in safe_index


def test_missing_usable_amr_freshness_cannot_manufacture_pass(monkeypatch):
    issuer, audience, role, binding, key = _world(monkeypatch)
    credential = _token(
        key,
        issuer,
        audience,
        role,
        amr=[{"method": "token_refresh", "timestamp": int(T0.timestamp()) - 10}],
    )

    with pytest.raises(conformance.ConformanceError, match="authentication_freshness_not_proven"):
        conformance.run_conformance(
            credential=credential,
            issuer=issuer,
            binding=binding,
            princess_commit=COMMIT,
            clock=FakeClock(T0 + timedelta(seconds=30)),
        )


def test_binding_drift_is_rejected_by_actual_composition_seam(monkeypatch):
    issuer, audience, role, binding, key = _world(monkeypatch)
    credential = _token(key, issuer, audience, role)
    binding["audience"] = "forged-but-plausible"

    with pytest.raises(InvalidInput) as err:
        conformance.run_conformance(
            credential=credential,
            issuer=issuer,
            binding=binding,
            princess_commit=COMMIT,
            clock=FakeClock(T0 + timedelta(seconds=30)),
        )
    assert err.value.code == "identity_runtime_binding_mismatch"


def test_receipt_schema_rejects_extra_fields_and_false_witnesses(monkeypatch):
    issuer, audience, role, binding, key = _world(monkeypatch)
    receipt = conformance.run_conformance(
        credential=_token(key, issuer, audience, role),
        issuer=issuer,
        binding=binding,
        princess_commit=COMMIT,
        clock=FakeClock(T0 + timedelta(seconds=30)),
    )

    extra = dict(receipt)
    extra["subject"] = SUBJECT
    with pytest.raises(conformance.ConformanceError, match="conformance_receipt_shape"):
        conformance.validate_conformance_receipt(extra)

    false = dict(receipt)
    false["stable_principal_mapping"] = False
    with pytest.raises(conformance.ConformanceError, match="conformance_receipt_stable_principal_mapping"):
        conformance.validate_conformance_receipt(false)


def test_protected_material_cannot_live_inside_checkout(tmp_path):
    with pytest.raises(conformance.ConformanceError, match="access_token_inside_repository"):
        conformance._protected_path(ROOT / "README.md", "access_token", must_exist=True)

    external = tmp_path / "receipt.json"
    assert conformance._protected_path(external, "protected_receipt", must_exist=False) == external.resolve()


def test_protected_material_requires_absolute_paths(monkeypatch, capsys):
    monkeypatch.setenv("PRINCESS_SUPABASE_STAGING_CONFORMANCE", "1")
    rc = conformance.main([
        "--qualification-receipt-file", "receipt.json",
        "--issuer-file", "issuer.txt",
        "--access-token-file", "access.jwt",
        "--receipt-output", "out.json",
        "--safe-index-output", str(conformance.SAFE_INDEX_PATH),
        "--protected-evidence-ref", "operator-local:test",
    ])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "FAIL: qualification_receipt_path_must_be_absolute"


def test_cli_requires_explicit_opt_in_before_touching_inputs(monkeypatch, capsys):
    monkeypatch.delenv("PRINCESS_SUPABASE_STAGING_CONFORMANCE", raising=False)
    rc = conformance.main([
        "--qualification-receipt-file", "/does/not/exist",
        "--issuer-file", "/does/not/exist",
        "--access-token-file", "/does/not/exist",
        "--receipt-output", "/does/not/exist/out.json",
        "--safe-index-output", str(conformance.SAFE_INDEX_PATH),
        "--protected-evidence-ref", "operator-local:test",
    ])
    assert rc == 2
    assert "explicit PRINCESS_SUPABASE_STAGING_CONFORMANCE=1 gate required" in capsys.readouterr().out


def test_safe_index_output_is_one_canonical_git_path(tmp_path):
    with pytest.raises(conformance.ConformanceError, match="safe_index_path_not_canonical"):
        conformance._safe_index_path(tmp_path / "looks-safe.md")


def test_unexpected_failure_never_echoes_protected_material(monkeypatch, tmp_path, capsys):
    qualification = tmp_path / "qualification.json"
    issuer = tmp_path / "issuer.txt"
    credential = tmp_path / "access.jwt"
    receipt = tmp_path / "receipt.json"
    qualification.write_text("{}", encoding="utf-8")
    issuer.write_text("https://protected-project.supabase.co/auth/v1", encoding="utf-8")
    credential.write_text("super-secret-access-token", encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise RuntimeError("super-secret-access-token https://protected-project.supabase.co")

    monkeypatch.setenv("PRINCESS_SUPABASE_STAGING_CONFORMANCE", "1")
    monkeypatch.setattr(conformance, "build_binding", explode)
    rc = conformance.main([
        "--qualification-receipt-file", str(qualification),
        "--issuer-file", str(issuer),
        "--access-token-file", str(credential),
        "--receipt-output", str(receipt),
        "--safe-index-output", str(conformance.SAFE_INDEX_PATH),
        "--protected-evidence-ref", "operator-local:test",
    ])
    rendered = capsys.readouterr().out
    assert rc == 1
    assert rendered.strip() == "FAIL: conformance_unexpected_failure"
    assert "super-secret-access-token" not in rendered
    assert "protected-project" not in rendered


def test_current_staging_manifest_still_matches_qualified_hash():
    digest = hashlib.sha256((ROOT / "infra" / "environments" / "staging.json").read_bytes()).hexdigest()
    assert digest == binding_config.QUALIFIED_ENVIRONMENT_MANIFEST_SHA256
