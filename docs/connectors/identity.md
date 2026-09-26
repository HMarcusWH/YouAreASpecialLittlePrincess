# IdentityProvider — internal principals, provider-backed authentication

[Connector index](README.md) · [T02](../roadmap/06-agent-backlog.md#t02) · [Auth ADR](../adr/ADR-002-auth-provider.md) · [Web](../roadmap/10-web-client-and-api-integration.md) · [Mobile](../roadmap/11-mobile-architecture.md).

## Port and data flow

Proposed operations: `verify_credential(credential, expected_audience, deadline) -> VerifiedIdentity`, `resolve_session(...)`, `revoke_binding(...)` and provider-specific account-deletion coordination behind a capability profile. A `VerifiedIdentity` contains issuer, stable provider subject, verified attributes actually supplied, assurance/session context and expiry; it does not contain authority to read a report.

The application resolves unique `(issuer, subject)` into its own `principal_id`/identity binding, then separately authorizes sample/report/credit operations. Do not use email as the account primary key or merge users merely because two providers return the same email string. Store only required profile fields; no handwriting-derived identity inference.

## Implementation instructions

Select a managed OIDC provider through ADR-002. Validate token signature with supported issuer keys/JWKS, expected issuer/audience, expiration/not-before and the correct token type. Key rotation uses bounded caching and a controlled refresh on unknown key IDs; do not fetch arbitrary issuer/JWKS URLs taken from an untrusted token. Keep replay/nonce/state and PKCE behavior in the relevant login transport.

Web uses secure cookie/session handling with CSRF/origin controls. Native uses the external user-agent flow and platform secure credential storage. Do not embed social-provider password forms. Provider SDKs may assist, but FastAPI still checks object permissions. Sign in with Apple applicability, private relay, Google identity, identity linking and token revocation must be verified for the chosen provider and actual platform configuration.

Guest-to-account migration proves possession of the guest session and authenticated account, transfers permitted ownership atomically and invalidates the old guest capability. Purchases require an authenticated principal first. Account deletion revokes sessions/bindings and initiates application deletion; deleting only the identity-provider user does not delete report assets or ledger obligations.

## Tests, failures and production gate

Fakes provide expired/wrong-audience/unverified-email/rotated-key/revoked-session states. Tests cover JWT algorithm/issuer confusion, arbitrary key URL, login CSRF, cross-owner report access, account linking without proof, private-relay recovery, guest transfer races, logout with late requests and deletion while a token remains otherwise valid. Missing provider attributes remain unknown, not fabricated verified facts.

Live configuration requires approved tenant, callback/deep-link domains, audiences, region/data handling and deletion support. No identity admin secret in mobile/web bundles. Log opaque binding/operation IDs and safe error codes, not tokens or login URLs containing credentials. Provider replacement migrates identity bindings through an explicit linking/recovery process, not by silently changing principal IDs.

Primary protocol references: E23/E24 and platform rules in [source refresh](../roadmap/22-research-and-source-refresh.md).
