"""Durable Premium provider attempts for restore reconciliation (T24).

Records only bounded provider-attempt metadata. Private packets, images and
model output are deliberately absent. The worker role owns this operational
journal; rows follow the Premium job lifecycle and cascade when deleted jobs
are erased.

Revision ID: 0010_provider_attempt
Revises: 0009_restore_and_transfer
"""
from __future__ import annotations

from alembic import op

revision = "0010_provider_attempt"
down_revision = "0009_restore_and_transfer"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
SHA = r"'^[0-9a-f]{64}$'"

UPGRADE = f"""
CREATE TABLE app.provider_attempt (
  attempt_id text PRIMARY KEY CHECK (attempt_id ~ {OPAQUE}),
  job_id text NOT NULL REFERENCES app.job (job_id) ON DELETE CASCADE,
  attempt_number integer NOT NULL CHECK (attempt_number > 0),
  packet_digest text NOT NULL CHECK (packet_digest ~ {SHA}),
  policy_version text NOT NULL CHECK (policy_version ~ {OPAQUE}),
  state text NOT NULL CHECK (state IN ('STARTED', 'COMPLETED', 'REFUSED', 'INCOMPLETE', 'AMBIGUOUS', 'FAILED')),
  error_code text,
  provider_request_id text,
  model_requested text,
  model_returned text,
  usage_input_tokens bigint CHECK (usage_input_tokens IS NULL OR usage_input_tokens >= 0),
  usage_output_tokens bigint CHECK (usage_output_tokens IS NULL OR usage_output_tokens >= 0),
  created_at timestamptz NOT NULL,
  completed_at timestamptz,
  UNIQUE (job_id, attempt_number),
  CHECK ((state = 'STARTED') = (completed_at IS NULL))
);

ALTER TABLE app.provider_attempt ENABLE ROW LEVEL SECURITY;
CREATE POLICY worker_provider_attempt ON app.provider_attempt TO princess_worker
  USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON app.provider_attempt TO princess_worker;
"""

DOWNGRADE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM app.provider_attempt) THEN
    RAISE EXCEPTION 'refusing to drop provider attempt history';
  END IF;
END $$;
DROP TABLE app.provider_attempt;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
