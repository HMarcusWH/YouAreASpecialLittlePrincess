"""Run reviewed Alembic migrations with an explicit migration-role URL."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parents[4] / "migrations"


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(_config(url), revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "downgrade"))
    parser.add_argument("revision", nargs="?", default="head")
    args = parser.parse_args()
    url = os.environ.get("PRINCESS_MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("PRINCESS_MIGRATION_DATABASE_URL is required")
    (upgrade if args.action == "upgrade" else downgrade)(url, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
