# ADR-002 — Managed identity and stable internal accounts

[Index](README.md) · [Identity port](../connectors/identity.md) · [Data model](../roadmap/01-data-architecture.md).

Status: IMPLEMENTATION_DEFAULT for managed OIDC; vendor RESEARCH_REQUIRED before T02 live adapter.

Use an established identity provider; do not build password storage or mint a parallel social-login system. Candidate comparison includes Clerk and Supabase Auth or an explicitly justified equivalent. Compare native Apple/Google flows, PKCE/callback support, private relay, account linking/deletion, JWT/JWKS behavior, region/retention, rate/cost limits and test tooling. No vendor account/contract is approved here.

Our principal ID and `(issuer, subject)` binding own identity continuity. Email matching is not proof for account merging. Guest migration and purchase ownership remain application transactions. Provider replacement must preserve principals with proven relinking/recovery, not reconstruct accounts from email addresses.

Acceptance: wrong issuer/audience, rotated keys, expired/revoked sessions, cross-owner access, guest migration races, native login recovery and account deletion all tested. Record exact SDK/configuration and allowed callback domains. Production gate requires approved provider tenant/data handling and working web/native identity flows.
