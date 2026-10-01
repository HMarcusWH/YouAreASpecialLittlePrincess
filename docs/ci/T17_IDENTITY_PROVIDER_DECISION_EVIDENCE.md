# T17 identity-provider decision evidence

**Checked: 2026-10-01. Status: public-source comparison complete; provider selection and production approval PENDING.**

This is supporting evidence for [ADR-002](../adr/ADR-002-auth-provider.md) and the canonical
[provider decision register](../roadmap/19-provider-decision-register.md). It does not select a provider, approve
a processor/account/region, claim a managed-project qualification PASS, or activate runtime identity.

The comparison uses current first-party vendor documentation plus evidence already merged in this repository.
Account-specific settings, contracts, negotiated support, actual provider behavior and owner decisions remain
separate gates. Unknown is not treated as equivalent to supported.

## Princess invariants applied to both candidates

Any selected provider/profile must preserve these existing repository decisions:

- Princess internal principals and explicit `(issuer, subject)` bindings own identity continuity. Email text alone
  is not proof for merging accounts.
- JWT issuance time is not authentication time. Logout-everywhere/deletion use the durable Princess
  `revoked_before` fence, so a provider must supply trustworthy authentication/reauthentication freshness or a
  separately reviewed revocation/application-session design.
- Web credentials remain server-only and opaque to browser JavaScript. Native authentication uses an external
  user-agent boundary plus secure credential storage; provider SDKs may assist but do not become authorization
  authority.
- Provider logout, provider-account deletion and application data deletion are distinct lifecycles.
- No admin/provider secret belongs in web or native public bundles.

## Decision matrix

| Dimension | Supabase Auth | Clerk | Princess implication / remaining evidence |
|---|---|---|---|
| Web authorization / PKCE | Supabase documents PKCE for user authentication and OAuth 2.1 authorization-code flows. | Clerk documents standards-based OAuth, public clients and PKCE. | Both are publicly compatible with the planned web redirect boundary. Exact Princess callback/origin configuration is still untested. |
| Native external-user-agent / Expo | Supabase documents Apple/Google native support and an Expo React Native social-auth path. | Clerk has an Expo SDK/quickstart plus native Apple and Google flows. | T29 already proves Princess's provider-neutral external-user-agent callback/state boundary, not either vendor's live flow. |
| Sign in with Apple | Web and native Sign in with Apple are documented. | Web and native Sign in with Apple are documented. | Actual App ID/Services ID/bundle/account configuration remains T29-T32 owner evidence. |
| Apple private relay | Checked Supabase Apple documentation supports Apple sign-in but does not establish Princess-specific private-relay recovery/linking behavior. | Clerk explicitly documents Apple Hide My Email / Private Email Relay configuration. | Supabase requires an account-level relay/recovery test; Clerk's documented relay support still does not prove Princess relinking semantics. |
| Google sign-in | Web/native Google flows are documented, including Expo/React Native configuration. | Expo/native Google configuration is documented. | Actual client IDs, package/bundle bindings and recovery remain account/device evidence. |
| Account linking | Supabase documents explicit identity linking/unlinking, including native OAuth-token linking. | Clerk documents automatic OAuth account-link attempts when verified email addresses match, plus explicit external-account management. | **Clerk requires an explicit compatibility decision:** automatic email-based linking is in tension with Princess's rule that email matching is not proof for account merging. Do not select Clerk until the exact configuration/flow preserves the Princess principal-binding invariant. |
| Session logout / revocation | Supabase documents global/local/other-session sign-out scopes; Princess adapter has not yet bound provider revocation. | Clerk exposes a backend session-revocation API. | Either selection still needs Princess provider-lifecycle choreography and failure tests. |
| Provider-account deletion | Supabase admin deletion is server-only and requires an elevated secret; existing access JWTs can remain valid until expiry unless additional session checks are performed. | Clerk exposes server-side user deletion through its Backend API. | Neither provider deletion substitutes for Princess report/asset/ledger deletion. Secret scope and late-token behavior need integration tests. |
| Backend credential/JWT verification | Repository already code-qualifies a narrow first-party Supabase access-JWT profile with asymmetric JWKS, exact issuer/audience/roles, session UUID and conservative AMR freshness. | Clerk session tokens are short-lived JWTs with `iss`, `sub`, `sid`, `iat`, `exp`, `fva` and JWKS verification guidance. | Supabase has Princess-specific verifier evidence. Clerk would need its own adapter/profile qualification before composition. |
| Authentication freshness / reauthentication | Repository source review and synthetic/live-harness design use timestamped Supabase AMR and explicitly reject token `iat` as freshness. | Clerk documents signed `fva` factor-verification-age claims, reverification and session-token refresh about every 60 seconds. | Clerk's public docs are promising but do **not** prove the exact stable absolute freshness semantics Princess needs across token refresh and the `revoked_before` fence. A dedicated qualification would be required. |
| Signing keys / rotation | Princess already implements bounded asymmetric JWKS retrieval and rotation handling for the qualified Supabase candidate. | Clerk documents JWKS/public-key verification and recommends caching/invalidation when keys are replaced. | Supabase is already code-qualified; Clerk would need algorithm/key-rotation adversarial tests. |
| Region / data residency | Supabase projects can select a specific region; current docs include Stockholm (`eu-north-1`) and caution that region choice is a data-location control, not blanket compliance. | Clerk's current security page says regional data residency is not offered and service data is US-hosted. | Material deployment difference. Actual Supabase project region and all processor flows still require owner/account review. |
| DPA / subprocessors | Public DPA and referenced subprocessor list exist. | Public DPA and subprocessor list exist. | Public terms are evidence inputs only; actual processor approval/support obligations remain `processor_retention_contracts`. |
| Rate limits | Supabase Auth documents configurable endpoint rate limits. | Clerk publishes Frontend/Backend API rate limits, including separate development/production limits. | Record exact selected-account limits and retry policy before activation. |
| Cost model | Current Supabase pricing meters Auth by MAU; public page currently lists 50k included on Free and 100k on Pro before usage pricing. | Clerk currently prices by monthly retained users (MRU); public pricing currently lists 50k included and paid retained-user tiers. | Units are not directly comparable. Recheck current plan/account pricing immediately before owner selection/activation. |
| Test / development tooling | Supabase CLI can run the Auth stack locally; managed-project qualification tooling already exists in Princess. | Clerk separates development and production instances and offers preconfigured development OAuth credentials; no Princess Clerk sandbox/profile has been qualified. | Supabase currently has substantially more Princess-specific test evidence; this is implementation maturity, not an owner selection by itself. |
| Exit / migration | Supabase documents direct access/export of `auth.users` / `auth.identities`. | Clerk documents user export and migration away through dashboard/backend APIs. | Princess must preserve internal principal IDs and require proven relinking; neither vendor export authorizes email-based reconstruction. |

## Primary sources checked

### Supabase

- PKCE user flow: https://supabase.com/docs/guides/auth/sessions/pkce-flow
- OAuth 2.1 / authorization code with PKCE: https://supabase.com/docs/guides/auth/oauth-server/oauth-flows
- Sign in with Apple: https://supabase.com/docs/guides/auth/social-login/auth-apple
- Sign in with Google: https://supabase.com/docs/guides/auth/social-login/auth-google
- Expo React Native social auth: https://supabase.com/docs/guides/auth/quickstarts/with-expo-react-native-social-auth
- Identity linking: https://supabase.com/docs/guides/auth/auth-identity-linking
- Identities: https://supabase.com/docs/guides/auth/identities
- Sessions: https://supabase.com/docs/guides/auth/sessions
- Sign out scopes: https://supabase.com/docs/guides/auth/signout
- User management/deletion behavior: https://supabase.com/docs/guides/auth/managing-user-data
- Admin user deletion: https://supabase.com/docs/reference/javascript/auth-admin-deleteuser
- Auth rate limits: https://supabase.com/docs/guides/auth/rate-limits
- Local development: https://supabase.com/docs/guides/local-development
- Regions: https://supabase.com/docs/guides/platform/regions
- Pricing: https://supabase.com/pricing
- Security/data residency overview: https://supabase.com/docs/guides/security
- DPA: https://supabase.com/legal/customer-resources/data-processing-addendum

### Clerk

- Session-token claims: https://clerk.com/docs/guides/sessions/session-tokens
- Token refresh: https://clerk.com/docs/guides/sessions/force-token-refresh
- Manual JWT/JWKS verification: https://clerk.com/docs/guides/sessions/manual-jwt-verification
- Reverification / factor freshness: https://clerk.com/docs/guides/secure/reverification
- OAuth/PKCE behavior: https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth
- Expo quickstart: https://clerk.com/docs/expo/getting-started/quickstart
- Native Apple / Expo: https://clerk.com/docs/expo/guides/configure/auth-strategies/sign-in-with-apple
- Apple Private Relay configuration: https://clerk.com/docs/guides/configure/auth-strategies/social-connections/apple
- OAuth account linking: https://clerk.com/docs/guides/configure/auth-strategies/social-connections/account-linking
- External-account management: https://clerk.com/docs/guides/development/custom-flows/account-updates/manage-sso-connections
- Session revocation: https://clerk.com/docs/reference/backend/sessions/revoke-session
- User deletion: https://clerk.com/docs/reference/backend/user/delete-user
- Migration/export: https://clerk.com/docs/guides/development/migrating/overview
- Rate limits: https://clerk.com/docs/guides/how-clerk-works/system-limits
- Pricing: https://clerk.com/pricing
- Security/data-residency statement: https://clerk.com/security
- DPA: https://clerk.com/legal/dpa
- Subprocessors: https://clerk.com/legal/subprocessors

## Evidence already held by this repository

Supabase has materially more Princess-specific implementation evidence because the repository already contains:

- a production-disabled `SupabaseIdentityProvider` candidate;
- asymmetric algorithm/issuer/audience/role/session/profile negative tests;
- conservative AMR-derived authentication freshness;
- bounded fixed-issuer JWKS fetching and rotation handling;
- a protected managed-project qualification harness capable of witnessing real refresh, signing-key rotation,
  genuine reauthentication and the Princess revocation fence.

That implementation lead is **not** a provider-selection claim. Clerk has not undergone equivalent Princess-specific
adapter/profile qualification.

## Selection blockers after this public-source pass

The public-source comparison does not close the following gates:

1. **Owner provider decision:** no owner has selected Supabase or Clerk in the repository.
2. **Supabase managed-project evidence:** the protected `MANAGED_PROJECT` run remains PENDING.
3. **Processor/account approval:** actual provider account, purpose, region, retention/deletion, support and
   subprocessors must be reviewed under `processor_retention_contracts`.
4. **Clerk principal-continuity compatibility:** if Clerk remains under consideration, prove/configure a flow that
   does not let email equality silently become Princess account-merge authority.
5. **Clerk freshness profile:** if Clerk remains under consideration, code-qualify how `fva`, session refresh,
   reverification, session revocation and JWT/JWKS behavior interact with Princess's durable `revoked_before`
   fence.
6. **Actual web/native account configuration:** callback/deep-link domains, Apple/Google credentials, private
   relay/relinking and cross-device recovery remain real account/device evidence.
7. **Provider lifecycle integration:** provider logout/revocation and provider-account deletion are still not
   bound to Princess application deletion/logout choreography.

## Decision state after this PR

Unless a separate explicit owner decision and account evidence are supplied during review, merging this evidence
packet must leave:

```text
Supabase Auth            CANDIDATE (Princess code-qualified; managed-project PASS pending)
Clerk                    alternative (public-source reviewed; Princess profile qualification pending)
ADR-002 provider choice  PENDING
production activation    PENDING
```

A later owner decision may select a provider without waiting for complete App Store/Play release evidence, but
must not treat this public-source review as live-account, signed-device, processor-contract or production
approval.
