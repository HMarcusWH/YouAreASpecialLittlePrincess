"""Alembic environment. The database URL is passed programmatically by
``princess_app.adapters.postgres.migrate``; nothing is read from a checked-in
ini file or from the runtime role's configuration."""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

url = context.config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("migrations need an explicit migration-role database URL")

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True,
                      version_table_schema="public")
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
