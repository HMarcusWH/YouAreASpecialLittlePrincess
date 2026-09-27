"""Report feedback (T24): owner-bound, redacted, expiring, support-only.

Rows go with their report (ON DELETE CASCADE), so capture and account
erasure remove them. ``princess_support`` is the only non-owner role that can
read feedback, and it sees the feedback columns only: no owner ID and no
grants on reports, captures, assets or measurements. Telemetry and analytics
roles get nothing here.

Revision ID: 0007_report_feedback
Revises: 0006_durable_erasure
"""
from __future__ import annotations

from alembic import op

revision = "0007_report_feedback"
down_revision = "0006_durable_erasure"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"

UPGRADE = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_support') THEN
    CREATE ROLE princess_support NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
GRANT USAGE ON SCHEMA app TO princess_support;

CREATE TABLE app.report_feedback (
  feedback_id text PRIMARY KEY CHECK (feedback_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  report_id text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 1),
  category text NOT NULL CHECK (category IN ('MEASUREMENT_LOOKS_WRONG', 'HARD_TO_UNDERSTAND',
                                             'HARMFUL_OR_OFFENSIVE', 'PREMIUM_TEXT_ISSUE', 'OTHER')),
  target_kind text NOT NULL CHECK (target_kind IN ('REPORT', 'SECTION', 'FACT', 'PREMIUM')),
  target_ref text CHECK (target_ref ~ {OPAQUE}),
  comment text CHECK (length(comment) BETWEEN 1 AND 600),
  contract_version text NOT NULL,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL CHECK (expires_at > created_at),
  FOREIGN KEY (owner_id, report_id) REFERENCES app.report (owner_id, report_id)
    ON UPDATE CASCADE ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  CHECK ((target_kind = 'REPORT') = (target_ref IS NULL))
);
CREATE INDEX report_feedback_report ON app.report_feedback (owner_id, report_id);
CREATE INDEX report_feedback_expiry ON app.report_feedback (expires_at);

ALTER TABLE app.report_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.report_feedback TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());
GRANT SELECT, INSERT, DELETE ON app.report_feedback TO princess_app;

CREATE POLICY support_review ON app.report_feedback FOR SELECT TO princess_support USING (true);
GRANT SELECT (feedback_id, report_id, revision, category, target_kind, target_ref, comment, contract_version,
              created_at, expires_at) ON app.report_feedback TO princess_support;

CREATE FUNCTION app.expire_feedback(p_now timestamptz, p_limit integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_count integer;
BEGIN
  DELETE FROM app.report_feedback WHERE feedback_id IN (
    SELECT feedback_id FROM app.report_feedback WHERE expires_at <= p_now ORDER BY expires_at LIMIT p_limit);
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END
$f$;
REVOKE ALL ON FUNCTION app.expire_feedback(timestamptz, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.expire_feedback(timestamptz, integer) TO princess_app, princess_worker;
"""

DOWNGRADE = """
DROP FUNCTION app.expire_feedback(timestamptz, integer);
DROP TABLE app.report_feedback;
REVOKE USAGE ON SCHEMA app FROM princess_support;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
