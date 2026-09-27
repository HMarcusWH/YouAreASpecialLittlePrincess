"""Restore replay and guest transfer fixes (T24 review).

* Every WITHDRAW or DENY decision, for any purpose, now queues a durable
  ``permission.withdrawn`` event carrying its notice version and time, so the
  erasure worker records it in the tombstone log. Before this, only
  service-processing and image-retention decisions were queued, and a restore
  could bring back a withdrawn third-party AI, sharing or other grant.
  Propagation still acts only on the purposes it covers.
* ``app.merged_guests`` lists the guests merged into an account. The erasure
  worker also tombstones those guests' IDs, so a backup taken before the
  merge cannot bring back the guest's copy of deleted data.
* A guest's push bindings follow it into the account on transfer, so they
  are erased with the account instead of outliving it.

Revision ID: 0009_restore_and_transfer
Revises: 0008_notifications
"""
from __future__ import annotations

from alembic import op

revision = "0009_restore_and_transfer"
down_revision = "0008_notifications"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE OR REPLACE FUNCTION app.queue_withdrawal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
BEGIN
  INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, created_at)
  VALUES ('evt.withdrawn.' || NEW.sequence, 'permission.withdrawn', NEW.subject_id, NEW.event_id,
          jsonb_build_object('purpose_id', NEW.purpose_id, 'scope_kind', NEW.scope_kind,
                             'scope_ref', NEW.scope_ref, 'decision', NEW.decision,
                             'notice_version', NEW.notice_version, 'recorded_at', NEW.recorded_at),
          'permission-withdrawn:' || NEW.event_id, NEW.recorded_at)
  ON CONFLICT (dedupe_key) DO NOTHING;
  RETURN NULL;
END
$f$;
DROP TRIGGER withdrawal_propagation ON app.permission_event;
CREATE TRIGGER withdrawal_propagation AFTER INSERT ON app.permission_event
  FOR EACH ROW WHEN (NEW.decision IN ('WITHDRAW', 'DENY'))
  EXECUTE FUNCTION app.queue_withdrawal();

CREATE FUNCTION app.merged_guests(p_account text) RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$ SELECT principal_id FROM app.principal WHERE transferred_to = p_account ORDER BY principal_id $f$;
REVOKE ALL ON FUNCTION app.merged_guests(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.merged_guests(text) TO princess_worker;

CREATE FUNCTION app.move_guest_devices() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
BEGIN
  UPDATE app.push_installation SET owner_id = NEW.transferred_to WHERE owner_id = NEW.principal_id;
  RETURN NULL;
END
$f$;
REVOKE ALL ON FUNCTION app.move_guest_devices() FROM PUBLIC;
CREATE TRIGGER guest_devices_follow_transfer AFTER UPDATE OF transferred_to ON app.principal
  FOR EACH ROW WHEN (OLD.transferred_to IS NULL AND NEW.transferred_to IS NOT NULL)
  EXECUTE FUNCTION app.move_guest_devices();
"""

DOWNGRADE = """
DROP TRIGGER guest_devices_follow_transfer ON app.principal;
DROP FUNCTION app.move_guest_devices();
DROP FUNCTION app.merged_guests(text);
DROP TRIGGER withdrawal_propagation ON app.permission_event;
CREATE TRIGGER withdrawal_propagation AFTER INSERT ON app.permission_event
  FOR EACH ROW WHEN (NEW.purpose_id IN ('service_processing', 'image_retention')
                     AND NEW.decision IN ('WITHDRAW', 'DENY'))
  EXECUTE FUNCTION app.queue_withdrawal();
CREATE OR REPLACE FUNCTION app.queue_withdrawal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
BEGIN
  INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, created_at)
  VALUES ('evt.withdrawn.' || NEW.sequence, 'permission.withdrawn', NEW.subject_id, NEW.event_id,
          jsonb_build_object('purpose_id', NEW.purpose_id, 'scope_kind', NEW.scope_kind,
                             'scope_ref', NEW.scope_ref, 'decision', NEW.decision),
          'permission-withdrawn:' || NEW.event_id, NEW.recorded_at)
  ON CONFLICT (dedupe_key) DO NOTHING;
  RETURN NULL;
END
$f$;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
