"""Provider-neutral runtime executable policy for T24 deployment artifacts.

This module deliberately performs no network I/O.  It answers a narrower
question than the environment manifest: can the current code actually compose
this role with the declared provider modes?
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from princess_app.config import RuntimeConfig, load_runtime_config
from princess_app.config_supabase import parse_supabase_staging_runtime_binding
from princess_app.ports.base import Environment, InvalidInput, ProviderMode, Unsupported

ROOT = Path(__file__).resolve().parents[2]
EXECUTABLE_COMPONENTS = frozenset({
    "api", "analysis_worker", "premium_worker", "export_worker",
    "notification_worker", "migrations",
})
PROVIDER_REQUIREMENTS: Mapping[str, tuple[str, ...]] = {
    "api": ("IdentityProvider", "ObjectStore", "PaymentProvider", "AbuseChallengeProvider"),
    "analysis_worker": ("ObjectStore",),
    "premium_worker": ("PremiumModelProvider",),
    "export_worker": ("ObjectStore",),
    "notification_worker": ("TransactionalMailer", "PushProvider"),
    "migrations": (),
}


def _manifest_sha256(root: Path, environment: Environment) -> str:
    try:
        return hashlib.sha256(
            (root / "infra" / "environments" / f"{environment.value}.json").read_bytes()
        ).hexdigest()
    except OSError:
        raise InvalidInput("manifest_unreadable", detail=environment.value) from None


def _provider_supported(config: RuntimeConfig, port: str, root: Path) -> None:
    mode = config.provider_mode(port)
    if mode is ProviderMode.FAKE:
        return
    if (
        config.component == "api"
        and port == "IdentityProvider"
        and config.environment is Environment.STAGING
        and mode is ProviderMode.SANDBOX
    ):
        parse_supabase_staging_runtime_binding(
            config.protected_value("PRINCESS_IDENTITY_BINDING"),
            issuer=config.protected_value("PRINCESS_IDENTITY_ISSUER"),
            audience=config.secret("PRINCESS_IDENTITY_AUDIENCE"),
            current_manifest_sha256=_manifest_sha256(root, config.environment),
        )
        return
    raise Unsupported("runtime_provider_not_configured", detail=f"{config.component}:{port}")


def preflight(env: Mapping[str, str], root: Path = ROOT) -> RuntimeConfig:
    """Validate secrets plus the composition capabilities implemented today."""
    config = load_runtime_config(env, root)
    component = config.component
    if component not in EXECUTABLE_COMPONENTS:
        raise InvalidInput("component_not_runtime_executable", detail=component)

    for port in PROVIDER_REQUIREMENTS[component]:
        _provider_supported(config, port, root)

    # T26 is intentionally runtime-inactive; only local/test may exercise the
    # fake Premium model until the downstream owner/provider gates are cleared.
    if component == "premium_worker" and config.environment not in (Environment.LOCAL, Environment.TEST):
        raise Unsupported("premium_runtime_not_approved")

    if component == "export_worker" and not (root / "apps" / "render" / "dist" / "render.mjs").is_file():
        raise InvalidInput("renderer_bundle_missing")

    return config
