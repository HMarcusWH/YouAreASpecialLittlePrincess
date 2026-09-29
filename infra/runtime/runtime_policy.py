"""Provider-neutral runtime executable policy for T24 deployment artifacts.

This module deliberately performs no network I/O.  It answers a narrower
question than the environment manifest: can the current code actually compose
this role with the declared provider modes?
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from princess_app.config import RuntimeConfig, load_runtime_config
from princess_app.ports.base import Environment, InvalidInput, ProviderMode, Unsupported

ROOT = Path(__file__).resolve().parents[2]
EXECUTABLE_COMPONENTS = frozenset({
    "api", "analysis_worker", "premium_worker", "export_worker",
    "notification_worker", "migrations",
})
FAKE_PROVIDER_REQUIREMENTS: Mapping[str, tuple[str, ...]] = {
    "api": ("IdentityProvider", "ObjectStore", "PaymentProvider", "AbuseChallengeProvider"),
    "analysis_worker": ("ObjectStore",),
    "premium_worker": ("PremiumModelProvider",),
    "export_worker": ("ObjectStore",),
    "notification_worker": ("TransactionalMailer", "PushProvider"),
    "migrations": (),
}


def preflight(env: Mapping[str, str], root: Path = ROOT) -> RuntimeConfig:
    """Validate secrets plus the composition capabilities implemented today."""
    config = load_runtime_config(env, root)
    component = config.component
    if component not in EXECUTABLE_COMPONENTS:
        raise InvalidInput("component_not_runtime_executable", detail=component)

    for port in FAKE_PROVIDER_REQUIREMENTS[component]:
        if config.provider_mode(port) is not ProviderMode.FAKE:
            raise Unsupported("runtime_provider_not_configured", detail=f"{component}:{port}")

    # T26 is intentionally runtime-inactive; only local/test may exercise the
    # fake Premium model until the downstream owner/provider gates are cleared.
    if component == "premium_worker" and config.environment not in (Environment.LOCAL, Environment.TEST):
        raise Unsupported("premium_runtime_not_approved")

    if component == "export_worker" and not (root / "apps" / "render" / "dist" / "render.mjs").is_file():
        raise InvalidInput("renderer_bundle_missing")

    return config
