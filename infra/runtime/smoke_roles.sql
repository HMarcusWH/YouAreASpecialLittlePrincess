\set ON_ERROR_STOP on
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_smoke_api') THEN
    CREATE ROLE princess_smoke_api LOGIN PASSWORD 'smoke-only-api' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE IN ROLE princess_app;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'princess_smoke_worker') THEN
    CREATE ROLE princess_smoke_worker LOGIN PASSWORD 'smoke-only-worker' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE IN ROLE princess_worker;
  END IF;
END $$;
GRANT princess_app TO princess_smoke_api;
GRANT princess_worker TO princess_smoke_worker;
