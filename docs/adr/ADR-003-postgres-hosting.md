# ADR-003 — PostgreSQL persistence and durable queue foundation

[Index](README.md) · [Data](../roadmap/01-data-architecture.md) · [Environments](../roadmap/15-environments-deployment-and-secrets.md).

Status: IMPLEMENTATION_DEFAULT for PostgreSQL/SQLAlchemy/Alembic; managed host pending T02/T24 decision.

Begin with a modular application and one PostgreSQL service using separate schemas/roles as needed. Use reviewed migrations, explicit constraints, owner-scoped access and transactional outbox/job records. Short queue-claim transactions with leases/fences are sufficient initially; no Redis/Celery/Kubernetes requirement absent measured need. Long CPU/model work stays outside SQL transactions.

Managed Supabase/Neon or another approved PostgreSQL host must be evaluated for region, backup/PITR/restore, connection pooling, roles/RLS, branch/preview privacy, limits and costs. A hosted auth/storage bundle does not require letting clients bypass our application authority.

Acceptance: real PostgreSQL integration tests under runtime non-owner roles, migration compatibility/rollback, concurrent job/credit behavior, backup/tombstone restore and source JSON/relational projection consistency. SQLite unit substitutes do not prove locking/RLS behavior. Future queue/database scaling needs measured evidence and a migration plan preserving ledger/idempotency.
