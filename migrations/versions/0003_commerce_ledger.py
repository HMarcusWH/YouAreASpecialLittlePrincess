"""Commerce ledger (T19): accounts, intents, verified event inbox, unique
financial grants, credit lots, reservations, append-only ledger entries and
saved Premium overlays.

Revision ID: 0003_commerce_ledger
Revises: 0002_intake_and_jobs
"""
from __future__ import annotations

from alembic import op

revision = "0003_commerce_ledger"
down_revision = "0002_intake_and_jobs"
branch_labels = None
depends_on = None

OPAQUE = r"'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
SHA = r"'^[0-9a-f]{64}$'"
RAILS = "('stripe', 'apple_app_store', 'google_play')"

UPGRADE = f"""
-- Our opaque per-account token handed to providers (never derived from email).
CREATE TABLE app.payment_account (
  owner_id text PRIMARY KEY REFERENCES app.principal (principal_id) DEFERRABLE INITIALLY IMMEDIATE,
  account_ref text NOT NULL UNIQUE CHECK (account_ref ~ {OPAQUE}),
  created_at timestamptz NOT NULL
);

CREATE TABLE app.purchase_intent (
  intent_ref text PRIMARY KEY CHECK (intent_ref ~ {OPAQUE}),
  owner_id text NOT NULL REFERENCES app.principal (principal_id) DEFERRABLE INITIALLY IMMEDIATE,
  rail text NOT NULL CHECK (rail IN {RAILS}),
  product_id text NOT NULL CHECK (product_id ~ {OPAQUE}),
  created_at timestamptz NOT NULL
);

-- Verified provider notifications. Holds no owner or account data, only
-- identifiers, a body digest and how the event was applied.
CREATE TABLE app.provider_event (
  rail text NOT NULL CHECK (rail IN {RAILS}),
  environment text NOT NULL,
  event_id text NOT NULL CHECK (length(event_id) BETWEEN 1 AND 256),
  event_type text NOT NULL CHECK (length(event_type) BETWEEN 1 AND 128),
  body_sha256 text NOT NULL CHECK (body_sha256 ~ {SHA}),
  received_at timestamptz NOT NULL,
  processed_at timestamptz,
  outcome text,
  PRIMARY KEY (rail, environment, event_id)
);

-- One row per financial identity: at most one grant, ever.
CREATE TABLE app.financial_transaction (
  txn_id text PRIMARY KEY CHECK (txn_id ~ {OPAQUE}),
  owner_id text NOT NULL REFERENCES app.principal (principal_id) DEFERRABLE INITIALLY IMMEDIATE,
  rail text NOT NULL CHECK (rail IN {RAILS}),
  environment text NOT NULL,
  transaction_ref text NOT NULL CHECK (length(transaction_ref) BETWEEN 1 AND 512),
  product_id text NOT NULL,
  quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 100),
  observed_state text NOT NULL,
  completion_action text NOT NULL,
  completed_at timestamptz,
  granted_at timestamptz NOT NULL,
  refunded_at timestamptz,
  UNIQUE (rail, environment, transaction_ref),
  UNIQUE (owner_id, txn_id)
);

CREATE TABLE app.credit_lot (
  lot_id text PRIMARY KEY CHECK (lot_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  txn_id text NOT NULL UNIQUE,
  origin_rail text NOT NULL CHECK (origin_rail IN {RAILS}),
  product_id text NOT NULL,
  credits integer NOT NULL CHECK (credits > 0),
  available integer NOT NULL CHECK (available >= 0 AND available <= credits),
  state text NOT NULL CHECK (state IN ('ACTIVE', 'REVOKED')),
  created_at timestamptz NOT NULL,
  revoked_at timestamptz,
  UNIQUE (owner_id, lot_id),
  FOREIGN KEY (owner_id, txn_id) REFERENCES app.financial_transaction (owner_id, txn_id)
    ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  CHECK ((state = 'REVOKED') = (revoked_at IS NOT NULL)),
  CHECK (state = 'ACTIVE' OR available = 0)
);

CREATE TABLE app.credit_reservation (
  reservation_id text PRIMARY KEY CHECK (reservation_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  lot_id text NOT NULL,
  operation_key text NOT NULL UNIQUE,
  state text NOT NULL CHECK (state IN ('RESERVED', 'SPENT', 'RELEASED', 'REVOKED')),
  created_at timestamptz NOT NULL,
  settled_at timestamptz,
  FOREIGN KEY (owner_id, lot_id) REFERENCES app.credit_lot (owner_id, lot_id)
    ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
  CHECK ((state = 'RESERVED') = (settled_at IS NULL))
);
CREATE INDEX credit_reservation_lot ON app.credit_reservation (lot_id, state);

-- Append-only accounting trail; balances are derived, never client-written.
CREATE TABLE app.ledger_entry (
  entry_id bigserial PRIMARY KEY,
  owner_id text NOT NULL REFERENCES app.principal (principal_id) DEFERRABLE INITIALLY IMMEDIATE,
  lot_id text NOT NULL,
  reservation_id text,
  kind text NOT NULL CHECK (kind IN ('GRANT', 'RESERVE', 'RELEASE', 'SPEND', 'REVOKE', 'REFUND_AFTER_SPEND')),
  delta integer NOT NULL,
  reason text,
  recorded_at timestamptz NOT NULL
);

CREATE TABLE app.premium_overlay (
  overlay_id text PRIMARY KEY CHECK (overlay_id ~ {OPAQUE}),
  owner_id text NOT NULL,
  report_id text NOT NULL,
  revision integer NOT NULL CHECK (revision > 1),
  job_id text NOT NULL UNIQUE,
  reservation_id text NOT NULL UNIQUE,
  packet_digest text NOT NULL CHECK (packet_digest ~ {SHA}),
  output_digest text NOT NULL CHECK (output_digest ~ {SHA}),
  packet jsonb NOT NULL,
  output jsonb NOT NULL,
  omissions jsonb NOT NULL,
  model_returned text,
  created_at timestamptz NOT NULL,
  FOREIGN KEY (owner_id, report_id) REFERENCES app.report (owner_id, report_id)
    ON UPDATE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['payment_account', 'purchase_intent', 'financial_transaction', 'credit_lot',
                           'credit_reservation', 'ledger_entry', 'premium_overlay'] LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY owner_isolation ON app.%I TO princess_app
                    USING (owner_id = app.current_principal()) WITH CHECK (owner_id = app.current_principal())', t);
  END LOOP;
END $$;

-- The completion worker (consume/acknowledge after grant) scans every owner's grants.
CREATE POLICY worker_completion ON app.financial_transaction TO princess_worker USING (true) WITH CHECK (true);

GRANT SELECT, INSERT ON app.payment_account, app.purchase_intent, app.ledger_entry, app.premium_overlay
  TO princess_app;
GRANT SELECT, INSERT, UPDATE ON app.financial_transaction, app.credit_lot, app.credit_reservation,
  app.provider_event TO princess_app;
GRANT USAGE ON SEQUENCE app.ledger_entry_entry_id_seq TO princess_app;

-- Webhooks arrive without a principal: resolve the owner for a provider-attested
-- account token or an already granted transaction, then act in that context.
CREATE FUNCTION app.resolve_payment_owner(p_account_ref text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$ SELECT owner_id FROM app.payment_account WHERE account_ref = p_account_ref $f$;

CREATE FUNCTION app.resolve_transaction_owner(p_rail text, p_environment text, p_ref text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, pg_temp AS
$f$ SELECT owner_id FROM app.financial_transaction
    WHERE rail = p_rail AND environment = p_environment AND transaction_ref = p_ref $f$;

REVOKE ALL ON FUNCTION app.resolve_payment_owner(text), app.resolve_transaction_owner(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.resolve_payment_owner(text), app.resolve_transaction_owner(text, text, text)
  TO princess_app;
"""

DOWNGRADE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM app.financial_transaction) OR EXISTS (SELECT 1 FROM app.provider_event)
     OR EXISTS (SELECT 1 FROM app.premium_overlay) THEN
    RAISE EXCEPTION 'refusing to drop financial history';
  END IF;
END $$;
DROP FUNCTION app.resolve_transaction_owner(text, text, text);
DROP FUNCTION app.resolve_payment_owner(text);
DROP TABLE app.premium_overlay;
DROP TABLE app.ledger_entry;
DROP TABLE app.credit_reservation;
DROP TABLE app.credit_lot;
DROP TABLE app.financial_transaction;
DROP TABLE app.provider_event;
DROP TABLE app.purchase_intent;
DROP TABLE app.payment_account;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
