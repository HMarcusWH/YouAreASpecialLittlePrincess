"""Product plane: principals, identity bindings, assets, runs, reports,
permission ledger, jobs and outbox with owner-scoped row-level security.

Revision ID: 0001_product_plane
Revises:
"""
from __future__ import annotations

from alembic import op

revision = "0001_product_plane"
down_revision = None
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
SHA = r"'^[0-9a-f]{64}$'"

UPGRADE = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_app') THEN
    CREATE ROLE princess_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;

CREATE SCHEMA app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO princess_app;

CREATE FUNCTION app.current_principal() RETURNS text LANGUAGE sql STABLE AS
$f$ SELECT nullif(current_setting('princess.principal_id', true), '') $f$;

CREATE TABLE app.principal (
  principal_id text PRIMARY KEY CHECK (principal_id ~ {OPAQUE}),
  kind text NOT NULL CHECK (kind IN ('GUEST', 'ACCOUNT')),
  created_at timestamptz NOT NULL,
  revoked_before timestamptz,
  deleted_at timestamptz,
  transferred_to text REFERENCES app.principal (principal_id),
  guest_capability_sha256 text UNIQUE CHECK (guest_capability_sha256 ~ {SHA}),
  guest_expires_at timestamptz,
  CHECK ((kind = 'GUEST') = (guest_expires_at IS NOT NULL)),
  CHECK (kind = 'GUEST' OR guest_capability_sha256 IS NULL)
);

CREATE TABLE app.identity_binding (
  issuer text NOT NULL CHECK (length(issuer) BETWEEN 1 AND 512),
  subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 512),
  principal_id text NOT NULL REFERENCES app.principal (principal_id),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (issuer, subject)
);
CREATE INDEX identity_binding_principal ON app.identity_binding (principal_id);

CREATE TABLE app.asset (
  asset_id text PRIMARY KEY CHECK (asset_id ~ {OPAQUE}),
  owner_id text NOT NULL REFERENCES app.principal (principal_id),
  kind text NOT NULL CHECK (kind IN ('ORIGINAL', 'DERIVATIVE', 'EXPORT')),
  parent_asset_id text,
  sha256 text NOT NULL CHECK (sha256 ~ {SHA}),
  media_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  version_ref text NOT NULL,
  created_at timestamptz NOT NULL,
  deleted_at timestamptz,
  UNIQUE (owner_id, asset_id),
  FOREIGN KEY (owner_id, parent_asset_id) REFERENCES app.asset (owner_id, asset_id) ON UPDATE CASCADE
);

CREATE TABLE app.analysis_run (
  run_id text PRIMARY KEY CHECK (run_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  input_asset_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  engine_version text NOT NULL,
  feature_schema text NOT NULL,
  method_manifest text NOT NULL CHECK (method_manifest ~ {SHA}),
  analysis_config_sha256 text NOT NULL CHECK (analysis_config_sha256 ~ {SHA}),
  input_sha256 text NOT NULL CHECK (input_sha256 ~ {SHA}),
  processed_sha256 text CHECK (processed_sha256 ~ {SHA}),
  result jsonb,
  result_digest text CHECK (result_digest ~ {SHA}),
  created_at timestamptz NOT NULL,
  completed_at timestamptz,
  error_code text,
  UNIQUE (owner_id, run_id),
  FOREIGN KEY (owner_id, input_asset_id) REFERENCES app.asset (owner_id, asset_id) ON UPDATE CASCADE,
  CHECK ((status = 'SUCCEEDED') = (result IS NOT NULL AND result_digest IS NOT NULL))
);
CREATE INDEX analysis_run_owner_time ON app.analysis_run (owner_id, created_at DESC);

CREATE TABLE app.measurement (
  owner_id text NOT NULL,
  run_id text NOT NULL,
  feature_id text NOT NULL CHECK (feature_id ~ '^[A-Z][A-Z0-9_]{{0,63}}$'),
  value_float double precision,
  value_json jsonb,
  unit text,
  quality text NOT NULL CHECK (quality IN ('OK', 'EXPERIMENTAL', 'MISSING', 'REJECTED')),
  missing_reason text,
  n_observations integer NOT NULL CHECK (n_observations >= 0),
  method_id text NOT NULL,
  confidence double precision CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  confidence_kind text NOT NULL CHECK (confidence_kind IN ('UNCALIBRATED', 'EXACT_CONDITIONAL', 'CALIBRATED')),
  PRIMARY KEY (run_id, feature_id),
  FOREIGN KEY (owner_id, run_id) REFERENCES app.analysis_run (owner_id, run_id) ON UPDATE CASCADE ON DELETE CASCADE,
  CHECK (value_float IS NULL OR value_float NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)),
  CHECK (value_float IS NULL OR value_json IS NULL),
  CHECK ((quality = 'MISSING') = (value_float IS NULL AND value_json IS NULL)),
  CHECK ((quality = 'MISSING') = (missing_reason IS NOT NULL))
);
CREATE INDEX measurement_feature ON app.measurement (feature_id, run_id);

CREATE TABLE app.region (
  owner_id text NOT NULL,
  run_id text NOT NULL,
  region_id text NOT NULL CHECK (region_id ~ {OPAQUE}),
  scope text NOT NULL,
  x integer NOT NULL CHECK (x >= 0),
  y integer NOT NULL CHECK (y >= 0),
  width integer NOT NULL CHECK (width >= 1),
  height integer NOT NULL CHECK (height >= 1),
  parent_region_id text,
  PRIMARY KEY (run_id, region_id),
  FOREIGN KEY (owner_id, run_id) REFERENCES app.analysis_run (owner_id, run_id) ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (run_id, parent_region_id) REFERENCES app.region (run_id, region_id)
);

CREATE TABLE app.evidence_bundle (
  bundle_id text PRIMARY KEY CHECK (bundle_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  run_id text NOT NULL UNIQUE,
  digest text NOT NULL CHECK (digest ~ {SHA}),
  document jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  FOREIGN KEY (owner_id, run_id) REFERENCES app.analysis_run (owner_id, run_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE app.report (
  report_id text PRIMARY KEY CHECK (report_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  run_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('INDIVIDUAL', 'PAIR', 'HISTORY')),
  created_at timestamptz NOT NULL,
  deleted_at timestamptz,
  UNIQUE (owner_id, report_id),
  FOREIGN KEY (owner_id, run_id) REFERENCES app.analysis_run (owner_id, run_id) ON UPDATE CASCADE
);
CREATE INDEX report_owner_time ON app.report (owner_id, created_at DESC);

CREATE TABLE app.report_revision (
  report_id text NOT NULL,
  revision integer NOT NULL CHECK (revision >= 1),
  owner_id text NOT NULL,
  digest text NOT NULL CHECK (digest ~ {SHA}),
  document jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (report_id, revision),
  FOREIGN KEY (owner_id, report_id) REFERENCES app.report (owner_id, report_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE app.permission_event (
  event_id text PRIMARY KEY CHECK (event_id ~ {OPAQUE}),
  sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  subject_id text NOT NULL REFERENCES app.principal (principal_id),
  actor_id text NOT NULL,
  purpose_id text NOT NULL,
  purpose_version integer NOT NULL CHECK (purpose_version >= 1),
  scope_kind text NOT NULL,
  scope_ref text,
  decision text NOT NULL CHECK (decision IN ('GRANT', 'DENY', 'WITHDRAW')),
  recorded_at timestamptz NOT NULL,
  effective_at timestamptz NOT NULL,
  notice_version text NOT NULL,
  CHECK (effective_at >= recorded_at),
  CHECK ((scope_kind = 'SUBJECT_WIDE') = (scope_ref IS NULL))
);
CREATE INDEX permission_event_lookup ON app.permission_event (subject_id, purpose_id, recorded_at);

CREATE TABLE app.permission_epoch (
  subject_id text NOT NULL REFERENCES app.principal (principal_id),
  purpose_id text NOT NULL,
  epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
  PRIMARY KEY (subject_id, purpose_id)
);

CREATE TABLE app.job (
  job_id text PRIMARY KEY CHECK (job_id ~ {OPAQUE}),
  kind text NOT NULL,
  owner_id text NOT NULL REFERENCES app.principal (principal_id),
  subject_ref text NOT NULL,
  state text NOT NULL CHECK (state IN ('QUEUED', 'LEASED', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  dedupe_key text NOT NULL UNIQUE,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  lease_owner text,
  lease_expires_at timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  last_error text,
  CHECK ((state = 'LEASED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX job_claim ON app.job (state, kind, created_at);

CREATE TABLE app.outbox_event (
  event_id text PRIMARY KEY CHECK (event_id ~ {OPAQUE}),
  topic text NOT NULL,
  owner_id text REFERENCES app.principal (principal_id),
  aggregate_ref text NOT NULL,
  payload jsonb NOT NULL,
  dedupe_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL,
  dispatched_at timestamptz
);

-- Row-level security: the runtime role sees only the current principal's rows.
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['asset', 'analysis_run', 'measurement', 'region', 'evidence_bundle', 'report',
                           'report_revision', 'job', 'outbox_event'] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY owner_isolation ON app.%I TO princess_app
                    USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal())', t);
  END LOOP;
END $$;

ALTER TABLE app.principal ENABLE ROW LEVEL SECURITY;
CREATE POLICY self_only ON app.principal TO princess_app
  USING (principal_id = app.current_principal()) WITH CHECK (principal_id = app.current_principal());

ALTER TABLE app.identity_binding ENABLE ROW LEVEL SECURITY;
CREATE POLICY binding_lookup ON app.identity_binding FOR SELECT TO princess_app
  USING (principal_id = app.current_principal()
         OR (issuer = current_setting('princess.auth_issuer', true)
             AND subject = current_setting('princess.auth_subject', true)));
CREATE POLICY binding_insert ON app.identity_binding FOR INSERT TO princess_app
  WITH CHECK (principal_id = app.current_principal());
CREATE POLICY binding_rebind ON app.identity_binding FOR UPDATE TO princess_app
  USING (issuer = current_setting('princess.auth_issuer', true)
         AND subject = current_setting('princess.auth_subject', true))
  WITH CHECK (principal_id = app.current_principal());

ALTER TABLE app.permission_event ENABLE ROW LEVEL SECURITY;
CREATE POLICY subject_only ON app.permission_event TO princess_app
  USING (subject_id = app.current_principal()) WITH CHECK (subject_id = app.current_principal());
ALTER TABLE app.permission_epoch ENABLE ROW LEVEL SECURITY;
CREATE POLICY subject_only ON app.permission_epoch TO princess_app
  USING (subject_id = app.current_principal()) WITH CHECK (subject_id = app.current_principal());

-- Immutable/append-only facts: no UPDATE or DELETE for the runtime role.
GRANT SELECT, INSERT ON app.measurement, app.region, app.evidence_bundle, app.report_revision,
  app.permission_event TO princess_app;
GRANT SELECT, INSERT, UPDATE ON app.principal, app.identity_binding, app.asset, app.analysis_run, app.report,
  app.permission_epoch, app.job, app.outbox_event TO princess_app;
GRANT EXECUTE ON FUNCTION app.current_principal() TO princess_app;

-- Guest capability lookup without exposing other principals.
CREATE FUNCTION app.resolve_guest(p_capability_sha256 text)
RETURNS TABLE (principal_id text, created_at timestamptz, guest_expires_at timestamptz, deleted_at timestamptz,
               revoked_before timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$ SELECT p.principal_id, p.created_at, p.guest_expires_at, p.deleted_at, p.revoked_before FROM app.principal p
    WHERE p.kind = 'GUEST' AND p.transferred_to IS NULL AND p.guest_capability_sha256 = p_capability_sha256 $f$;

-- Atomic guest-to-account transfer. The caller must already act as the
-- authenticated account (principal context) and prove the guest capability.
CREATE FUNCTION app.transfer_guest(p_capability_sha256 text, p_at timestamptz) RETURNS text
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
  -- Owner changes cascade through the composite (owner_id, id) foreign keys.
  UPDATE app.asset SET owner_id = v_account WHERE owner_id = v_guest.principal_id;
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

REVOKE ALL ON FUNCTION app.resolve_guest(text), app.transfer_guest(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.resolve_guest(text), app.transfer_guest(text, timestamptz) TO princess_app;
"""

DOWNGRADE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM app.principal) THEN
    RAISE EXCEPTION 'refusing to drop the product plane while principals exist; restore or erase explicitly';
  END IF;
END $$;
DROP SCHEMA app CASCADE;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
