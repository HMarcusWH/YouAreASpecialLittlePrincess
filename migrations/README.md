# PostgreSQL migration and role guide

The ordered source revisions are under `versions/`; the [generated migration inventory](../docs/reference/command-inventory.md#migration-inventory) lists their declared IDs and predecessors. Run upgrades through `python -m princess_app.adapters.postgres.migrate upgrade` with `PRINCESS_MIGRATION_DATABASE_URL`, not by executing individual revision files.

Fresh local role setup is in [local setup](../docs/development/local-setup.md). Runtime logins use reviewed application/worker group roles and must not own tables or have superuser/BYPASSRLS. The migration/admin connection is separate. Composite ownership and immutable report/evidence semantics are not optional client-side filters.

Back up and qualify real provider migrations under their owner scope. Application rollback keeps the database forward and promotes a separately built previous application artifact; do not downgrade a populated schema as an incident shortcut. Follow [rollback/restore runbooks](../docs/runbooks/README.md). This documentation update adds no migration.
