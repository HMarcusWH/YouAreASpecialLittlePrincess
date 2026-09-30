"""Privacy-safe cross-tenant operational aggregates for T24.

The runtime application role remains RLS-scoped and cannot enumerate another
principal's rows. These SECURITY DEFINER functions expose only fixed,
low-cardinality aggregate observations and the Alembic revision required by
the provider-neutral operational snapshot.
"""
from __future__ import annotations

from alembic import op

revision = "0011_operational_snapshot"
down_revision = "0010_provider_attempt"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE FUNCTION app.operational_snapshot(p_now timestamptz)
RETURNS TABLE (
  source text,
  category text,
  state text,
  item_count bigint,
  oldest_age_s bigint,
  max_attempts bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$
  SELECT 'jobs'::text,
         CASE WHEN j.kind IN ('analysis', 'premium', 'export') THEN j.kind ELSE 'other' END,
         lower(j.state),
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(j.created_at)))::bigint),
         max(j.attempts)::bigint
    FROM app.job j
   WHERE j.state IN ('QUEUED', 'LEASED')
   GROUP BY 2, 3

  UNION ALL

  SELECT 'outbox'::text,
         CASE
           WHEN o.topic IN (
             'capture.deletion_requested', 'capture.retention_review',
             'account.deletion_requested', 'upload.rejected',
             'asset.erasure_requested', 'permission.withdrawn',
             'sessions.revoked', 'push.unregistered', 'feedback.withdrawn'
           ) THEN 'privacy'
           WHEN o.topic = 'report.ready' THEN 'notification'
           ELSE 'other'
         END,
         'pending'::text,
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(o.created_at)))::bigint),
         NULL::bigint
    FROM app.outbox_event o
   WHERE o.dispatched_at IS NULL
   GROUP BY 2

  UNION ALL

  SELECT 'notifications'::text,
         lower(n.channel),
         lower(n.state),
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(n.created_at)))::bigint),
         max(n.attempts)::bigint
    FROM app.notification_delivery n
   WHERE n.state IN ('PENDING', 'FAILED')
   GROUP BY 2, 3

  UNION ALL

  SELECT 'payment_events'::text,
         p.rail,
         'pending'::text,
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(p.received_at)))::bigint),
         NULL::bigint
    FROM app.provider_event p
   WHERE p.processed_at IS NULL
   GROUP BY p.rail

  UNION ALL

  SELECT 'commerce_completion'::text,
         'all'::text,
         'pending'::text,
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(f.granted_at)))::bigint),
         NULL::bigint
    FROM app.financial_transaction f
   WHERE f.completed_at IS NULL
  HAVING count(*) > 0

  UNION ALL

  SELECT 'credit_reservations'::text,
         'all'::text,
         'reserved'::text,
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(c.created_at)))::bigint),
         NULL::bigint
    FROM app.credit_reservation c
   WHERE c.state = 'RESERVED'
  HAVING count(*) > 0

  UNION ALL

  SELECT 'premium_attempts'::text,
         'all'::text,
         lower(a.state),
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(a.created_at)))::bigint),
         max(a.attempt_number)::bigint
    FROM app.provider_attempt a
   WHERE a.state IN ('STARTED', 'AMBIGUOUS')
   GROUP BY a.state

  UNION ALL

  SELECT 'exports'::text,
         'all'::text,
         lower(e.state),
         count(*)::bigint,
         greatest(0::bigint, floor(extract(epoch FROM p_now - min(e.created_at)))::bigint),
         NULL::bigint
    FROM app.report_export e
   WHERE e.state IN ('QUEUED', 'FAILED')
   GROUP BY e.state

   ORDER BY 1, 2, 3
$f$;

CREATE FUNCTION app.operational_schema_revision() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$ SELECT version_num FROM public.alembic_version LIMIT 1 $f$;

REVOKE ALL ON FUNCTION app.operational_snapshot(timestamptz), app.operational_schema_revision() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.operational_snapshot(timestamptz), app.operational_schema_revision()
  TO princess_app;
"""

DOWNGRADE = """
DROP FUNCTION app.operational_schema_revision();
DROP FUNCTION app.operational_snapshot(timestamptz);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
