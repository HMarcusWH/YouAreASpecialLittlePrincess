# Architecture decisions

[Roadmap index](../roadmap/00-index.md) · [Provider register](../roadmap/19-provider-decision-register.md) · [Connector index](../connectors/README.md).

These records document the engineering defaults proposed by roadmap v2.0. Merging the plan adopts a build direction, not provider procurement, account approval, live spend or a tested SDK version. Change a direction with rationale, impact on contracts/clients/data, tests and migration/rollback; do not silently introduce an alternate stack.

| Record | Direction |
|---|---|
| [ADR-001](ADR-001-client-architecture.md) | Next.js web presentation; FastAPI business authority |
| [ADR-002](ADR-002-auth-provider.md) | Supabase Auth selected; staging/sandbox exact-profile qualification passed; processor/runtime and production/live activation pending |
| [ADR-003](ADR-003-postgres-hosting.md) | PostgreSQL with migrations/roles and durable jobs |
| [ADR-004](ADR-004-object-storage.md) | Private S3-shaped storage with capability tests |
| [ADR-005](ADR-005-mobile-framework.md) | Expo/RN native app, shared semantics not webview |
| [ADR-006](ADR-006-payments.md) | Internal ledger with web/Apple/Play adapters |
| [ADR-007](ADR-007-email.md) | Outbox transactional mail |
| [ADR-008](ADR-008-observability.md) | OTel-compatible operations, allowlisted analytics |
| [ADR-009](ADR-009-abuse-protection.md) | Layered quotas and platform risk signals |

Every decision implementation records exact versions, source date, compatibility spike, owner, production gate and exit path. Missing vendor selection must block the affected real adapter, not fake-contract development. No record below is a legal compliance certificate.
