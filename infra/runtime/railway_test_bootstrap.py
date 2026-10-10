"""Create limited runtime database users after schema migration (test only)."""
from __future__ import annotations

import os
import psycopg
from psycopg import sql
from princess_app.adapters.postgres.migrate import upgrade

def main() -> int:
    assert os.environ["PRINCESS_ENV"] == "test"
    dsn = os.environ["PRINCESS_MIGRATION_DATABASE_URL"]
    users = [
        ("princess_railway_api", "princess_app", os.environ["PRINCESS_BOOTSTRAP_API_PASSWORD"]),
        ("princess_railway_worker", "princess_worker", os.environ["PRINCESS_BOOTSTRAP_WORKER_PASSWORD"]),
    ]
    if any(len(password) < 32 for _, _, password in users):
        raise RuntimeError("Database login credentials are too short")
    upgrade(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cursor:
            for username, group, password in users:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (username,))
                if cursor.fetchone():
                    cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(username), sql.Literal(password)))
                else:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                        sql.Identifier(username), sql.Literal(password)))
                cursor.execute(sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group), sql.Identifier(username)))
    print("Completed test migrations and least-privilege role bootstrap")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
