# ADR-002 — Managed identity and stable internal accounts

[Index](README.md) · [Identity port](../connectors/identity.md) · [Data model](../roadmap/01-data-architecture.md).

Status: IMPLEMENTATION_DEFAULT for managed identity behind stable internal principals; vendor and exact API credential/session profile RESEARCH_REQUIRED before live composition.

Use an established identity provider; do not build password storage or mint a parallel social-login system. Candidate comparison includes Clerk and Supabase Auth or an explicitly justified equivalent. Compare native Apple/Google flows, PKCE/callback support, private relay, account linking/deletion, JWT/JWKS behavior, region/retention, rate/cost limits and test tooling. No vendor account/contract is approved here.

Before binding a vendor, choose the exact credential the FastAPI API verifies (for example a provider session credential or an OAuth/OIDC API credential) and prove its audience, key source and lifecycle. Do not infer reauthentication from JWT issuance time: `iat` is not `auth_time`. The application persists `revoked_before` for logout-everywhere/deletion and requires trustworthy authentication freshness after that fence. A provider that cannot supply compatible freshness must use a reviewed provider-revocation/application-session design rather than weakening the fence. The existing generic OIDC adapter remains ID-token-shaped until this decision is made; this ADR does not authorize accepting additional token types.

Our principal ID and `(issuer, subject)` binding own identity continuity. Email matching is not proof for account merging. Guest migration and purchase ownership remain application transactions. Provider replacement must preserve principals with proven relinking/recovery, not reconstruct accounts from email addresses.

Acceptance: wrong issuer/audience, rotated keys, expired credentials, old/unknown authentication freshness after local revocation, provider/session revocation behavior, cross-owner access, guest migration races, native login recovery and account deletion all tested. Newly issued credentials without a proven new authentication must not bypass logout/deletion. Record exact credential profile, SDK/configuration and allowed callback domains. Production gate requires approved provider tenant/data handling and working web/native identity flows.
