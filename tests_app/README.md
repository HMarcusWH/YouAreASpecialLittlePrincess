# PostgreSQL application tests

Run `python -m pytest -q tests_app` with `PRINCESS_TEST_DATABASE_URL` targeting a disposable real PostgreSQL database and the reviewed backend dependencies. These tests are not included by default `pytest` discovery.

Follow [setup/testing](../docs/development/testing.md) for isolated roles/database. Do not run concurrently with destructive web/native E2E scripts against the same `princess_test`. RLS/transaction/fencing evidence must come from PostgreSQL, not an SQLite substitute. Real provider/store/device qualification is separate.
