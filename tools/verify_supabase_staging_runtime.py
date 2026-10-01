#!/usr/bin/env python3
"""Run one privacy-safe real conformance check against the qualified Supabase staging verifier.

This operator-only harness verifies one already-issued disposable staging access
JWT. It does not sign users in, refresh credentials, use a Supabase API key,
touch PostgreSQL, or activate application login/production identity.

Protected inputs and the full operational receipt must stay outside the Git
checkout. Only the redacted evidence index may be written into the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
API = ROOT / "apps" / "api"
for path in (SRC, TOOLS, API):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import princess_app.config_supabase as binding_config  # noqa: E402
from build_supabase_staging_runtime_binding import BindingError, build_binding  # noqa: E402
from princess_api.compose import compose_identity_provider  # noqa: E402
from princess_app.adapters.fakes import SequentialIds  # noqa: E402
from princess_app.adapters.supabase import SupabaseIdentityProvider  # noqa: E402
from princess_app.application.identity import IdentityService, InMemoryIdentityStore  # noqa: E402
from princess_app.config import RuntimeConfig, load_manifest  # noqa: E402
from princess_app.ports import identity as identity_port  # noqa: E402
from princess_app.ports.base import (  # noqa: E402
    CallContext,
    Environment,
    PortError,
    ProviderMode,
    SystemClock,
)

VERSION = "supabase-staging-runtime-conformance/1"
SAFE_INDEX_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_RUNTIME_CONFORMANCE.md"
ACCOUNT_SNAPSHOT_PATH = ROOT / "docs" / "ci" / "T17_SUPABASE_STAGING_ACCOUNT_SNAPSHOT.json"
MAX_QUALIFICATION_RECEIPT_BYTES = 1024 * 1024
MAX_ACCESS_TOKEN_BYTES = 64 * 1024
MAX_ISSUER_BYTES = 2048
COMMIT = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVIDENCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

RECEIPT_KEYS = frozenset({
    "version",
    "provider",
    "project_alias",
    "environment",
    "provider_mode",
    "capability",
    "checked_date",
    "princess_commit",
    "qualification_receipt_sha256",
    "runtime_binding_sha256",
    "account_snapshot_sha256",
    "qualified_environment_manifest_sha256",
    "project_ref_sha256",
    "issuer_sha256",
    "audience_sha256",
    "role_sha256",
    "source_revision",
    "jwks_fetch_observed",
    "credential_verified",
    "identity_service_authenticated",
    "stable_principal_mapping",
    "principal_kind",
    "auth_time_present",
    "session_id_present",
    "credential_unexpired",
    "provider_cleanup_required",
    "provider_cleanup_performed_by_tool",
    "application_login",
    "production_activation",
    "global_gate_closure",
    "result",
})


class ConformanceError(ValueError):
    """Static, non-sensitive failure code for the operator harness."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _protected_path(path: Path, name: str, *, must_exist: bool) -> Path:
    if not path.is_absolute():
        raise ConformanceError(f"{name}_path_must_be_absolute")
    resolved = path.resolve()
    if _inside_repo(resolved):
        raise ConformanceError(f"{name}_inside_repository")
    if must_exist and not resolved.is_file():
        raise ConformanceError(f"{name}_unreadable")
    if not must_exist and not resolved.parent.is_dir():
        raise ConformanceError(f"{name}_parent_missing")
    return resolved


def _safe_index_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != SAFE_INDEX_PATH.resolve():
        raise ConformanceError("safe_index_path_not_canonical")
    return resolved


def _read_bytes(path: Path, *, name: str, max_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise ConformanceError(f"{name}_size")
        value = path.read_bytes()
    except OSError:
        raise ConformanceError(f"{name}_unreadable") from None
    if not value or len(value) > max_bytes:
        raise ConformanceError(f"{name}_size")
    return value


def _read_text(path: Path, *, name: str, max_bytes: int) -> str:
    raw = _read_bytes(path, name=name, max_bytes=max_bytes)
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ConformanceError(f"{name}_unreadable") from None
    if not value or "\x00" in value:
        raise ConformanceError(f"{name}_unreadable")
    return value


def _load_account_snapshot() -> dict[str, Any]:
    try:
        data = json.loads(ACCOUNT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConformanceError("account_snapshot_unreadable") from None
    if not isinstance(data, dict):
        raise ConformanceError("account_snapshot_unreadable")
    return data


def _repo_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ConformanceError("princess_commit_unavailable") from None
    commit = result.stdout.strip().lower()
    if not COMMIT.fullmatch(commit):
        raise ConformanceError("princess_commit_invalid")
    if status.stdout.strip():
        raise ConformanceError("princess_checkout_dirty")
    return commit


def identity_only_runtime_config(*, issuer: str, binding: Mapping[str, Any]) -> RuntimeConfig:
    """Build the narrow config consumed by the already-merged identity composition seam.

    This intentionally does not call `load_runtime_config`: that validates a
    complete staging API process and would require unrelated database/storage
    credentials. The reviewed staging manifest remains the provider-mode and
    secret-grant authority, while `compose_identity_provider` revalidates the
    current manifest hash against the qualified receipt-derived binding.
    """
    manifest = load_manifest(ROOT, Environment.STAGING)
    if manifest.providers["IdentityProvider"] is not ProviderMode.SANDBOX:
        raise ConformanceError("identity_mode_not_staging_sandbox")
    audience = binding.get("audience")
    if not isinstance(audience, str) or not audience:
        raise ConformanceError("runtime_binding_audience_missing")
    binding_json = json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return RuntimeConfig(
        environment=Environment.STAGING,
        component="api",
        manifest=manifest,
        secrets=MappingProxyType({"PRINCESS_IDENTITY_AUDIENCE": audience}),
        protected=MappingProxyType({
            "PRINCESS_IDENTITY_ISSUER": issuer,
            "PRINCESS_IDENTITY_BINDING": binding_json,
        }),
    )


def validate_conformance_receipt(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != set(RECEIPT_KEYS):
        raise ConformanceError("conformance_receipt_shape")
    expected = {
        "version": VERSION,
        "provider": "supabase-auth",
        "project_alias": binding_config.PROJECT_ALIAS,
        "environment": "staging",
        "provider_mode": "sandbox",
        "capability": identity_port.VERIFY_CREDENTIAL,
        "principal_kind": "ACCOUNT",
        "provider_cleanup_required": True,
        "provider_cleanup_performed_by_tool": False,
        "application_login": False,
        "production_activation": False,
        "global_gate_closure": False,
        "result": "PASS",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ConformanceError(f"conformance_receipt_{key}")

    if not isinstance(receipt.get("checked_date"), str) or not DATE.fullmatch(receipt["checked_date"]):
        raise ConformanceError("conformance_receipt_checked_date")
    if not isinstance(receipt.get("princess_commit"), str) or not COMMIT.fullmatch(receipt["princess_commit"]):
        raise ConformanceError("conformance_receipt_princess_commit")
    if receipt.get("source_revision") != binding_config.SOURCE_REVISION:
        raise ConformanceError("conformance_receipt_source_revision")

    for name in (
        "qualification_receipt_sha256",
        "runtime_binding_sha256",
        "account_snapshot_sha256",
        "qualified_environment_manifest_sha256",
        "project_ref_sha256",
        "issuer_sha256",
        "audience_sha256",
        "role_sha256",
    ):
        value = receipt.get(name)
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise ConformanceError(f"conformance_receipt_{name}")

    if receipt["qualification_receipt_sha256"] != binding_config.QUALIFICATION_RECEIPT_SHA256:
        raise ConformanceError("conformance_receipt_qualification_anchor")
    if receipt["account_snapshot_sha256"] != binding_config.ACCOUNT_SNAPSHOT_SHA256:
        raise ConformanceError("conformance_receipt_account_anchor")
    if receipt["qualified_environment_manifest_sha256"] != binding_config.QUALIFIED_ENVIRONMENT_MANIFEST_SHA256:
        raise ConformanceError("conformance_receipt_manifest_anchor")
    if receipt["project_ref_sha256"] != binding_config.PROJECT_REF_SHA256:
        raise ConformanceError("conformance_receipt_project_anchor")
    if receipt["issuer_sha256"] != binding_config.QUALIFIED_ISSUER_SHA256:
        raise ConformanceError("conformance_receipt_issuer_anchor")
    if receipt["audience_sha256"] != binding_config.QUALIFIED_AUDIENCE_SHA256:
        raise ConformanceError("conformance_receipt_audience_anchor")
    if receipt["role_sha256"] != binding_config.QUALIFIED_ROLE_SHA256:
        raise ConformanceError("conformance_receipt_role_anchor")

    for name in (
        "jwks_fetch_observed",
        "credential_verified",
        "identity_service_authenticated",
        "stable_principal_mapping",
        "auth_time_present",
        "session_id_present",
        "credential_unexpired",
    ):
        if receipt.get(name) is not True:
            raise ConformanceError(f"conformance_receipt_{name}")


def run_conformance(
    *,
    credential: str,
    issuer: str,
    binding: Mapping[str, Any],
    princess_commit: str,
    clock: Any | None = None,
) -> dict[str, Any]:
    """Exercise the actual #56 composition seam and IdentityService with one credential."""
    if not isinstance(credential, str) or not credential:
        raise ConformanceError("access_token_unreadable")
    if not isinstance(issuer, str) or not issuer:
        raise ConformanceError("issuer_unreadable")
    if not COMMIT.fullmatch(princess_commit):
        raise ConformanceError("princess_commit_invalid")

    clock = clock or SystemClock()
    config = identity_only_runtime_config(issuer=issuer, binding=binding)
    provider = compose_identity_provider(config, clock)
    if not isinstance(provider, SupabaseIdentityProvider):
        raise ConformanceError("unexpected_identity_provider")
    if provider.profile.mode is not ProviderMode.SANDBOX:
        raise ConformanceError("unexpected_identity_provider_mode")
    if provider.profile.capabilities != frozenset({identity_port.VERIFY_CREDENTIAL}):
        raise ConformanceError("unexpected_identity_capabilities")

    ctx = CallContext(
        correlation_id="t17-staging-conformance",
        environment=Environment.STAGING,
        deadline=clock.now() + timedelta(seconds=30),
    )

    verified = provider.verify_credential(credential, ctx)
    service = IdentityService(provider, InMemoryIdentityStore(), clock, SequentialIds())
    first = service.authenticate(credential, ctx)
    second = service.authenticate(credential, ctx)

    if verified.auth_time is None:
        raise ConformanceError("authentication_freshness_not_proven")
    if verified.session_id is None:
        raise ConformanceError("session_id_not_proven")
    if first.kind != "ACCOUNT" or second.kind != "ACCOUNT":
        raise ConformanceError("account_principal_not_created")
    if first.principal_id != second.principal_id:
        raise ConformanceError("principal_mapping_not_stable")
    if verified.expires_at <= clock.now():
        raise ConformanceError("credential_not_live")
    if provider.refresh_count < 1:
        raise ConformanceError("jwks_fetch_not_observed")

    audience = binding.get("audience")
    role = binding.get("allowed_role")
    if not isinstance(audience, str) or not isinstance(role, str):
        raise ConformanceError("runtime_binding_profile_missing")

    receipt = {
        "version": VERSION,
        "provider": "supabase-auth",
        "project_alias": binding_config.PROJECT_ALIAS,
        "environment": "staging",
        "provider_mode": "sandbox",
        "capability": identity_port.VERIFY_CREDENTIAL,
        "checked_date": clock.now().date().isoformat(),
        "princess_commit": princess_commit,
        "qualification_receipt_sha256": binding["qualification_receipt_sha256"],
        "runtime_binding_sha256": _sha256_bytes(_canonical_json_bytes(dict(binding))),
        "account_snapshot_sha256": binding["account_snapshot_sha256"],
        "qualified_environment_manifest_sha256": binding["qualified_environment_manifest_sha256"],
        "project_ref_sha256": binding["project_ref_sha256"],
        "issuer_sha256": binding["issuer_sha256"],
        "audience_sha256": _sha256_text(audience),
        "role_sha256": _sha256_text(role),
        "source_revision": binding["source_revision"],
        "jwks_fetch_observed": True,
        "credential_verified": True,
        "identity_service_authenticated": True,
        "stable_principal_mapping": True,
        "principal_kind": "ACCOUNT",
        "auth_time_present": True,
        "session_id_present": True,
        "credential_unexpired": True,
        "provider_cleanup_required": True,
        "provider_cleanup_performed_by_tool": False,
        "application_login": False,
        "production_activation": False,
        "global_gate_closure": False,
        "result": "PASS",
    }
    validate_conformance_receipt(receipt)
    return receipt


def render_safe_index(
    receipt: Mapping[str, Any],
    *,
    receipt_sha256: str,
    protected_evidence_ref: str,
) -> str:
    validate_conformance_receipt(receipt)
    if not HEX64.fullmatch(receipt_sha256):
        raise ConformanceError("conformance_receipt_digest_invalid")
    if not EVIDENCE_REF.fullmatch(protected_evidence_ref):
        raise ConformanceError("protected_evidence_ref_invalid")

    return f"""# T17 Supabase staging runtime conformance

**Status: PASS — the qualified staging/sandbox verifier accepted a real disposable credential through the actual Princess composition seam. Provider cleanup remains operator-owned; application login and production/live remain disabled.**

This is the Git-safe index for the protected operational receipt produced by
`tools/verify_supabase_staging_runtime.py`. The access JWT, provider subject/session,
Princess principal ID, raw issuer/project reference, JWKS document and any provider
credential remain outside Git.

## Evidence record

```text
provider:                              {receipt["provider"]}
project_alias:                         {receipt["project_alias"]}
receipt_version:                       {receipt["version"]}
environment:                           {receipt["environment"]}
provider_mode:                         {receipt["provider_mode"]}
capability:                            {receipt["capability"]}
checked_date:                          {receipt["checked_date"]}
princess_commit:                       {receipt["princess_commit"]}
receipt_sha256:                        {receipt_sha256}
protected_evidence_ref:                {protected_evidence_ref}

qualification_receipt_sha256:          {receipt["qualification_receipt_sha256"]}
runtime_binding_sha256:                {receipt["runtime_binding_sha256"]}
account_snapshot_sha256:               {receipt["account_snapshot_sha256"]}
qualified_environment_manifest_sha256: {receipt["qualified_environment_manifest_sha256"]}
project_ref_sha256:                    {receipt["project_ref_sha256"]}
issuer_sha256:                         {receipt["issuer_sha256"]}
audience_sha256:                       {receipt["audience_sha256"]}
role_sha256:                           {receipt["role_sha256"]}
source_revision:                       {receipt["source_revision"]}

jwks_fetch:                            PASS
credential_verified:                   PASS
identity_service_authenticated:        PASS
stable_principal_mapping:              PASS
principal_kind:                        ACCOUNT
auth_time_present:                     PASS
session_id_present:                    PASS
credential_unexpired:                  PASS

provider_cleanup_required:             true
provider_cleanup_performed_by_tool:    false
application_login:                     false
production_activation:                 false
global_gate_closure:                   false
result:                                PASS
```

## What this proves

The real disposable staging access JWT passed the exact
`compose_identity_provider -> SupabaseJwksSource -> SupabaseIdentityProvider -> IdentityService`
path. The provider used the reviewed `(staging, sandbox)` tuple and receipt-derived
profile binding. Repeat authentication converged on the same in-memory Princess
principal without using email as an account key.

This does **not** prove complete staging API startup, PostgreSQL composition,
ObjectStore/Payment/Abuse readiness, application-managed sign-in/refresh, provider
logout/deletion integration, or production/live identity.

## Protected material

Do not commit the operational receipt, access/refresh tokens, API keys, passwords,
provider subject/session identifiers, Princess principal ID, raw issuer/project
reference, raw JWKS, login URLs containing credentials, or private account data.

## Cleanup

The harness intentionally has no provider admin credential and does not revoke or
delete the disposable Supabase account. After a real run, the authorized operator
must globally revoke/sign out the disposable provider session and delete the
disposable Auth user using owner-authorized provider controls. Already-issued
access JWTs can remain cryptographically valid until expiry, so cleanup must not be
represented as instantaneous token invalidation. Retain only safe cleanup evidence.

## Scope non-claims

This PASS is staging/sandbox `VERIFY_CREDENTIAL` evidence only. It does not enable
application login, close `processor_retention_contracts` globally, approve a
production Supabase account, or qualify production/live identity.
"""


def _write_new(path: Path, content: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        raise ConformanceError("protected_receipt_already_exists") from None
    except OSError:
        raise ConformanceError("protected_receipt_write_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-receipt-file", type=Path, required=True)
    parser.add_argument("--issuer-file", type=Path, required=True)
    parser.add_argument("--access-token-file", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    parser.add_argument("--safe-index-output", type=Path, required=True)
    parser.add_argument("--protected-evidence-ref", required=True)
    args = parser.parse_args(argv)

    if os.environ.get("PRINCESS_SUPABASE_STAGING_CONFORMANCE") != "1":
        print("FAIL: explicit PRINCESS_SUPABASE_STAGING_CONFORMANCE=1 gate required")
        return 2

    try:
        qualification_path = _protected_path(
            args.qualification_receipt_file,
            "qualification_receipt",
            must_exist=True,
        )
        issuer_path = _protected_path(args.issuer_file, "issuer", must_exist=True)
        access_token_path = _protected_path(args.access_token_file, "access_token", must_exist=True)
        receipt_output = _protected_path(args.receipt_output, "protected_receipt", must_exist=False)
        safe_index_output = _safe_index_path(args.safe_index_output)
        if not EVIDENCE_REF.fullmatch(args.protected_evidence_ref):
            raise ConformanceError("protected_evidence_ref_invalid")

        qualification_bytes = _read_bytes(
            qualification_path,
            name="qualification_receipt",
            max_bytes=MAX_QUALIFICATION_RECEIPT_BYTES,
        )
        issuer = _read_text(issuer_path, name="issuer", max_bytes=MAX_ISSUER_BYTES)
        credential = _read_text(
            access_token_path,
            name="access_token",
            max_bytes=MAX_ACCESS_TOKEN_BYTES,
        )

        binding = build_binding(qualification_bytes, _load_account_snapshot())
        princess_commit = _repo_commit()
        receipt = run_conformance(
            credential=credential,
            issuer=issuer,
            binding=binding,
            princess_commit=princess_commit,
        )
        receipt_bytes = _pretty_json_bytes(receipt)
        receipt_sha256 = _sha256_bytes(receipt_bytes)
        safe_index = render_safe_index(
            receipt,
            receipt_sha256=receipt_sha256,
            protected_evidence_ref=args.protected_evidence_ref,
        )

        # Write protected evidence first. If the Git-safe index write fails, no
        # false PASS lands in Git; the protected receipt remains available for
        # an operator to reconcile with a fresh output path.
        _write_new(receipt_output, receipt_bytes)
        try:
            safe_index_output.write_text(safe_index, encoding="utf-8")
        except OSError:
            raise ConformanceError("safe_index_write_failed") from None

    except BindingError as exc:
        # BindingError strings are static codes emitted by the reviewed binding tool.
        print(f"FAIL: {exc}")
        return 1
    except PortError as exc:
        print(f"FAIL: {exc.code}")
        return 1
    except ConformanceError as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception:
        # Never forward unexpected provider/library text: it may contain
        # protected request material or filesystem details.
        print("FAIL: conformance_unexpected_failure")
        return 1

    print(f"PASS {VERSION} receipt_sha256={receipt_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
