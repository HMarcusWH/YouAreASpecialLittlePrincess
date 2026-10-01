"""Environment manifests and startup configuration (T28).

Non-secret composition lives in reviewed JSON manifests under
``infra/environments/<environment>.json``: provider mode per connector port,
the database name, kill switches, and for each deployable component the
secret *names* and egress destinations it may receive. Secret values arrive
only as process environment variables at startup.

Startup fails closed when:

* the environment or component is unknown;
* a provider mode is not allowed in the environment (fakes never in
  production, live providers never in local/test/preview);
* a component is granted a secret or egress destination outside the reviewed
  matrix (for example a model key on the analysis worker);
* a required secret is missing, a production secret looks like a test/fake
  key, or a non-production secret looks like a live key;
* the database URL does not name this environment's database (a preview can
  never point at the production database).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .ports import PORT_NAMES
from .ports.base import Environment, InvalidInput, ProviderMode, check_mode_allowed

MANIFEST_VERSION = 1
SERVER_PORTS = tuple(p for p in PORT_NAMES if p != "NativePurchaseClient")

# Secret name -> category. Only names are reviewed here; values never are.
SECRET_CATEGORIES: Mapping[str, str] = {
    "PRINCESS_DATABASE_URL": "database",
    "PRINCESS_MIGRATION_DATABASE_URL": "database_migration",
    "PRINCESS_SESSION_SECRET": "session",
    "PRINCESS_IDENTITY_AUDIENCE": "identity_verification",
    "PRINCESS_STORAGE_SIGNING_KEY": "storage_signing",
    "PRINCESS_STORAGE_READ_KEY": "storage_read",
    "PRINCESS_MODEL_API_KEY": "model",
    "PRINCESS_STRIPE_SECRET_KEY": "payment_server",
    "PRINCESS_STRIPE_WEBHOOK_SECRET": "payment_webhook",
    "PRINCESS_APPLE_SERVER_KEY": "payment_server",
    "PRINCESS_GOOGLE_SERVICE_ACCOUNT": "payment_server",
    "PRINCESS_MAIL_API_KEY": "mail",
    "PRINCESS_PUSH_APNS_KEY": "push",
    "PRINCESS_PUSH_FCM_KEY": "push",
    "PRINCESS_CHALLENGE_SECRET": "abuse",
    "PRINCESS_TELEMETRY_TOKEN": "telemetry",
}

# Evidence-bound provider-profile inputs are protected process configuration,
# but deliberately not added to environment manifests: the already-qualified
# staging identity receipt is bound to the current manifest SHA-256.
PROTECTED_CONFIG_NAMES = frozenset({
    "PRINCESS_IDENTITY_ISSUER",
    "PRINCESS_IDENTITY_BINDING",
})

# Component -> secret categories it may hold (doc 15 secret/egress matrix).
COMPONENT_SECRET_CATEGORIES: Mapping[str, frozenset[str]] = {
    "api": frozenset({"database", "session", "identity_verification", "storage_signing", "payment_server",
                      "payment_webhook", "abuse", "telemetry"}),
    "web_server": frozenset({"session", "telemetry"}),
    "analysis_worker": frozenset({"database", "storage_read", "telemetry"}),
    "premium_worker": frozenset({"database", "storage_read", "model", "telemetry"}),
    "render_worker": frozenset(),
    # Claims export jobs, derives the authorized projection and stores the
    # bytes; spawns the render_worker sandbox, which gets only the projection.
    "export_worker": frozenset({"database", "storage_read", "telemetry"}),
    "reference_worker": frozenset(),
    "notification_worker": frozenset({"database", "mail", "push", "telemetry"}),
    "migrations": frozenset({"database_migration"}),
    "web_public": frozenset(),
    "native_public": frozenset(),
}
COMPONENT_EGRESS: Mapping[str, frozenset[str]] = {
    "api": frozenset({"database", "object_store", "identity_provider", "payment_providers", "abuse_provider",
                      "telemetry"}),
    "web_server": frozenset({"api", "telemetry"}),
    "analysis_worker": frozenset({"database", "object_store", "telemetry"}),
    "premium_worker": frozenset({"database", "object_store", "model_provider", "telemetry"}),
    "render_worker": frozenset(),
    "export_worker": frozenset({"database", "object_store", "telemetry"}),
    "reference_worker": frozenset(),
    "notification_worker": frozenset({"database", "mail_provider", "push_provider", "telemetry"}),
    "migrations": frozenset({"database"}),
    "web_public": frozenset({"api"}),
    "native_public": frozenset({"api"}),
}
KILL_SWITCHES = ("premium_generation", "commerce", "uploads", "sharing", "notifications")
_DB_NAME = re.compile(r"^princess_(local|test|preview(?:_[a-z0-9]{1,24})?|staging|production)$")
_LIVE_LOOKING = re.compile(r"(?i)(^sk_live_|^rk_live_|_live_|\blive\b)")
_TEST_LOOKING = re.compile(r"(?i)(^sk_test_|^rk_test_|_test_|\btest\b|fake|dummy|changeme|example)")


def _fail(code: str, detail: str | None = None) -> InvalidInput:
    return InvalidInput(code, detail=detail)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise _fail("duplicate_manifest_key", key[:64])
        out[key] = value
    return out


@dataclass(frozen=True)
class ComponentPolicy:
    secrets: frozenset[str]
    egress: frozenset[str]


@dataclass(frozen=True)
class EnvironmentManifest:
    environment: Environment
    database_name: str
    providers: Mapping[str, ProviderMode]
    kill_switches: Mapping[str, bool]
    components: Mapping[str, ComponentPolicy]


def parse_manifest(data: Any, *, expected: Environment | None = None) -> EnvironmentManifest:
    if not isinstance(data, dict) or set(data) != {"version", "environment", "database", "providers",
                                                   "kill_switches", "components"}:
        raise _fail("manifest_shape")
    if data["version"] != MANIFEST_VERSION or type(data["version"]) is not int:
        raise _fail("manifest_version")
    environment = Environment.parse(data["environment"])
    if expected is not None and environment is not expected:
        raise _fail("manifest_environment_mismatch")
    database = data["database"]
    if not isinstance(database, dict) or set(database) != {"name"} or not isinstance(database["name"], str):
        raise _fail("manifest_database")
    _check_database_name(environment, database["name"])

    providers = data["providers"]
    if not isinstance(providers, dict) or set(providers) != set(SERVER_PORTS):
        raise _fail("manifest_providers_incomplete")
    modes: dict[str, ProviderMode] = {}
    for port, raw in providers.items():
        try:
            mode = ProviderMode(raw)
        except ValueError:
            raise _fail("unknown_provider_mode", port) from None
        check_mode_allowed(environment, mode)
        modes[port] = mode

    switches = data["kill_switches"]
    if (not isinstance(switches, dict) or set(switches) != set(KILL_SWITCHES)
            or not all(type(v) is bool for v in switches.values())):
        raise _fail("manifest_kill_switches")

    components = data["components"]
    if not isinstance(components, dict) or set(components) != set(COMPONENT_SECRET_CATEGORIES):
        raise _fail("manifest_components_incomplete")
    policies = {}
    for name, policy in components.items():
        if name not in COMPONENT_SECRET_CATEGORIES:
            raise _fail("unknown_component", str(name)[:64])
        if not isinstance(policy, dict) or set(policy) != {"secrets", "egress"}:
            raise _fail("component_policy_shape", name)
        secrets, egress = policy["secrets"], policy["egress"]
        if not isinstance(secrets, list) or not isinstance(egress, list):
            raise _fail("component_policy_shape", name)
        for secret in secrets:
            category = SECRET_CATEGORIES.get(secret)
            if category is None:
                raise _fail("unknown_secret_name", name)
            if category not in COMPONENT_SECRET_CATEGORIES[name]:
                raise _fail("secret_not_allowed_for_component", f"{name}:{secret}")
        for destination in egress:
            if destination not in COMPONENT_EGRESS[name]:
                raise _fail("egress_not_allowed_for_component", f"{name}:{destination}"[:120])
        if len(set(secrets)) != len(secrets) or len(set(egress)) != len(egress):
            raise _fail("duplicate_component_entry", name)
        policies[name] = ComponentPolicy(frozenset(secrets), frozenset(egress))
    # Read-only views: validated composition cannot be edited after startup.
    return EnvironmentManifest(environment, database["name"], MappingProxyType(modes),
                               MappingProxyType(dict(switches)), MappingProxyType(policies))


def _check_database_name(environment: Environment, name: str) -> None:
    match = _DB_NAME.match(name)
    if not match:
        raise _fail("invalid_database_name")
    declared = match.group(1).split("_", 1)[0]
    if declared != environment.value:
        raise _fail("database_belongs_to_another_environment")


def load_manifest(root: Path, environment: Environment) -> EnvironmentManifest:
    path = root / "infra" / "environments" / f"{environment.value}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        if isinstance(exc, InvalidInput):
            raise
        raise _fail("manifest_unreadable", environment.value) from None
    return parse_manifest(data, expected=environment)


class _Secret(str):
    """A string whose repr never shows the value."""

    def __repr__(self) -> str:
        return "<secret>"


@dataclass(frozen=True)
class RuntimeConfig:
    environment: Environment
    component: str
    manifest: EnvironmentManifest
    secrets: Mapping[str, str] = field(repr=False)
    protected: Mapping[str, str] = field(repr=False)

    def secret(self, name: str) -> str:
        if name not in self.manifest.components[self.component].secrets:
            raise _fail("secret_not_granted", name)
        return self.secrets[name]

    def protected_value(self, name: str) -> str:
        if name not in PROTECTED_CONFIG_NAMES or name not in self.protected:
            raise _fail("protected_config_not_granted", name)
        return self.protected[name]

    def provider_mode(self, port: str) -> ProviderMode:
        return self.manifest.providers[port]

    def enabled(self, switch: str) -> bool:
        return self.manifest.kill_switches[switch]


def load_runtime_config(env: Mapping[str, str], root: Path) -> RuntimeConfig:
    """Compose configuration for one process from its environment variables."""
    environment = Environment.parse(env.get("PRINCESS_ENV"))
    component = env.get("PRINCESS_COMPONENT")
    manifest = load_manifest(root, environment)
    if component not in manifest.components:
        raise _fail("component_not_in_manifest", str(component)[:64])
    policy = manifest.components[component]
    protected_values = {name: env.get(name) for name in PROTECTED_CONFIG_NAMES if env.get(name)}
    staging_identity_profile = (
        component == "api"
        and environment is Environment.STAGING
        and manifest.providers["IdentityProvider"] is ProviderMode.SANDBOX
    )
    if staging_identity_profile:
        missing = sorted(name for name in PROTECTED_CONFIG_NAMES if not env.get(name))
        if missing:
            raise _fail("missing_protected_config", missing[0])
    elif protected_values:
        raise _fail("protected_config_not_allowed", sorted(protected_values)[0])

    stray = sorted(name for name in SECRET_CATEGORIES if env.get(name) and name not in policy.secrets)
    if stray:
        # A known secret the component is not granted must not even be present.
        raise _fail("ungranted_secret_present", stray[0])
    secrets: dict[str, str] = {}
    for name in sorted(policy.secrets):
        value = env.get(name)
        if not value:
            raise _fail("missing_secret", name)
        if environment is Environment.PRODUCTION and _TEST_LOOKING.search(value):
            raise _fail("test_credential_in_production", name)
        if environment is not Environment.PRODUCTION and _LIVE_LOOKING.search(value):
            raise _fail("live_credential_outside_production", name)
        secrets[name] = _Secret(value)
    for name in ("PRINCESS_DATABASE_URL", "PRINCESS_MIGRATION_DATABASE_URL"):
        if name in secrets:
            parts = urlsplit(secrets[name])
            if parts.scheme not in ("postgresql", "postgresql+psycopg") or not parts.hostname:
                raise _fail("database_url_not_postgresql", name)
            if parts.path.lstrip("/") != manifest.database_name:
                raise _fail("database_url_names_another_database", name)
    protected = {name: _Secret(value) for name, value in protected_values.items() if value is not None}
    return RuntimeConfig(
        environment,
        component,
        manifest,
        MappingProxyType(secrets),
        MappingProxyType(protected),
    )
