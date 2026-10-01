# ADR-002 — Managed identity and stable internal accounts

[Index](README.md) · [Identity port](../connectors/identity.md) · [Data model](../roadmap/01-data-architecture.md).

Status: IMPLEMENTATION_DEFAULT for managed identity behind stable internal principals; Supabase Auth has a code-qualified **CANDIDATE** first-party access-token profile, Clerk remains an alternative, and no production vendor/account is selected or approved.

Use an established identity provider; do not build password storage or mint a parallel social-login system. Supabase Auth is now the first code-qualified candidate; Clerk remains an alternative rather than a rejected option. The Supabase candidate is deliberately narrow: first-party access JWTs, configured singleton audience/roles, canonical UUID subject/session, non-anonymous sessions, asymmetric project signing, and the stock claims profile with no unaudited Custom Access Token Hook. Compare native Apple/Google flows, PKCE/callback support, private relay, account linking/deletion, JWT/JWKS behavior, region/retention, rate/cost limits and test tooling before selection. No vendor account/contract is approved here.

Before binding a vendor, choose the exact credential the FastAPI API verifies (for example a provider session credential or an OAuth/OIDC API credential) and prove its provider-specific verification context, key source and lifecycle. Audience, authorized-party, tenant or equivalent rules belong inside the selected adapter rather than in `IdentityService`; providers are not required to expose an OAuth/OIDC `aud` claim merely because the current generic OIDC profile does. Do not infer reauthentication from JWT issuance time: `iat` is not `auth_time`. The application persists `revoked_before` for logout-everywhere/deletion and requires trustworthy authentication freshness after that fence. A provider that cannot supply compatible freshness must use a reviewed provider-revocation/application-session design rather than weakening the fence. The existing generic OIDC adapter remains ID-token-shaped until this decision is made; this ADR does not authorize accepting additional token types.

Our principal ID and `(issuer, subject)` binding own identity continuity. Email matching is not proof for account merging. Guest migration and purchase ownership remain application transactions. Provider replacement must preserve principals with proven relinking/recovery, not reconstruct accounts from email addresses.

Acceptance: wrong issuer/audience/role/profile, symmetric/rotated keys, expired credentials, malformed/unknown AMR, old/unknown authentication freshness after local revocation, provider/session revocation behavior, cross-owner access, guest migration races, native login recovery and account deletion all tested. Newly issued credentials without a proven new authentication must not bypass logout/deletion. Record exact credential profile, SDK/configuration and allowed callback domains. Production gate requires approved provider tenant/data handling and working web/native identity flows.


## Provider decision evidence (2026-10-01)

The current primary-source comparison is recorded in [T17 identity-provider decision evidence](../ci/T17_IDENTITY_PROVIDER_DECISION_EVIDENCE.md). It closes the public-document research gap but **does not select a provider**.

Both Supabase and Clerk document web PKCE plus native Apple/Google paths compatible in principle with the existing web/native transport boundaries. The comparison also records material differences that must survive the Princess invariants before selection: Supabase offers selectable project regions and already has a Princess-qualified access-JWT/JWKS/freshness candidate; Clerk documents strong native/session tooling but automatically attempts OAuth account linking on matching verified email addresses, which requires an explicit compatibility decision because Princess does not treat email equality as account-merge proof. Clerk's signed factor-verification-age/reverification model is also not yet Princess-qualified against the durable `revoked_before` fence.

Supabase therefore remains a code-qualified **CANDIDATE**, not an owner-selected provider. Clerk remains an alternative with public-source review complete but Princess-specific credential/freshness/principal-continuity qualification pending. Account-specific processor terms, region/data handling, retention/deletion/support, actual callback/native credentials and the Supabase `MANAGED_PROJECT` witness remain separate evidence gates.


For the Supabase candidate, the reviewed implementation source is `supabase/auth@ce9a8eee0cc042be8c7a42981a7ddae631e41d91`, not evidence about any future managed project's deployed version. Its current stock access-token path emits session AMR from persisted authentication claims, so a refresh changes JWT issuance time without automatically advancing Princess `auth_time`. The candidate adapter encodes that property and fails closed when usable AMR freshness is absent. Actual project qualification must confirm issuer, audience, roles, asymmetric signing/JWKS, Custom Access Token Hook state and refresh/reauthentication behavior before composition.


## Managed-project qualification harness

T17 provides `tools/qualify_supabase_identity.py` and the evidence boundary in
`docs/ci/T17_SUPABASE_IDENTITY_QUALIFICATION.md`. Synthetic regression coverage is offline. Managed-project
qualification is an explicit owner-authorized live procedure: the tool performs the provider refresh itself with
protected refresh material and a low-privilege publishable/legacy-anon API key, witnesses unchanged signed
authentication freshness in the same session, then requires an external asymmetric signing-key rotation and
genuine new sign-in before completing the receipt.

A managed PASS requires a new trusted signing `kid`, a new provider session, advanced AMR-derived authentication
freshness and a successful Princess revocation-fence witness. It also records the actual access-token lifetime,
JWKS algorithms/key IDs/hashes and explicitly inspected anonymous-sign-in/OAuth-server settings. Enabled/unknown
Custom Access Token Hooks, symmetric signing, elevated API keys, stale reauthentication material and unknown
account-policy settings fail closed.

The generated `supabase-identity-qualification/2` receipt contains no raw access/refresh token, API key, subject,
session ID, issuer URL, JWKS body or provider secret and always records `provider_selection_claim=false` and
`production_activation=false`. **No managed Supabase project is qualified merely because this tooling exists.**
Provider selection, processor/region/retention/deletion approval and the actual managed-project run remain
owner/provider gates before composition or production PKCE/refresh integration.


PR #48 additionally provides a fixed-issuer, redirect-refusing, size/key-count-bounded HTTPS JWKS source and makes the qualification harness use that same implementation. This removes a future runtime primitive gap without changing this ADR's decision state: API/runtime composition remains fake-only until the managed-project and owner/account gates are real evidence rather than repository assumptions.
