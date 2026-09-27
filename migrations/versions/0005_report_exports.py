"""Report exports (T21): PDF documents and share cards rendered from one
authorized projection of a saved report revision.

The rendered bytes are an ``EXPORT`` asset in the object store, so account
deletion erases them with every other asset. ``cache_key`` is the digest of
the authorized projection (without its generation time) plus layout and
template, so anything that changes what may be shown — a revoked image, an
erased Premium payload, a new revision — yields a different key.

Revision ID: 0005_report_exports
Revises: 0004_erasure_admission
"""
from __future__ import annotations

from alembic import op

revision = "0005_report_exports"
down_revision = "0004_erasure_admission"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
SHA = r"'^[0-9a-f]{64}$'"

UPGRADE = f"""
CREATE TABLE app.report_export (
  export_id text PRIMARY KEY CHECK (export_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  report_id text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 1),
  projection text NOT NULL CHECK (projection IN ('EXPORT', 'SHARE')),
  layout text NOT NULL CHECK (layout IN ('A4', 'LETTER', 'CARD_SQUARE', 'CARD_STORY')),
  params jsonb NOT NULL,
  template_version text NOT NULL,
  cache_key text NOT NULL CHECK (cache_key ~ {SHA}),
  state text NOT NULL CHECK (state IN ('QUEUED', 'READY', 'FAILED', 'REVOKED')),
  asset_id text,
  media_type text,
  size_bytes bigint CHECK (size_bytes > 0),
  sha256 text CHECK (sha256 ~ {SHA}),
  error_code text,
  created_at timestamptz NOT NULL,
  completed_at timestamptz,
  UNIQUE (owner_id, cache_key),
  FOREIGN KEY (owner_id, report_id) REFERENCES app.report (owner_id, report_id)
    ON UPDATE CASCADE ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  FOREIGN KEY (owner_id, asset_id) REFERENCES app.asset (owner_id, asset_id)
    ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  -- A REVOKED export keeps naming its (erased) asset as the tombstone.
  CHECK (state <> 'READY' OR (asset_id IS NOT NULL AND sha256 IS NOT NULL AND completed_at IS NOT NULL)),
  CHECK (state NOT IN ('QUEUED', 'FAILED') OR asset_id IS NULL)
);
CREATE INDEX report_export_report ON app.report_export (owner_id, report_id);

ALTER TABLE app.report_export ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.report_export TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());
GRANT SELECT, INSERT, UPDATE ON app.report_export TO princess_app;
"""

DOWNGRADE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM app.report_export WHERE asset_id IS NOT NULL) THEN
    RAISE EXCEPTION 'refusing to drop export records that still name stored assets';
  END IF;
END $$;
DROP TABLE app.report_export;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
