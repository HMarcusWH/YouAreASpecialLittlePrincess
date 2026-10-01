# IdentityProvider — internal principals, provider-backed authentication

[Connector index](README.md) · [T02](../roadmap/06-agent-backlog.md#t02) · [Auth ADR](../adr/ADR-002-auth-provider.md) · [Web](../roadmap/10-web-client-and-api-integration.md) · [Mobile](../roadmap/11-mobile-architecture.md).

## Port and data flow

The implemented port operation is `verify_credential(credential, ctx) -> VerifiedIdentity`, plus provider session revocation and provider-account deletion capabilities where a selected adapter supports them. The **adapter owns the complete credential-validation policy**: issuer/key source, audience or authorized-party rules when that provider uses them, token/session type and temporal checks. The application layer never supplies or interprets an OAuth/OIDC `aud` claim. The port intentionally does **not** decide whether production uses an OAuth access token, provider session JWT, ID token or an application-issued session credential; ADR-002 must bind exactly one reviewed profile. A `VerifiedIdentity` contains only already-verified issuer/subject and optional provider facts; it does not carry an `audience` field or authority to read a report.

The application resolves unique `(issuer, subject)` into its own `principal_id`/identity binding, then separately authorizes sample/report/credit operations. Do not use email as the account primary key or merge users merely because two providers return the same email string. Store only required profile fields; no handwriting-derived identity inference.

## Implementation instructions

ADR-002 selects Supabase Auth as the implementation provider. Before composition, qualify the exact managed project/account/profile and validate the selected credential's signature/key source, provider-specific context claims, time claims and token/session type inside the dedicated Supabase adapter. The existing generic `OidcIdentityProvider` remains an **ID-token-shaped** verifier with its expected audience configured in the adapter and still rejects RFC 9068 access-token `typ` values; selecting Supabase does not authorize broadening that generic profile. Key rotation uses bounded caching and a controlled refresh on unknown key IDs; do not fetch arbitrary issuer/JWKS URLs taken from an untrusted token. Keep replay/nonce/state and PKCE behavior in the relevant login transport.

`auth_time` means the time of an actual provider authentication/reauthentication ceremony. It is optional when the provider cannot prove it, and **token `iat` is never substituted for it**. Application logout-everywhere and deletion persist a local `revoked_before` fence: after that fence, unknown/old authentication freshness fails closed even if a provider can mint a newly issued credential. The production identity decision must therefore demonstrate a trustworthy reauthentication/session-freshness mechanism compatible with that fence, or introduce a separately reviewed application-session/provider-revocation design. The current provider-neutral service does not pretend that merely having a provider `sid` means provider logout has been executed.

Credential transport is client-owned and remains distinct from provider verification and application authorization. Web already uses a server-only credential boundary: `apps/web/lib/session.ts` reads one opaque credential from the host-only `princess_session` HttpOnly SameSite=Lax cookie and the same-origin proxy forwards it as a bearer credential without parsing provider claims. `apps/web/lib/session-policy.ts` owns the reviewed issue/clear cookie policy; the cookie is Secure outside local/test, browser JavaScript never receives it, and local-device sign-out only clears that transport. `POST /v1/me/logout-everywhere` is the separate application revocation fence and still does not claim provider-side revocation. Native already uses `SecureSessionStore` plus `NativeSessionBoundary` for platform secure storage/account-switch fencing; no duplicate Python session port exists or is needed. Do not embed social-provider password forms. Provider SDKs may assist later, but FastAPI still verifies identity and object permissions independently. Sign in with Apple applicability, private relay, Google identity, identity linking and token revocation must be verified for the chosen provider and actual platform configuration.

Guest-to-account migration proves possession of the guest session and authenticated account, transfers permitted ownership atomically and invalidates the old guest capability. Purchases require an authenticated principal first. Account deletion revokes sessions/bindings and initiates application deletion; deleting only the identity-provider user does not delete report assets or ledger obligations.

## Tests, failures and production gate

Fakes provide expired/wrong-audience/unverified-email/rotated-key/revoked-session states. Tests cover JWT algorithm/issuer confusion, arbitrary key URL, login CSRF, cross-owner report access, account linking without proof, private-relay recovery, guest transfer races, logout with late requests and deletion while a token remains otherwise valid. Missing provider attributes remain unknown, not fabricated verified facts.

Live configuration requires an approved tenant, exact credential profile/audiences, callback/deep-link domains, a tested reauthentication/logout/deletion model, region/data handling and deletion support. No identity admin secret belongs in mobile/web bundles. Log opaque binding/operation IDs and safe error codes, not tokens or login URLs containing credentials. Provider replacement migrates identity bindings through an explicit linking/recovery process, not by silently changing principal IDs. The checked-in `PRINCESS_SESSION_SECRET` name is configuration surface only; there is currently no application-issued session-token implementation and its presence is not evidence that one exists.

Primary protocol references: E23/E24 and platform rules in [source refresh](../roadmap/22-research-and-source-refresh.md).


## Selected Supabase Auth implementation profile (T17, production disabled)

`src/princess_app/adapters/supabase/SupabaseIdentityProvider` code-qualifies the narrow profile selected by ADR-002; the separate 2026-10-01 owner decision selects Supabase as implementation provider, but this adapter does not activate Supabase for production. The reviewed upstream behavior is pinned to `supabase/auth@ce9a8eee0cc042be8c7a42981a7ddae631e41d91` (checked 2026-09-30). The owner-authorized intended staging/sandbox profile subsequently passed the environment-bound v4 `MANAGED_PROJECT` witness on 2026-10-01. The product/technical owner approved the narrow staging `VERIFY_CREDENTIAL` processor/account scope on 2026-10-01 in [T17 Supabase staging account/processor evidence](../ci/T17_SUPABASE_ACCOUNT_PROCESSOR_EVIDENCE.md). Runtime code now has an exact staging/sandbox composition path, but its protected receipt-derived binding and real conformance run remain operational evidence; application-managed login and production/live remain separate gates.

The selected profile accepts first-party Supabase **access JWTs** only when all of these are true:

- project signing is asymmetric and the key comes from the configured JWKS source; HS256/shared-secret projects are outside this profile;
- issuer, singleton audience and permitted role are explicit adapter configuration, not universal Supabase constants;
- `sub` and `session_id` are canonical UUIDs, `aal` is `aal1` or `aal2`, and `is_anonymous` is false;
- `client_id` is absent, so Supabase OAuth-server client credentials are not silently accepted as the first-party session profile;
- `exp` and `iat` are required; `nbf` is optional but validated when present;
- the account uses the reviewed stock claims profile. An enabled Custom Access Token Hook is **not qualified** by this adapter unless a later review proves that the hook preserves every Princess-trusted claim. Construction therefore requires an explicit `stock_claims_profile=True` assertion; that flag is configuration evidence, not provider approval.

Authentication freshness is derived from signed AMR objects, never token `iat`. The reviewed Supabase Auth source stores authentication-method claims on the session and emits their timestamps into access-token AMR; token refresh reissues a JWT from that persisted session AMR rather than turning the refresh timestamp into a new authentication ceremony. Princess accepts timestamped reviewed authentication/reauthentication methods as freshness evidence, ignores unknown/string-only/refresh-only entries for freshness, rejects malformed/future/post-`iat` timestamps, and returns `auth_time=None` when no usable freshness exists. That allows a valid never-revoked session to authenticate while preserving the existing fail-closed `revoked_before` behavior after logout/deletion.

The selected profile advertises only `VERIFY_CREDENTIAL`. `REVOKE_SESSION` and `DELETE_PROVIDER_ACCOUNT` remain unsupported: Supabase logout/admin APIs have not yet been bound to Princess's durable provider-session/deletion choreography. API identity composition accepts only the exact `(staging, sandbox)` Supabase path when protected issuer/profile inputs validate against the qualified receipt-derived binding. Local/test/preview keep the fake; staging/live and production/live still fail closed. No raw Supabase key, issuer, project reference or role is committed to an environment manifest.


## Supabase managed-project qualification boundary

The selected production-disabled profile has the opt-in account-profile qualification harness at
`tools/qualify_supabase_identity.py`. Synthetic CI remains offline. A `MANAGED_PROJECT` run is deliberately
manual: it uses a protected initial access JWT, refresh token and low-privilege Supabase publishable/legacy-anon
API key, fetches the configured issuer's JWKS, and performs one real refresh grant itself. Secret/service-role
keys are refused.

After the refresh witness passes, the harness requires the operator to rotate the asymmetric signing key in the
owner-authorized qualification project and complete a genuine new sign-in. It then fetches JWKS again and only
passes when the original/refresh credentials share a session and authentication freshness, the reauthentication
uses a new session and newer AMR-derived freshness, the signing `kid` has changed, and both old/new signing keys
remain trusted by the final JWKS. The same run exercises Princess's local `revoked_before` fence: the refreshed
old session is rejected and the post-fence genuine authentication is accepted.

The `supabase-identity-qualification/4` receipt records checked date/Princess commit, explicit project binding, environment/provider mode, environment-manifest hash, issuer host and hashes,
audience/role, inspected anonymous-sign-in and OAuth-server settings, Custom Access Token Hook state, token
lifetime, JWKS algorithms/key IDs/hashes, AMR method names and boolean refresh/rotation/reauth/fence witnesses.
It contains no access/refresh token, API key, subject, session ID, absolute authentication timestamp, raw issuer
URL or JWKS body. A PASS still cannot itself select a provider, prove processor terms, or activate any runtime adapter. For the selected Supabase provider, the 2026-10-01 staging/sandbox `INTENDED_RUNTIME_PROFILE` run passed this receipt contract and closes only the staging exact-profile technical gate; production/live remains separately unqualified.

If the Custom Access Token Hook is enabled/unknown, the account-policy settings were not explicitly inspected,
the project uses an out-of-profile signing configuration, a secret/service-role key is supplied, refresh changes
session/authentication freshness, the signing key does not rotate for the live witness, reauthentication is not
genuinely newer, or the selected adapter rejects any credential, qualification fails. Fix/review the account
configuration; do not weaken the candidate verifier or durable freshness fence to manufacture a PASS.


### Bounded Supabase JWKS network source

PR #48 adds `SupabaseJwksSource` as a reusable network primitive for the already-reviewed selected profile. The JWKS URL is derived only from the explicitly configured HTTPS issuer; token headers cannot supply `jku`, `x5u` or another key URL. Redirects are refused, decoded response bytes and key count are bounded, and HTTP/network failures are translated to typed redacted port errors. The qualification harness reuses this source so live qualification and later runtime composition cannot drift onto different JWKS-fetch policies.

`apps/api/princess_api/compose.py` and runtime preflight now recognize only the qualified staging/sandbox identity tuple. `tools/build_supabase_staging_runtime_binding.py` converts the protected v4 receipt plus the Git-safe account snapshot into a safe hash-bound runtime profile; startup then hashes the protected issuer and requires the qualified audience/role before constructing `SupabaseJwksSource` and `SupabaseIdentityProvider`. The staging environment manifest is deliberately unchanged so the v4 manifest binding remains valid. Full staging API startup still fails at the next unimplemented sandbox connector (currently ObjectStore); this slice is not application login, production/live qualification, or global processor-gate closure.

### Staging runtime conformance harness

`tools/verify_supabase_staging_runtime.py` is an explicit opt-in operator harness for the remaining staging witness. It accepts no password, Supabase API key, refresh token or admin credential. The operator supplies only the protected v4 qualification receipt, the protected exact issuer and one already-issued disposable staging access JWT, all through absolute files outside the Git checkout.

The harness rebuilds the exact runtime binding through `build_binding()`, loads the reviewed staging manifest, constructs only the narrow immutable `RuntimeConfig` needed by the already-merged identity seam, and then calls `compose_identity_provider()`. It therefore exercises the real `SupabaseJwksSource -> SupabaseIdentityProvider -> IdentityService` path without pretending that complete staging API startup, PostgreSQL, ObjectStore, Payment or Abuse are ready. Repeat authentication must converge on one in-memory ACCOUNT principal, usable AMR-derived authentication freshness and a session ID must be present, and a live JWKS fetch must have occurred before a PASS receipt can exist.

Protected inputs plus the full operational receipt must remain outside Git. The generated Git-safe index in [T17 Supabase staging runtime conformance](../ci/T17_SUPABASE_RUNTIME_CONFORMANCE.md) contains only evidence hashes, boolean witnesses and scope non-claims; it contains no raw access token, provider subject/session, Princess principal ID, raw issuer/project reference or JWKS. Tooling and synthetic CI do not constitute a live provider PASS.

The harness intentionally does not perform provider cleanup because `REVOKE_SESSION` and `DELETE_PROVIDER_ACCOUNT` are still unsupported adapter capabilities and adding an admin/service credential to this verification-only slice would widen authority. After a live witness, an authorized operator must revoke/sign out the disposable provider session and delete the disposable Auth user separately, retaining only safe cleanup evidence. Already-issued access JWTs can remain cryptographically valid until expiry, so cleanup must not be described as instantaneous token invalidation.

### Selected-account Auth operational policy

Before Princess activates application-managed Supabase sign-in or refresh, T17 requires exact selected-account Auth
settings plus an explicit retry/backoff/abuse policy. Public Supabase defaults are not accepted as substitutes for
the selected staging project's configuration.

`tools/build_supabase_auth_settings_snapshot.py` is the evidence builder for that gate. The operator captures the
selected project's `GET /v1/projects/{ref}/config/auth` response outside Git and supplies the raw project ref through
a separate protected file. The builder verifies the already-qualified Princess project-ref SHA-256, extracts only
reviewed non-secret operational fields, canonicalizes their safe projection, and emits the future
`docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json`. It performs no provider request and accepts no Management API
access token, Supabase API key, password, access token or refresh token.

The policy contract is in [T17 Supabase Auth operational policy](../ci/T17_SUPABASE_AUTH_OPERATIONAL_POLICY.md).
Retry ownership remains application/caller-owned. Bad credentials/permanent failures are never automatically
retried; provider rate limits must be honored before any later retry; transient transport failures may only receive
bounded application-owned retry once the actual login/session transport is reviewed; and refresh must be
single-flight per session rather than fanning out parallel refresh calls. No retry counts/delays are invented in
this evidence slice before that transport exists.

The selected-account snapshot also records whether Supabase's `Sb-Forwarded-For` Auth rate-limit feature is
enabled, but this slice does not enable it or add a Supabase secret key. Any later use of forwarded end-user IPs
requires its own least-privilege/trusted-proxy review. CAPTCHA/social/passkey/phone/other new sign-in methods are
likewise not activated by this policy.

The real staging conformance PASS and the selected-account Auth-settings evidence are independent gates. Neither
one substitutes for the other, and application-managed authentication remains disabled until both are closed.

For managed evidence, `QUALIFICATION_ONLY` and `INTENDED_RUNTIME_PROFILE` are deliberately different receipt
bindings. A disposable rotation project can prove the selected credential mechanics but cannot be cited as proof
that the later runtime tenant/profile has matching settings. The full receipt remains protected; Git stores only
the safe digest/reference index in `docs/ci/T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md`.



Environment binding is also explicit: the qualification tool verifies the requested environment/provider mode against the reviewed manifest. A staging/sandbox receipt cannot be cited as production/live evidence.
