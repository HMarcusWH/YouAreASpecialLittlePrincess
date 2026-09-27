"""Account erasure and guest admission.

``app.erase_deleted_account`` removes a deleted account's analysis records,
reports and Premium payloads once every object-store asset of that account is
verified erased (the erasure worker does that first). Consent history, the
financial ledger and deletion tombstones stay: they are accountability and
accounting records, not the user's writing.

``app.admit_guest`` counts guest creations per fixed window so unauthenticated
callers cannot grow the principal table without bound. Per-network limits
belong at the edge.

Revision ID: 0004_erasure_admission
Revises: 0003_commerce_ledger
"""
from __future__ import annotations

from alembic import op

revision = "0004_erasure_admission"
down_revision = "0003_commerce_ledger"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE FUNCTION app.erase_deleted_account(p_owner text, p_at timestamptz) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_reports integer;
BEGIN
  PERFORM 1 FROM app.principal WHERE principal_id = p_owner AND deleted_at IS NOT NULL FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'account_not_deleted' USING ERRCODE = 'P0002';
  END IF;
  IF EXISTS (SELECT 1 FROM app.asset WHERE owner_id = p_owner AND deleted_at IS NULL) THEN
    RAISE EXCEPTION 'assets_not_erased' USING ERRCODE = '55000';
  END IF;
  SET CONSTRAINTS ALL DEFERRED;
  DELETE FROM app.premium_overlay WHERE owner_id = p_owner;
  DELETE FROM app.report WHERE owner_id = p_owner;  -- cascades to every revision
  GET DIAGNOSTICS v_reports = ROW_COUNT;
  DELETE FROM app.job WHERE owner_id = p_owner;     -- cascades to attempts
  DELETE FROM app.analysis_run WHERE owner_id = p_owner;  -- measurements, regions, evidence
  DELETE FROM app.capture WHERE owner_id = p_owner;
  DELETE FROM app.upload WHERE owner_id = p_owner;
  RETURN v_reports;
END
$f$;
REVOKE ALL ON FUNCTION app.erase_deleted_account(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.erase_deleted_account(text, timestamptz) TO princess_worker;

CREATE TABLE app.guest_admission (
  window_start timestamptz PRIMARY KEY,
  admitted integer NOT NULL CHECK (admitted >= 0)
);
ALTER TABLE app.guest_admission ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION app.admit_guest(p_at timestamptz, p_window_seconds integer, p_limit integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_window timestamptz := to_timestamp(floor(extract(epoch FROM p_at) / p_window_seconds) * p_window_seconds);
  v_admitted integer;
BEGIN
  IF p_window_seconds < 1 OR p_limit < 0 THEN
    RAISE EXCEPTION 'invalid_admission_policy' USING ERRCODE = '22023';
  END IF;
  INSERT INTO app.guest_admission AS g (window_start, admitted) VALUES (v_window, 1)
    ON CONFLICT (window_start) DO UPDATE SET admitted = g.admitted + 1
    WHERE g.admitted < p_limit
    RETURNING admitted INTO v_admitted;
  DELETE FROM app.guest_admission WHERE window_start < v_window - make_interval(secs => p_window_seconds * 2);
  RETURN v_admitted IS NOT NULL AND v_admitted <= p_limit;
END
$f$;
REVOKE ALL ON FUNCTION app.admit_guest(timestamptz, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.admit_guest(timestamptz, integer, integer) TO princess_app;
"""

DOWNGRADE = """
DROP FUNCTION app.admit_guest(timestamptz, integer, integer);
DROP TABLE app.guest_admission;
DROP FUNCTION app.erase_deleted_account(text, timestamptz);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
