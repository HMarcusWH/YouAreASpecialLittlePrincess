"""T28 environment composition, secret/egress matrix and build-pin policy."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomli is in the reviewed 3.10 lock
    import tomli as tomllib

import pytest

from princess_app.config import load_manifest, load_runtime_config, parse_manifest
from princess_app.ports.base import Environment, InvalidInput

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SECRETS = {
    "PRINCESS_DATABASE_URL": "postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_local",
    "PRINCESS_SESSION_SECRET": "local-session-secret-0123456789",
    "PRINCESS_IDENTITY_AUDIENCE": "princess-local",
    "PRINCESS_STORAGE_SIGNING_KEY": "local-signing-key-0123456789",
}


def manifest(env: str) -> dict:
    return json.loads((ROOT / "infra" / "environments" / f"{env}.json").read_text())


def code(fn) -> str:
    with pytest.raises(InvalidInput) as err:
        fn()
    return err.value.code


@pytest.mark.parametrize("env", list(Environment))
def test_reviewed_manifests_are_valid(env):
    loaded = load_manifest(ROOT, env)
    assert loaded.environment is env
    assert loaded.database_name.startswith(f"princess_{env.value}")


@pytest.mark.parametrize("env,mode,expected", [
    ("production", "fake", "mode_not_allowed_in_environment"),
    ("production", "sandbox", "mode_not_allowed_in_environment"),
    ("preview", "live", "mode_not_allowed_in_environment"),
    ("local", "live", "mode_not_allowed_in_environment"),
    ("test", "teleport", "unknown_provider_mode"),
])
def test_provider_modes_are_bound_to_environment(env, mode, expected):
    data = manifest(env)
    data["providers"]["PaymentProvider"] = mode
    assert code(lambda: parse_manifest(data)) == expected


@pytest.mark.parametrize("component,secret", [
    ("analysis_worker", "PRINCESS_MODEL_API_KEY"),
    ("analysis_worker", "PRINCESS_STRIPE_SECRET_KEY"),
    ("render_worker", "PRINCESS_DATABASE_URL"),
    ("render_worker", "PRINCESS_MODEL_API_KEY"),
    ("web_public", "PRINCESS_SESSION_SECRET"),
    ("native_public", "PRINCESS_STRIPE_SECRET_KEY"),
    ("notification_worker", "PRINCESS_MODEL_API_KEY"),
    ("premium_worker", "PRINCESS_STRIPE_SECRET_KEY"),
])
def test_secret_matrix_rejects_forbidden_grants(component, secret):
    data = manifest("local")
    data["components"][component]["secrets"].append(secret)
    assert code(lambda: parse_manifest(data)) == "secret_not_allowed_for_component"


@pytest.mark.parametrize("component,destination", [
    ("analysis_worker", "model_provider"), ("analysis_worker", "public_internet"),
    ("render_worker", "database"), ("web_public", "database"),
])
def test_egress_matrix_rejects_forbidden_destinations(component, destination):
    data = manifest("local")
    data["components"][component]["egress"].append(destination)
    assert code(lambda: parse_manifest(data)) == "egress_not_allowed_for_component"


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d["database"].update(name="princess_production"), "database_belongs_to_another_environment"),
    (lambda d: d["database"].update(name="prod_db"), "invalid_database_name"),
    (lambda d: d["providers"].pop("ObjectStore"), "manifest_providers_incomplete"),
    (lambda d: d["kill_switches"].update(commerce="yes"), "manifest_kill_switches"),
    (lambda d: d["components"].update(mystery={"secrets": [], "egress": []}), "unknown_component"),
    (lambda d: d["components"]["api"]["secrets"].append("PRINCESS_UNREVIEWED"), "unknown_secret_name"),
    (lambda d: d.update(environment="staging"), "manifest_environment_mismatch"),
])
def test_manifest_shape_and_database_rules(mutate, expected):
    data = copy.deepcopy(manifest("preview"))
    mutate(data)
    assert code(lambda: parse_manifest(data, expected=Environment.PREVIEW)) == expected


def runtime(env: dict[str, str]):
    return load_runtime_config(env, ROOT)


def test_local_runtime_config_loads_and_hides_secret_values():
    config = runtime({"PRINCESS_ENV": "local", "PRINCESS_COMPONENT": "api", **LOCAL_SECRETS})
    assert config.provider_mode("ObjectStore").value == "fake"
    assert config.enabled("uploads") and not config.enabled("premium_generation")
    assert "local-session-secret" not in repr(config)
    assert repr(config.secret("PRINCESS_SESSION_SECRET")) == "<secret>"
    with pytest.raises(InvalidInput):
        config.secret("PRINCESS_MODEL_API_KEY")


@pytest.mark.parametrize("env,expected", [
    ({"PRINCESS_ENV": "prod", "PRINCESS_COMPONENT": "api"}, "unknown_environment"),
    ({"PRINCESS_COMPONENT": "api"}, "unknown_environment"),
    ({"PRINCESS_ENV": "local", "PRINCESS_COMPONENT": "shell"}, "component_not_in_manifest"),
    ({"PRINCESS_ENV": "local", "PRINCESS_COMPONENT": "api"}, "missing_secret"),
])
def test_runtime_rejects_unknown_or_incomplete_composition(env, expected):
    assert code(lambda: runtime(env)) == expected


def test_preview_cannot_point_at_the_production_database():
    env = {"PRINCESS_ENV": "preview", "PRINCESS_COMPONENT": "analysis_worker",
           "PRINCESS_DATABASE_URL": "postgresql://svc@db.internal/princess_production",
           "PRINCESS_STORAGE_READ_KEY": "preview-read-key-0123456789"}
    assert code(lambda: runtime(env)) == "database_url_names_another_database"


def test_production_refuses_test_keys_and_local_refuses_live_keys():
    prod = {"PRINCESS_ENV": "production", "PRINCESS_COMPONENT": "web_server",
            "PRINCESS_SESSION_SECRET": "sk_test_abc123"}
    assert code(lambda: runtime(prod)) == "test_credential_in_production"
    local = {"PRINCESS_ENV": "local", "PRINCESS_COMPONENT": "api", **LOCAL_SECRETS,
             "PRINCESS_SESSION_SECRET": "sk_live_abc123"}
    assert code(lambda: runtime(local)) == "live_credential_outside_production"


def test_public_bundles_have_no_secrets_in_any_environment():
    for env in Environment:
        loaded = load_manifest(ROOT, env)
        assert loaded.components["web_public"].secrets == frozenset()
        assert loaded.components["native_public"].secrets == frozenset()


EXACT_NPM = re.compile(r"^\d+\.\d+\.\d+$")


def test_javascript_dependencies_are_exact_pins():
    manifests = [ROOT / "package.json", *sorted((ROOT / "packages").glob("*/package.json")),
                 *sorted((ROOT / "apps").glob("*/package.json"))]
    assert len(manifests) >= 3
    for path in manifests:
        data = json.loads(path.read_text())
        for group in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for name, spec in data.get(group, {}).items():
                assert spec == "workspace:*" or EXACT_NPM.match(spec), f"{path}: {name}@{spec}"
    root = json.loads((ROOT / "package.json").read_text())
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+\+sha512\.[0-9a-f]{128}", root["packageManager"])
    assert (ROOT / "pnpm-lock.yaml").is_file()


def exact_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, version = line.split("==")
            pins[re.sub(r"[-_.]+", "-", name).lower()] = version
    return pins


def test_backend_environment_keeps_core_pins_and_excludes_provider_sdks():
    core = exact_pins(ROOT / "requirements" / "ci-py312.txt")
    app = exact_pins(ROOT / "requirements" / "app-py312.txt")
    assert all(app.get(name) == version for name, version in core.items())
    forbidden = {"openai", "anthropic", "stripe", "boto3", "google-cloud-storage", "firebase-admin", "torch",
                 "sentry-sdk", "resend"}
    assert not forbidden & set(app)
    lock = (ROOT / "requirements" / "app-py312.lock").read_text()
    assert "# Python 3.12; Linux x86_64." in lock
    assert {line.split("==")[0].lower().replace("_", "-") for line in lock.splitlines()
            if "==" in line} == set(app)


def test_free_distribution_excludes_the_application_and_provider_dependencies():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "princess_graphology*", "princess_contracts*"]
    deps = {re.split(r"[<>=!~ ]", d, maxsplit=1)[0] for d in pyproject["project"]["dependencies"]}
    assert deps == {"numpy", "opencv-python-headless", "scipy", "scikit-learn", "scikit-image"}
