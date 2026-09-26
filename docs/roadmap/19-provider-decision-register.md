# 19 — Engineering defaults, vendor decisions and human approvals

[Index](00-index.md) · [ADR index](../adr/README.md) · [Connectors](../connectors/README.md) · [Sources](22-research-and-source-refresh.md) · [Release gates](21-release-readiness-checklists.md).

## Decision states

`IMPLEMENTATION_DEFAULT` is the engineering direction this plan proposes for coding agents after merge. `CANDIDATE` is not a selected vendor. `RESEARCH_REQUIRED` blocks the affected real adapter choice, not fixture/port work. `PRODUCTION_APPROVED` requires a named human owner, dated evidence and a scope/environment; no such approval is fabricated here.

| Decision | Direction | Open before implementation/activation | Owner/task |
|---|---|---|---|
| ADR-001 | Next.js web presentation and thin session layer; FastAPI remains business authority | Exact compatible versions, deployment profile, cookie/origin contract | T17/T28 |
| ADR-002 | Managed OIDC identity behind an internal principal/identity binding | Compare Clerk/Supabase Auth or approved equivalent for native Apple/Google login, deletion, region and cost; choose one | T02/T27 |
| ADR-003 | PostgreSQL + SQLAlchemy/Alembic; local DB tests and non-owner roles | Managed host/region/backups/PITR/pooling contract; Supabase/Neon candidates, not approvals | T02/T24 |
| ADR-004 | S3-shaped private storage port with provider capability tests | R2/S3 candidate choice, jurisdiction, checksum/version/copy/delete semantics and egress pricing | T04/T27 |
| ADR-005 | Expo/RN/Router native app; shared contract/state/tokens, native platform UX | Exact SDK/native bridge/build compatibility, minimum OS, generated-native ownership, signing/build provider approval | T29 |
| ADR-006 | Internal ledger; Stripe web candidate; direct StoreKit/Play server verification as default | Native bridge/library selection, RevenueCat comparison, catalog/consumable portability/terms/storefront policy | T19/T29 |
| ADR-007 | Outbox-driven transactional mail; Resend candidate or equivalent | Sender domains, identity email separation, retention/region, bounce/retry behavior, contract | T02/T24 |
| ADR-008 | OTel-compatible operational telemetry; explicit product-event allowlist | Export destination, SDK privacy, retention, alerts and support access | T28/T24 |
| ADR-009 | Layered quotas, web challenge candidate, native integrity signals | Abuse provider data use, fallback behavior, account/device policy | T04/T29 |

[ADR files](../adr/README.md) contain the rationale and exit/acceptance conditions. This table does not authorize account provisioning or paid usage.

## Required provider decision record

For every real connector record: provider and SDK/API version; internal port/capability profile; supported environments/platforms; source links and checked date; transmitted data categories; region/storage/retention/deletion behavior; subprocessors/contract evidence; secrets and least-privilege role; rate limits/retries; cost model; sandbox tests; unsupported cases; incident/exit procedure; implementation owner; production approver.

Do not equate an EU marketing region with complete residency, a version pin with authenticated artifacts, or a provider's compliant product with our app's legal compliance. Verify account-specific data settings and native storefront rules before activation. SDKs may make additional telemetry calls; audit them before treating a client as private.

## Owner gates

The task graph names gates including protocol/rights, actual participant permission, calibration, benchmark promotion, approved model account/data/spend, approved product/price/refund/tax terms, design acceptance, provider processor contracts, native account/signing authority, store policy/review and public release signoff. A gate record must name purpose, scope, evidence, approver, approval date, expiration/review trigger and relevant environment. Unknown is not approved.

Do not put private contracts or keys into the repo. Store safe references/redacted decision summaries. Agents may write draft records and fakes but must leave approval fields pending. Tasks can complete implementation with production disabled where their acceptance explicitly permits that; T25 cannot.

## Policy refresh triggers

Recheck provider/store requirements before SDK upgrades, new regions, alternative payment methods, age-scope changes, new data categories, content sharing, live model changes and each store release candidate. Compare actual API support and account settings rather than copying old example model IDs, prices, deadlines or broad payment exceptions. [22](22-research-and-source-refresh.md) records what this research pass verified and what still needs account-level confirmation.
