# T17 Supabase staging account/processor evidence

**Status: EVIDENCE ASSEMBLED — scoped owner decision PENDING.**

This is the Git-safe account/processor review record for the owner-selected Supabase Auth implementation provider.
It is deliberately narrower than `processor_retention_contracts` as a repository-wide gate and narrower than
production/live approval. Public provider documentation and observed account facts are evidence inputs; they do
not create approval on their own.

The requested decision in this record is limited to the already-qualified **staging / sandbox**
`IdentityProvider` profile and its current `VERIFY_CREDENTIAL` capability using internal/disposable test
identities. It does not authorize a public login rollout, social-provider credentials, handwriting processing,
Supabase Storage, Premium AI, commerce, analytics, native store release, or production/live identity.

## Account and qualification facts

```text
provider:                         supabase-auth
connector_port:                   IdentityProvider
capability_scope:                 VERIFY_CREDENTIAL
environment:                      staging
provider_mode:                    sandbox
project_alias:                    princess-staging
project_binding:                  INTENDED_RUNTIME_PROFILE
project_region:                   eu-west-1
organization_plan:                Free
checked_date:                     2026-10-01

managed_project_receipt:          supabase-identity-qualification/4
managed_project_result:           PASS
managed_project_evidence:         docs/ci/T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md

owner_decision:                   PENDING
approver_role:                    product/technical owner
approved_on:                      PENDING
production_approved:              false
global_processor_gate_closed:     false
```

The project region and account plan are account facts observed for the owner-authorized staging project. The region
is a provider location control, not a claim that every backup, log, support path or subprocessor remains in that
region.

## Requested processing purpose

The requested staging decision covers only technical identity processing needed to exercise the selected
first-party Supabase access-token profile:

- maintain internal/disposable staging Auth users used for qualification and integration tests;
- authenticate those test users through the configured Supabase Auth method;
- issue/refresh provider session material for those test users where required by the staged test;
- let Princess verify first-party access JWTs against the fixed issuer/JWKS profile already qualified by #53.

FastAPI remains the application authorization authority. This decision would not authorize Supabase to decide
report access, account merging, entitlement, measurement, or report contents.

## Data categories in this staging scope

Supabase Auth may process the minimum account/authentication data required by the configured test flow:

- account/login identifiers such as email when that sign-in method is used;
- authentication credentials handled by the provider for the configured sign-in method (for example a password
  in the password test flow, or authorization artifacts in a later separately configured OAuth flow);
- provider user/identity identifiers;
- session and authentication metadata, including session IDs, AAL/AMR state and authentication timestamps;
- access/refresh token material and signed token claims;
- ordinary provider security/audit/network metadata where the service records it, such as request time,
  client/network identifiers or user-agent metadata.

Princess must not log or commit raw credentials, access/refresh tokens, provider secrets or private account
correspondence.

Explicitly outside this decision:

- handwriting images or derived crops;
- handwriting measurements/evidence packets;
- report text, snapshots or exports;
- Supabase Storage or database use as Princess's application data plane;
- Premium model payloads;
- payment/store data;
- product analytics;
- support-human access to handwriting;
- production/live identities or credentials.

## Region, retention and deletion evidence

The account-level project region is `eu-west-1`. Supabase public documentation states that project region is a
data-location control for core project services, while backups, logs, exported data and subprocessors can affect
the broader residency analysis. Region selection therefore does not close the repository's general residency or
processor gate.

Current provider documentation and the existing ADR-002 comparison establish that provider-side Auth user
deletion is a server/admin lifecycle distinct from Princess application deletion, and that provider credentials
can remain valid until their normal lifetime unless the application/session design fences them. Princess keeps
its durable `revoked_before` fence and treats provider-account deletion, provider session revocation and
application data deletion as separate operations.

Exact provider backup/log retention, contract-specific deletion obligations and any retention that survives Auth
user deletion remain matters for the owner to accept from the provider terms/DPA before this record can move from
PENDING to an approved staging decision.

## DPA, subprocessors and support

Public evidence already referenced by the repository:

- Supabase DPA: https://supabase.com/legal/customer-resources/data-processing-addendum
- security/data-residency overview: https://supabase.com/docs/guides/security
- region documentation: https://supabase.com/docs/guides/platform/regions
- Auth user/deletion behavior: https://supabase.com/docs/guides/auth/managing-user-data
- Auth rate limits: https://supabase.com/docs/guides/auth/rate-limits
- pricing/account-plan information: https://supabase.com/pricing

The staging organization is on the Free plan. No negotiated support commitment is evidenced in the repository.
The DPA/public resources are evidence inputs only; subprocessor/support/account terms are not treated as accepted
until the owner explicitly records that decision here. Any later plan, region, DPA/subprocessor, support or
material service change reopens this review.

## Secrets and least privilege

The current selected adapter verifies credentials using the configured issuer/audience/allowed roles and the
provider's public asymmetric JWKS. `VERIFY_CREDENTIAL` does not require a Supabase service-role/admin secret.

The publishable key used during the managed qualification is not admin authority and is not evidence that a
browser/native login implementation has been approved. Provider session revocation and provider-account deletion
remain unsupported by the Princess adapter; a future server-side lifecycle adapter may require elevated
credentials and must receive a separate least-privilege review before composition.

## Rate limits, retries and failure behavior

Supabase documents configurable Auth rate limits. Exact account endpoint values for later public login flows are
not frozen by this record and must be captured before #56 activates those flows.

For the current server verification capability, Princess already has a fixed-issuer, redirect-refusing,
size/key-count-bounded JWKS source with typed rate-limit/unavailable failures. Unknown keys, wrong
issuer/audience/role/profile, cross-environment credentials and out-of-profile signing fail closed.

## Sandbox evidence and unsupported cases

The staging profile's live refresh/rotation/reauthentication/fence evidence is indexed in
[T17 managed-project evidence](T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md). The selected adapter currently
advertises only `VERIFY_CREDENTIAL`.

Still unsupported or separately gated:

- provider-side session revocation;
- provider-account deletion;
- web callback/PKCE/access+refresh transport;
- Apple/Google provider configuration and private-relay recovery;
- cross-device recovery/linking;
- production/live identity;
- full staging API boot while unrelated ObjectStore/Payment/Abuse providers remain uncomposed.

## Incident, exit and review triggers

On an identity-provider incident, disable the affected staging identity path rather than falling back to an
unreviewed provider/profile or weakening credential verification. Princess internal principals remain the account
continuity anchor; provider replacement requires proven relinking and never reconstructs ownership from matching
email text.

Re-review this record before any of the following:

- project region, organization plan or relevant support terms change;
- DPA/subprocessor terms materially change;
- selected credential claims/signing profile changes;
- Custom Access Token Hook or anonymous/OAuth-server profile changes;
- new data categories or sign-in methods are introduced;
- provider revocation/deletion capabilities are composed;
- staging use expands beyond internal/disposable test identities;
- any production/live composition or activation.

## Owner decision

The evidence above is ready for a human scope decision. Agents must leave this section pending until the
product/technical owner explicitly approves or rejects the requested scope.

```text
decision:               PENDING
approver_role:          product/technical owner
decided_on:             PENDING
scope:                  staging/sandbox IdentityProvider VERIFY_CREDENTIAL + internal/disposable test identities
evidence:               this record + T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md
expiration/review:      material account/region/terms/profile/data-scope change
production_activation:  false
global_gate_closure:    false
```

Even an APPROVED staging decision here would close only this Supabase Auth slice. It must not mark the shared
`processor_retention_contracts` gate globally complete, must not alter the pending consent/legal-basis records,
and must not be cited as production/live authorization.
