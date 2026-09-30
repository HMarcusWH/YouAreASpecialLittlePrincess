# IdentityProvider — internal principals, provider-backed authentication

[Connector index](README.md) · [T02](../roadmap/06-agent-backlog.md#t02) · [Auth ADR](../adr/ADR-002-auth-provider.md) · [Web](../roadmap/10-web-client-and-api-integration.md) · [Mobile](../roadmap/11-mobile-architecture.md).

## Port and data flow

The implemented port operation is `verify_credential(credential, ctx) -> VerifiedIdentity`, plus provider session revocation and provider-account deletion capabilities where a selected adapter supports them. The **adapter owns the complete credential-validation policy**: issuer/key source, audience or authorized-party rules when that provider uses them, token/session type and temporal checks. The application layer never supplies or interprets an OAuth/OIDC `aud` claim. The port intentionally does **not** decide whether production uses an OAuth access token, provider session JWT, ID token or an application-issued session credential; ADR-002 must bind exactly one reviewed profile. A `VerifiedIdentity` contains only already-verified issuer/subject and optional provider facts; it does not carry an `audience` field or authority to read a report.

The application resolves unique `(issuer, subject)` into its own `principal_id`/identity binding, then separately authorizes sample/report/credit operations. Do not use email as the account primary key or merge users merely because two providers return the same email string. Store only required profile fields; no handwriting-derived identity inference.

## Implementation instructions

Select a managed identity provider and exact API credential profile through ADR-002. Validate the selected credential's signature/key source, provider-specific context claims, time claims and token/session type inside that adapter. The existing generic `OidcIdentityProvider` remains an **ID-token-shaped** verifier with its expected audience configured in the adapter and still rejects RFC 9068 access-token `typ` values; that behavior must not be broadened before the provider decision. Key rotation uses bounded caching and a controlled refresh on unknown key IDs; do not fetch arbitrary issuer/JWKS URLs taken from an untrusted token. Keep replay/nonce/state and PKCE behavior in the relevant login transport.

`auth_time` means the time of an actual provider authentication/reauthentication ceremony. It is optional when the provider cannot prove it, and **token `iat` is never substituted for it**. Application logout-everywhere and deletion persist a local `revoked_before` fence: after that fence, unknown/old authentication freshness fails closed even if a provider can mint a newly issued credential. The production identity decision must therefore demonstrate a trustworthy reauthentication/session-freshness mechanism compatible with that fence, or introduce a separately reviewed application-session/provider-revocation design. The current provider-neutral service does not pretend that merely having a provider `sid` means provider logout has been executed.

Credential transport is client-owned and remains distinct from provider verification and application authorization. Web already uses a server-only credential boundary: `apps/web/lib/session.ts` reads one opaque credential from the host-only `princess_session` HttpOnly SameSite=Lax cookie and the same-origin proxy forwards it as a bearer credential without parsing provider claims. `apps/web/lib/session-policy.ts` owns the reviewed issue/clear cookie policy; the cookie is Secure outside local/test, browser JavaScript never receives it, and local-device sign-out only clears that transport. `POST /v1/me/logout-everywhere` is the separate application revocation fence and still does not claim provider-side revocation. Native already uses `SecureSessionStore` plus `NativeSessionBoundary` for platform secure storage/account-switch fencing; no duplicate Python session port exists or is needed. Do not embed social-provider password forms. Provider SDKs may assist later, but FastAPI still verifies identity and object permissions independently. Sign in with Apple applicability, private relay, Google identity, identity linking and token revocation must be verified for the chosen provider and actual platform configuration.

Guest-to-account migration proves possession of the guest session and authenticated account, transfers permitted ownership atomically and invalidates the old guest capability. Purchases require an authenticated principal first. Account deletion revokes sessions/bindings and initiates application deletion; deleting only the identity-provider user does not delete report assets or ledger obligations.

## Tests, failures and production gate

Fakes provide expired/wrong-audience/unverified-email/rotated-key/revoked-session states. Tests cover JWT algorithm/issuer confusion, arbitrary key URL, login CSRF, cross-owner report access, account linking without proof, private-relay recovery, guest transfer races, logout with late requests and deletion while a token remains otherwise valid. Missing provider attributes remain unknown, not fabricated verified facts.

Live configuration requires an approved tenant, exact credential profile/audiences, callback/deep-link domains, a tested reauthentication/logout/deletion model, region/data handling and deletion support. No identity admin secret belongs in mobile/web bundles. Log opaque binding/operation IDs and safe error codes, not tokens or login URLs containing credentials. Provider replacement migrates identity bindings through an explicit linking/recovery process, not by silently changing principal IDs. The checked-in `PRINCESS_SESSION_SECRET` name is configuration surface only; there is currently no application-issued session-token implementation and its presence is not evidence that one exists.

Primary protocol references: E23/E24 and platform rules in [source refresh](../roadmap/22-research-and-source-refresh.md).


## Supabase Auth candidate profile (T17, production disabled)

`src/princess_app/adapters/supabase/SupabaseIdentityProvider` code-qualifies one narrow **candidate** profile; it does not select or activate Supabase for production. The reviewed upstream behavior is pinned to `supabase/auth@ce9a8eee0cc042be8c7a42981a7ddae631e41d91` (checked 2026-09-30). A future managed project must still prove its actual version/configuration, processor terms, region/retention/deletion behavior and account settings.

The candidate accepts first-party Supabase **access JWTs** only when all of these are true:

- project signing is asymmetric and the key comes from the configured JWKS source; HS256/shared-secret projects are outside this profile;
- issuer, singleton audience and permitted role are explicit adapter configuration, not universal Supabase constants;
- `sub` and `session_id` are canonical UUIDs, `aal` is `aal1` or `aal2`, and `is_anonymous` is false;
- `client_id` is absent, so Supabase OAuth-server client credentials are not silently accepted as the first-party session profile;
- `exp` and `iat` are required; `nbf` is optional but validated when present;
- the account uses the reviewed stock claims profile. An enabled Custom Access Token Hook is **not qualified** by this adapter unless a later review proves that the hook preserves every Princess-trusted claim. Construction therefore requires an explicit `stock_claims_profile=True` assertion; that flag is configuration evidence, not provider approval.

Authentication freshness is derived from signed AMR objects, never token `iat`. The reviewed Supabase Auth source stores authentication-method claims on the session and emits their timestamps into access-token AMR; token refresh reissues a JWT from that persisted session AMR rather than turning the refresh timestamp into a new authentication ceremony. Princess accepts timestamped reviewed authentication/reauthentication methods as freshness evidence, ignores unknown/string-only/refresh-only entries for freshness, rejects malformed/future/post-`iat` timestamps, and returns `auth_time=None` when no usable freshness exists. That allows a valid never-revoked session to authenticate while preserving the existing fail-closed `revoked_before` behavior after logout/deletion.

The candidate advertises only `VERIFY_CREDENTIAL`. `REVOKE_SESSION` and `DELETE_PROVIDER_ACCOUNT` remain unsupported: Supabase logout/admin APIs have not yet been bound to Princess's durable provider-session/deletion choreography. API composition still refuses every non-fake IdentityProvider, and no Supabase key, URL or project configuration is present in the environment manifests.
