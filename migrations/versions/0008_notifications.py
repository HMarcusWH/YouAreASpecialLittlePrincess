"""Notification delivery (T24): push bindings, mail preference, delivery records.

* ``push_installation`` binds one device token to one principal. The API
  (``princess_app``) registers through ``app.bind_push_installation`` and can
  see and delete its own bindings but never read a token back; only the
  notification worker (``princess_worker``) reads tokens. A token registered
  by another account moves to it (account switch) and the old binding goes,
  with anything still queued for it.
* ``notification_preference`` holds the owner's opt-in to report-ready mail.
* ``notification_delivery`` is the durable delivery record: one row per
  report and target, keyed by a delivery key the providers see, so a
  replayed outbox event or a second worker never plans a second delivery.
  Rows go with their report, their installation, or their account.
* ``mail_suppression`` records recipients who must not be mailed.

Revision ID: 0008_notifications
Revises: 0007_report_feedback
"""
from __future__ import annotations

from alembic import op

revision = "0008_notifications"
down_revision = "0007_report_feedback"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
LOCALE = r"'^[a-z]{2}(-[A-Z]{2})?$'"

UPGRADE = f"""
CREATE TABLE app.push_installation (
  installation_id text PRIMARY KEY CHECK (installation_id ~ {OPAQUE}),
  owner_id text NOT NULL REFERENCES app.principal (principal_id),
  platform text NOT NULL CHECK (platform IN ('apns', 'fcm')),
  app_environment text NOT NULL CHECK (app_environment IN ('local', 'test', 'preview', 'staging', 'production')),
  device_token text NOT NULL CHECK (length(device_token) BETWEEN 8 AND 4096
                                     AND device_token ~ '^[A-Za-z0-9_:.-]+$'),
  token_sha256 text NOT NULL CHECK (token_sha256 ~ '^[0-9a-f]{{64}}$'),
  locale text NOT NULL CHECK (locale ~ {LOCALE}),
  registered_at timestamptz NOT NULL,
  UNIQUE (platform, app_environment, token_sha256)
);
CREATE INDEX push_installation_owner ON app.push_installation (owner_id, registered_at);
ALTER TABLE app.push_installation ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.push_installation TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());
GRANT SELECT (installation_id, owner_id, platform, app_environment, locale, registered_at), DELETE
  ON app.push_installation TO princess_app;
CREATE POLICY worker_delivery ON app.push_installation TO princess_worker USING (true);
GRANT SELECT ON app.push_installation TO princess_worker;

CREATE FUNCTION app.bind_push_installation(p_installation_id text, p_platform text, p_environment text,
                                           p_device_token text, p_locale text, p_at timestamptz, p_max integer)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_owner text := app.current_principal();
  v_digest text := encode(sha256(convert_to(p_device_token, 'UTF8')), 'hex');
  v_existing app.push_installation;
BEGIN
  IF v_owner IS NULL OR NOT EXISTS (SELECT 1 FROM app.principal WHERE principal_id = v_owner
      AND deleted_at IS NULL AND transferred_to IS NULL) THEN
    RAISE EXCEPTION 'principal_required' USING ERRCODE = '42501';
  END IF;
  IF p_max < 1 THEN
    RAISE EXCEPTION 'invalid_installation_cap' USING ERRCODE = '22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('push:' || v_digest, 0));
  SELECT * INTO v_existing FROM app.push_installation
    WHERE platform = p_platform AND app_environment = p_environment AND token_sha256 = v_digest;
  IF FOUND AND v_existing.owner_id = v_owner THEN
    UPDATE app.push_installation SET locale = p_locale, registered_at = p_at
      WHERE installation_id = v_existing.installation_id;
    RETURN v_existing.installation_id;  -- a relaunch re-registers the same binding
  END IF;
  IF FOUND THEN
    -- The device now belongs to another account: late notifications for the
    -- previous one must not reach it.
    DELETE FROM app.push_installation WHERE installation_id = v_existing.installation_id;
  END IF;
  INSERT INTO app.push_installation (installation_id, owner_id, platform, app_environment, device_token,
                                     token_sha256, locale, registered_at)
    VALUES (p_installation_id, v_owner, p_platform, p_environment, p_device_token, v_digest, p_locale, p_at);
  DELETE FROM app.push_installation WHERE installation_id IN (
    SELECT installation_id FROM app.push_installation WHERE owner_id = v_owner
    ORDER BY registered_at DESC, installation_id DESC OFFSET p_max);
  RETURN p_installation_id;
END
$f$;
REVOKE ALL ON FUNCTION app.bind_push_installation(text, text, text, text, text, timestamptz, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.bind_push_installation(text, text, text, text, text, timestamptz, integer)
  TO princess_app;

CREATE TABLE app.notification_preference (
  owner_id text PRIMARY KEY REFERENCES app.principal (principal_id),
  mail_report_ready boolean NOT NULL,
  locale text NOT NULL CHECK (locale ~ {LOCALE}),
  updated_at timestamptz NOT NULL
);
ALTER TABLE app.notification_preference ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.notification_preference TO princess_app
  USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal());
GRANT SELECT, INSERT, UPDATE, DELETE ON app.notification_preference TO princess_app;
CREATE POLICY worker_delivery ON app.notification_preference FOR SELECT TO princess_worker USING (true);

CREATE TABLE app.notification_delivery (
  delivery_key text PRIMARY KEY CHECK (delivery_key ~ {OPAQUE}),
  owner_id text NOT NULL,
  report_id text NOT NULL,
  channel text NOT NULL CHECK (channel IN ('MAIL', 'PUSH')),
  kind text NOT NULL CHECK (kind ~ '^[a-z_]{{1,64}}$'),
  installation_id text REFERENCES app.push_installation (installation_id) ON DELETE CASCADE,
  state text NOT NULL CHECK (state IN ('PENDING', 'ACCEPTED', 'SUPPRESSED', 'SKIPPED', 'FAILED')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  not_before timestamptz NOT NULL,
  lease_until timestamptz,
  outcome text CHECK (outcome ~ '^[a-z0-9_.:-]{{1,64}}$'),
  provider_message_ref text CHECK (provider_message_ref ~ {OPAQUE}),
  created_at timestamptz NOT NULL,
  completed_at timestamptz,
  FOREIGN KEY (owner_id, report_id) REFERENCES app.report (owner_id, report_id)
    ON UPDATE CASCADE ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  CHECK ((channel = 'PUSH') = (installation_id IS NOT NULL)),
  CHECK ((state = 'PENDING') = (completed_at IS NULL))
);
CREATE INDEX notification_delivery_due ON app.notification_delivery (not_before) WHERE state = 'PENDING';
CREATE INDEX notification_delivery_done ON app.notification_delivery (completed_at) WHERE state <> 'PENDING';
CREATE INDEX notification_delivery_installation ON app.notification_delivery (installation_id);
ALTER TABLE app.notification_delivery ENABLE ROW LEVEL SECURITY;
CREATE POLICY worker_delivery ON app.notification_delivery TO princess_worker USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON app.notification_delivery TO princess_worker;

CREATE TABLE app.mail_suppression (
  recipient_ref text PRIMARY KEY REFERENCES app.principal (principal_id),
  reason text NOT NULL CHECK (reason IN ('BOUNCE', 'COMPLAINT', 'PROVIDER', 'MANUAL')),
  recorded_at timestamptz NOT NULL
);
ALTER TABLE app.mail_suppression ENABLE ROW LEVEL SECURITY;
CREATE POLICY worker_delivery ON app.mail_suppression TO princess_worker USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON app.mail_suppression TO princess_worker;

-- Account erasure: run by the erasure consumer in the same transaction as
-- app.erase_deleted_account.
CREATE FUNCTION app.erase_account_notifications(p_owner text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM app.principal WHERE principal_id = p_owner AND deleted_at IS NOT NULL) THEN
    RAISE EXCEPTION 'account_not_deleted' USING ERRCODE = 'P0002';
  END IF;
  DELETE FROM app.notification_delivery WHERE owner_id = p_owner;
  DELETE FROM app.push_installation WHERE owner_id = p_owner;
  DELETE FROM app.notification_preference WHERE owner_id = p_owner;
  DELETE FROM app.mail_suppression WHERE recipient_ref = p_owner;
END
$f$;
REVOKE ALL ON FUNCTION app.erase_account_notifications(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.erase_account_notifications(text) TO princess_worker;
"""

DOWNGRADE = """
DROP FUNCTION app.erase_account_notifications(text);
DROP TABLE app.mail_suppression;
DROP TABLE app.notification_delivery;
DROP TABLE app.notification_preference;
DROP FUNCTION app.bind_push_installation(text, text, text, text, text, timestamptz, integer);
DROP TABLE app.push_installation;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
