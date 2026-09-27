"""Durable erasure follow-ups.

* Withdrawing or denying ``service_processing`` or ``image_retention``
  queues ``permission.withdrawn`` in the transaction that records the
  decision, so its effects (tombstones, byte erasure) survive a crash between
  the permission commit and the API's immediate propagation.
* ``app.erase_capture_records`` removes a deleted capture's analysis records
  (runs, measurements, regions, evidence, reports, exports, Premium overlays)
  once its bytes are verified erased. The capture and upload rows stay as
  tombstones.
* ``app.expire_upload_slots`` revokes reserved or abandoned upload slots past
  their expiry and queues erasure of any bytes uploaded to them.
* ``app.review_idle_captures`` queues the retention review for completed
  captures that never went on to an analysis.

Revision ID: 0006_durable_erasure
Revises: 0005_report_exports
"""
from __future__ import annotations

from alembic import op

revision = "0006_durable_erasure"
down_revision = "0005_report_exports"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE FUNCTION app.queue_withdrawal() RETURNS trigger
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
REVOKE ALL ON FUNCTION app.queue_withdrawal() FROM PUBLIC;
CREATE TRIGGER withdrawal_propagation AFTER INSERT ON app.permission_event
  FOR EACH ROW WHEN (NEW.purpose_id IN ('service_processing', 'image_retention')
                     AND NEW.decision IN ('WITHDRAW', 'DENY'))
  EXECUTE FUNCTION app.queue_withdrawal();

CREATE FUNCTION app.erase_capture_records(p_owner text, p_capture text, p_at timestamptz) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_runs text[];
  v_reports text[];
  v_res record;
  v_restored integer;
BEGIN
  PERFORM 1 FROM app.capture WHERE owner_id = p_owner AND capture_id = p_capture AND deleted_at IS NOT NULL
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'capture_not_deleted' USING ERRCODE = 'P0002';
  END IF;
  SELECT coalesce(array_agg(run_id), '{}') INTO v_runs FROM app.analysis_run
    WHERE owner_id = p_owner AND capture_id = p_capture;
  SELECT coalesce(array_agg(report_id), '{}') INTO v_reports FROM app.report
    WHERE owner_id = p_owner AND run_id = ANY(v_runs);
  SET CONSTRAINTS ALL DEFERRED;
  -- Premium work for these reports ends; each open reservation's credit goes back.
  FOR v_res IN
    UPDATE app.credit_reservation r SET state = 'RELEASED', settled_at = p_at
    FROM app.job j WHERE j.kind = 'premium' AND j.owner_id = p_owner AND j.subject_ref = ANY(v_reports)
      AND j.payload->>'reservation_id' = r.reservation_id AND r.state = 'RESERVED'
    RETURNING r.reservation_id, r.lot_id
  LOOP
    UPDATE app.credit_lot SET available = available + 1 WHERE lot_id = v_res.lot_id AND state = 'ACTIVE';
    GET DIAGNOSTICS v_restored = ROW_COUNT;
    INSERT INTO app.ledger_entry (owner_id, lot_id, reservation_id, kind, delta, reason, recorded_at)
      VALUES (p_owner, v_res.lot_id, v_res.reservation_id, 'RELEASE', v_restored, 'report_deleted', p_at);
  END LOOP;
  UPDATE app.job SET state = 'CANCELLED', lease_owner = NULL, lease_expires_at = NULL,
    last_error = 'report_deleted', updated_at = p_at
    WHERE kind = 'premium' AND owner_id = p_owner AND subject_ref = ANY(v_reports) AND state IN ('QUEUED', 'LEASED');
  DELETE FROM app.premium_overlay WHERE owner_id = p_owner AND report_id = ANY(v_reports);
  DELETE FROM app.report WHERE owner_id = p_owner AND report_id = ANY(v_reports);  -- revisions, exports
  DELETE FROM app.job WHERE kind = 'analysis' AND owner_id = p_owner AND subject_ref = ANY(v_runs);
  DELETE FROM app.analysis_run WHERE owner_id = p_owner AND run_id = ANY(v_runs);  -- measurements, regions
  RETURN coalesce(array_length(v_reports, 1), 0);
END
$f$;

CREATE FUNCTION app.expire_upload_slots(p_now timestamptz, p_limit integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_count integer;
BEGIN
  WITH expired AS (
    UPDATE app.upload SET state = 'REVOKED' WHERE upload_id IN (
      SELECT upload_id FROM app.upload
      WHERE (state = 'RESERVED' AND expires_at < p_now)
         OR (state = 'COMPLETING' AND expires_at < p_now - interval '15 minutes')  -- a crashed completion
      ORDER BY expires_at LIMIT p_limit FOR UPDATE SKIP LOCKED)
    RETURNING owner_id, upload_id, asset_id)
  INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, created_at)
    SELECT 'evt.upload_expired.' || upload_id, 'upload.rejected', owner_id, upload_id,
           jsonb_build_object('asset_id', asset_id), 'upload-expired:' || upload_id, p_now FROM expired
    ON CONFLICT (dedupe_key) DO NOTHING;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END
$f$;

-- A capture that never went on to an analysis (the browser closed before the
-- permission was recorded) is reviewed like any finished one: its original is
-- erased unless image retention covers it.
CREATE FUNCTION app.review_idle_captures(p_now timestamptz, p_idle_seconds integer, p_limit integer)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
DECLARE
  v_count integer;
BEGIN
  INSERT INTO app.outbox_event (event_id, topic, owner_id, aggregate_ref, payload, dedupe_key, created_at)
    SELECT 'evt.idle_capture.' || c.capture_id, 'capture.retention_review', c.owner_id, c.capture_id,
           '{}'::jsonb, 'idle-capture:' || c.capture_id, p_now
    FROM app.capture c JOIN app.asset a ON a.asset_id = c.asset_id
    WHERE c.deleted_at IS NULL AND a.deleted_at IS NULL
      AND c.created_at < p_now - make_interval(secs => p_idle_seconds)
      AND NOT EXISTS (SELECT 1 FROM app.analysis_run r WHERE r.capture_id = c.capture_id)
      AND NOT EXISTS (SELECT 1 FROM app.outbox_event o WHERE o.dedupe_key = 'idle-capture:' || c.capture_id)
    ORDER BY c.created_at LIMIT p_limit
  ON CONFLICT (dedupe_key) DO NOTHING;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END
$f$;

REVOKE ALL ON FUNCTION app.erase_capture_records(text, text, timestamptz),
  app.expire_upload_slots(timestamptz, integer), app.review_idle_captures(timestamptz, integer, integer)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.erase_capture_records(text, text, timestamptz),
  app.expire_upload_slots(timestamptz, integer), app.review_idle_captures(timestamptz, integer, integer)
  TO princess_worker;
"""

DOWNGRADE = """
DROP FUNCTION app.review_idle_captures(timestamptz, integer, integer);
DROP FUNCTION app.expire_upload_slots(timestamptz, integer);
DROP FUNCTION app.erase_capture_records(text, text, timestamptz);
DROP TRIGGER withdrawal_propagation ON app.permission_event;
DROP FUNCTION app.queue_withdrawal();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
