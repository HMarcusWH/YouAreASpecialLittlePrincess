"""Backend integration tests. They need a real PostgreSQL; there is no skip path.

``PRINCESS_TEST_DATABASE_URL`` must name a disposable database and a role that
can create roles and schemas (see infra/README.md). The suite migrates a fresh
``app`` schema and then connects as a separate non-owner login role that is a
member of ``princess_app``, so row-level security and grants are exercised.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import text

from princess_app.adapters.postgres import migrate
from princess_app.adapters.postgres.stores import Database, make_engine

APP_ROLE = "princess_api_test"
APP_PASSWORD = "test-only-app-role"
WORKER_ROLE = "princess_worker_test"
WORKER_PASSWORD = "test-only-worker-role"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("PRINCESS_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("PRINCESS_TEST_DATABASE_URL is required for tests_app (see infra/README.md)")
    return url


@pytest.fixture(scope="session")
def admin_engine(database_url):
    engine = make_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    migrate.upgrade(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
        conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS "
                          "IN ROLE princess_app"))
        conn.execute(text(f"DROP ROLE IF EXISTS {WORKER_ROLE}"))
        conn.execute(text(f"CREATE ROLE {WORKER_ROLE} LOGIN PASSWORD '{WORKER_PASSWORD}' NOSUPERUSER NOBYPASSRLS "
                          "IN ROLE princess_worker"))
    yield engine
    engine.dispose()


def _role_url(database_url: str, role: str, password: str) -> str:
    parts = urlsplit(database_url)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, f"{role}:{password}@{host}", parts.path, parts.query, ""))


@pytest.fixture(scope="session")
def app_url(database_url, admin_engine) -> str:
    return _role_url(database_url, APP_ROLE, APP_PASSWORD)


@pytest.fixture(scope="session")
def app_db(app_url) -> Database:
    return Database(make_engine(app_url))


@pytest.fixture(scope="session")
def worker_db(database_url, admin_engine) -> Database:
    return Database(make_engine(_role_url(database_url, WORKER_ROLE, WORKER_PASSWORD)))


@pytest.fixture(autouse=True)
def clean(admin_engine):
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("TRUNCATE app.principal, app.identity_binding, app.asset, app.analysis_run, "
                          "app.measurement, app.region, app.evidence_bundle, app.report, app.report_revision, "
                          "app.permission_event, app.permission_epoch, app.job, app.outbox_event, app.upload, "
                          "app.capture, app.job_attempt CASCADE"))
