"""Intake (upload slots, immutable captures), job attempts and the worker role.

Revision ID: 0002_intake_and_jobs
Revises: 0001_product_plane
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0002_intake_and_jobs"
down_revision = "0001_product_plane"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
SHA = r"'^[0-9a-f]{64}$'"

UPGRADE = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_worker') THEN
    CREATE ROLE princess_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
-- Workers act through the same owner-scoped policies as the API once they have
-- claimed a job and set the job owner's principal context.
GRANT princess_app TO princess_worker;

CREATE TABLE app.upload (
  upload_id text PRIMARY KEY CHECK (upload_id ~ {OPAQUE}),
  owner_id text NOT NULL REFERENCES app.principal (principal_id),
  asset_id text NOT NULL UNIQUE CHECK (asset_id ~ {OPAQUE}),
  media_type text NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png')),
  max_bytes bigint NOT NULL CHECK (max_bytes > 0),
  -- COMPLETING serializes completion: one request promotes and inspects bytes.
  state text NOT NULL CHECK (state IN ('RESERVED', 'COMPLETING', 'COMPLETED', 'REJECTED', 'REVOKED')),
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  completed_at timestamptz,
  UNIQUE (owner_id, upload_id),
  CHECK (expires_at > created_at)
);
CREATE INDEX upload_owner_time ON app.upload (owner_id, created_at DESC);

CREATE TABLE app.capture (
  capture_id text PRIMARY KEY CHECK (capture_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  upload_id text NOT NULL UNIQUE,
  asset_id text NOT NULL,
  media_type text NOT NULL,
  width integer NOT NULL CHECK (width BETWEEN 1 AND 100000),
  height integer NOT NULL CHECK (height BETWEEN 1 AND 100000),
  exif_orientation integer NOT NULL CHECK (exif_orientation BETWEEN 1 AND 8),
  sha256 text NOT NULL CHECK (sha256 ~ {SHA}),
  created_at timestamptz NOT NULL,
  deleted_at timestamptz,
  UNIQUE (owner_id, capture_id),
  FOREIGN KEY (owner_id, upload_id) REFERENCES app.upload (owner_id, upload_id) ON UPDATE CASCADE,
  FOREIGN KEY (owner_id, asset_id) REFERENCES app.asset (owner_id, asset_id) ON UPDATE CASCADE
);

ALTER TABLE app.analysis_run ADD COLUMN capture_id text;
ALTER TABLE app.analysis_run ADD FOREIGN KEY (owner_id, capture_id)
  REFERENCES app.capture (owner_id, capture_id) ON UPDATE CASCADE;

CREATE TABLE app.job_attempt (
  job_id text NOT NULL REFERENCES app.job (job_id) ON DELETE CASCADE,
  fencing_token bigint NOT NULL,
  worker_id text NOT NULL,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  outcome text CHECK (outcome IN ('SUCCEEDED', 'FAILED', 'FENCED', 'CANCELLED', 'RETRY')),
  error_code text,
  PRIMARY KEY (job_id, fencing_token)
);

ALTER TABLE app.upload ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.upload TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());
ALTER TABLE app.capture ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.capture TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());

-- Claiming work: only the worker role sees every job/attempt row.
CREATE POLICY worker_claim ON app.job TO princess_worker USING (true) WITH CHECK (true);
ALTER TABLE app.job_attempt ENABLE ROW LEVEL SECURITY;
CREATE POLICY worker_attempts ON app.job_attempt TO princess_worker USING (true) WITH CHECK (true);
CREATE POLICY owner_attempts ON app.job_attempt FOR SELECT TO princess_app
  USING (EXISTS (SELECT 1 FROM app.job j WHERE j.job_id = job_attempt.job_id
                 AND j.owner_id = app.current_principal()));

GRANT SELECT, INSERT, UPDATE ON app.upload, app.capture TO princess_app;
GRANT SELECT ON app.job_attempt TO princess_app;
GRANT SELECT, INSERT, UPDATE ON app.job_attempt TO princess_worker;

-- Erasure/retention consumers read every outbox row and mark it dispatched.
CREATE POLICY worker_outbox ON app.outbox_event TO princess_worker USING (true) WITH CHECK (true);
GRANT UPDATE (dispatched_at) ON app.outbox_event TO princess_worker;

-- Owner changes cascade through overlapping composite (owner_id, id) keys, so
-- guest transfer checks them at commit instead of after each statement.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
           WHERE contype = 'f' AND connamespace = 'app'::regnamespace LOOP
    EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE', r.tbl, r.conname);
  END LOOP;
END $$;

-- Guest transfer must also move the new owner-scoped rows.
CREATE OR REPLACE FUNCTION app.transfer_guest(p_capability_sha256 text, p_at timestamptz) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_account text := app.current_principal();
  v_guest app.principal;
BEGIN
  IF v_account IS NULL OR NOT EXISTS (SELECT 1 FROM app.principal
      WHERE principal_id = v_account AND kind = 'ACCOUNT' AND deleted_at IS NULL) THEN
    RAISE EXCEPTION 'account_required' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO v_guest FROM app.principal
    WHERE kind = 'GUEST' AND guest_capability_sha256 = p_capability_sha256 FOR UPDATE;
  IF NOT FOUND OR v_guest.transferred_to IS NOT NULL THEN
    RAISE EXCEPTION 'guest_not_transferable' USING ERRCODE = 'P0002';
  END IF;
  IF v_guest.guest_expires_at <= p_at OR v_guest.deleted_at IS NOT NULL OR v_guest.revoked_before IS NOT NULL THEN
    RAISE EXCEPTION 'guest_not_transferable' USING ERRCODE = 'P0002';
  END IF;
  SET CONSTRAINTS ALL DEFERRED;
  -- Work started under the guest's permissions cannot publish for the account:
  -- end it explicitly instead of leaving a stale worker to fence it later.
  WITH ended AS (
    UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL,
      last_error = 'owner_transferred', updated_at = p_at
    WHERE owner_id = v_guest.principal_id AND state IN ('QUEUED', 'LEASED') RETURNING subject_ref)
  UPDATE app.analysis_run SET status = 'CANCELLED', error_code = 'owner_transferred', completed_at = p_at
    WHERE owner_id = v_guest.principal_id AND run_id IN (SELECT subject_ref FROM ended)
      AND status IN ('QUEUED', 'RUNNING');
  UPDATE app.upload SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.asset SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.capture SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.analysis_run SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.report SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.job SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  UPDATE app.outbox_event SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
  -- Permission history is append-only and stays with the principal that
  -- recorded it; the account must decide for itself. Moving the account's
  -- epochs fences in-flight work that started under the guest's grants.
  INSERT INTO app.permission_epoch (subject_id, purpose_id, epoch)
    SELECT DISTINCT v_account, purpose_id, 1 FROM app.permission_event WHERE subject_id = v_guest.principal_id
    ON CONFLICT (subject_id, purpose_id) DO UPDATE SET epoch = app.permission_epoch.epoch + 1;
  UPDATE app.principal SET transferred_to = v_account, guest_capability_sha256 = NULL
    WHERE principal_id = v_guest.principal_id;
  RETURN v_guest.principal_id;
END
$f$;
"""

DOWNGRADE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM app.upload) OR EXISTS (SELECT 1 FROM app.job_attempt) THEN
    RAISE EXCEPTION 'refusing to drop intake tables that hold rows';
  END IF;
END $$;
DROP POLICY IF EXISTS worker_claim ON app.job;
DROP POLICY IF EXISTS worker_outbox ON app.outbox_event;
REVOKE UPDATE (dispatched_at) ON app.outbox_event FROM princess_worker;
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
           WHERE contype = 'f' AND connamespace = 'app'::regnamespace LOOP
    EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I NOT DEFERRABLE', r.tbl, r.conname);
  END LOOP;
END $$;
DROP TABLE app.job_attempt;
ALTER TABLE app.analysis_run DROP COLUMN capture_id;
DROP TABLE app.capture;
DROP TABLE app.upload;
REVOKE princess_app FROM princess_worker;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def _transfer_guest_v1() -> str:
    """The 0001 function, restored on downgrade so it never references dropped tables."""
    source = Path(__file__).with_name("0001_product_plane.py").read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION app.transfer_guest")
    end = source.index("$f$;", start) + len("$f$;")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def downgrade() -> None:
    op.execute(_transfer_guest_v1())
    op.execute(DOWNGRADE)
