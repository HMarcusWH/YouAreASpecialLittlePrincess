"""Backend integration tests. They need a real PostgreSQL; there is no skip path.

Set ``PRINCESS_TEST_DATABASE_URL`` to a disposable database owned by a role
that may create roles and schemas (see infra/README.md).
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("PRINCESS_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("PRINCESS_TEST_DATABASE_URL is required for tests_app (see infra/README.md)")
    return url
