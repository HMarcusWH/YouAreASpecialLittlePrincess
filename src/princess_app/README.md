# Source-tree product application

`domain` and `application` own product semantics; `ports` define typed boundaries; `adapters` provide persistence/provider implementations. This code is intentionally outside the Free distribution and runs with the backend lock.

Read [architecture](../../docs/architecture/overview.md), [lifecycles](../../docs/architecture/data-and-lifecycles.md), [connectors](../../docs/connectors/README.md) and [tests](../../docs/development/testing.md). In-memory/fake implementations remain fixtures, not a fallback for failed live configuration. Preserve RLS, leases, permission epochs, immutable publication, ledger uniqueness and forward deletion tombstones.
