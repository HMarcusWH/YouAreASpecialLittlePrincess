# T17 Supabase staging account/processor evidence

**Status: APPROVED FOR NARROW STAGING VERIFICATION SCOPE — production/global gates remain open.**

This is the Git-safe account/processor review record for the owner-selected Supabase Auth implementation provider.
It is deliberately narrower than `processor_retention_contracts` as a repository-wide gate and narrower than
production/live approval. Public provider documentation, source review and observed account facts are evidence
inputs; they do not create approval on their own.

The requested decision is limited to the already-qualified **staging / sandbox** identity profile. The Princess
runtime adapter capability remains only `VERIFY_CREDENTIAL`. Separately, operator-controlled disposable test-user
authentication and token refresh may be used only to mint credentials for staging qualification/conformance. That
manual test activity is not the web/native application login transport and does not authorize public login,
social-provider credentials, handwriting processing, Supabase Storage, Premium AI, commerce, analytics, native
store release, or production/live identity.

## Account and qualification facts

```text
provider:                            supabase-auth
provider_api_profile:                first-party Auth access JWT + public asymmetric JWKS
reviewed_auth_source:                supabase/auth@ce9a8eee0cc042be8c7a42981a7ddae631e41d91
connector_port:                      IdentityProvider
runtime_capability_scope:            VERIFY_CREDENTIAL
environment:                         staging
provider_mode:                       sandbox
platform_scope:                      backend credential verification only
project_alias:                       princess-staging
project_binding:                     INTENDED_RUNTIME_PROFILE
project_region:                      eu-west-1
organization_plan:                   Free
checked_date:                        2026-10-01

account_settings_snapshot:           docs/ci/T17_SUPABASE_STAGING_ACCOUNT_SNAPSHOT.json
account_settings_snapshot_sha256:    905a943563fcce0c921b07f3c661032f2e732dbd968f8dcc6b6b31bf4e2c96a1
account_settings_source:             Supabase Management API (get_project + get_organization)

managed_project_receipt:             supabase-identity-qualification/4
managed_project_result:              PASS
managed_project_evidence:            docs/ci/T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md

implementation_owner_task:           T17
implementation_owner_role:           frontend
production_approver_role:            product/technical owner
owner_decision:                      APPROVED
approved_on:                         2026-10-01
production_approved:                 false
global_processor_gate_closed:        false
```

The linked account snapshot is a safe provider-returned fact artifact. It stores only the alias, region, account
plan/tier, checked date and hashes of the provider project/organization identifiers; it contains no key, token,
credential, raw issuer URL or private contract. Its SHA-256 above is over the canonical JSON (sorted keys, compact
UTF-8) represented by that file. This makes the asserted account facts reviewable without exposing the provider
identifiers.

The region is a provider location control, not a claim that every backup, log, support path or subprocessor remains
in that region.

## Requested processing purpose and scope

The requested staging decision covers two deliberately different things:

1. **Princess runtime capability:** server-side verification of the selected first-party Supabase access JWT through
   the qualified `VERIFY_CREDENTIAL` adapter.
2. **Operator/test credential acquisition:** owner/operator-controlled authentication of internal/disposable
   staging test users and issuance/refresh of their provider session material solely to obtain credentials needed
   by qualification and isolated staging conformance.

The second item does **not** authorize an application-managed web/native sign-in, PKCE callback, browser refresh
transport, social-provider flow or public account onboarding. Those remain later T17/T29-T31 work with their own
configuration, rate-limit, callback, recovery and lifecycle evidence.

FastAPI remains the application authorization authority. Neither scope authorizes Supabase to decide report
access, account merging, entitlement, measurement, or report contents.

## Data categories in this staging scope

Supabase Auth may process the minimum account/authentication data required by the operator-controlled test flow:

- account/login identifiers such as email when that sign-in method is used;
- authentication credentials handled by the provider for the configured test sign-in method;
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
- application-managed public login/PKCE/social-provider flows;
- production/live identities or credentials.

## Region, retention and deletion evidence

The source-bound account snapshot records `eu-west-1` for the staging project. Current Supabase GDPR guidance
states that a project is deployed to one primary region and that the primary Postgres database, Auth service and
Storage objects are hosted there, while backups, logs, exports and subprocessors can affect the wider residency
analysis. Region selection therefore does not close the repository's general residency/processor gate.

Current provider documentation separates these lifecycles:

- global sign-out terminates the affected provider sessions and destroys their refresh tokens/session state;
- access JWTs from revoked sessions can remain cryptographically valid until their `exp` time;
- deleting an Auth user/provider account is distinct from Princess application-data deletion;
- deleting the entire Supabase project is the provider-documented route that permanently removes project data,
  including stored backups.

Princess therefore keeps its durable local `revoked_before` fence and treats provider session revocation,
provider-user deletion, project decommission and application data deletion as separate operations.

For this staging scope, the retention/deletion obligation is:

- use only disposable identity test data;
- revoke provider sessions before deleting a disposable Auth user;
- keep the Princess identity path disabled/fenced while already-issued access JWTs age out;
- do not claim provider deletion complete merely because Princess deleted an identity binding;
- if strict full-project cleanup is required, decommission/delete the staging project through an owner-authorized
  provider operation and retain a safe completion reference;
- record any provider-side residual log/contract retention as residual provider retention rather than silently
  asserting immediate erasure.

## DPA, subprocessors and support

Public evidence checked 2026-10-01:

- Supabase DPA: https://supabase.com/legal/customer-resources/data-processing-addendum
- Supabase Subprocessor List: https://supabase.com/legal/customer-resources/subprocessor-list
- GDPR/data-residency guidance: https://supabase.com/docs/guides/security/gdpr-compliance
- Database backups: https://supabase.com/docs/guides/platform/backups
- Auth sign-out/session revocation: https://supabase.com/docs/guides/auth/signout
- Auth user/deletion behavior: https://supabase.com/docs/guides/auth/managing-user-data
- Auth rate limits / production checklist: https://supabase.com/docs/guides/platform/going-into-prod
- pricing/account-plan information: https://supabase.com/pricing

The current public DPA describes Supabase as processor/service provider for covered data, uses its published
Subprocessor List, and ties processing duration to the agreement unless earlier deletion is requested through
service functionality. The staging organization is on the Free plan according to the source-bound Management API
snapshot. No negotiated support commitment is evidenced for this staging account; current public production
guidance states that access to the Supabase support team is a Pro-plan benefit. The approved narrow staging
decision therefore explicitly accepts **Free-plan staging without a negotiated support SLA** rather than inventing one.

The scoped owner decision accepts the reviewed public DPA/subprocessor posture only for this staging test scope. Any later plan, region, DPA/subprocessor, support or material service change reopens this review.

## Secrets and least privilege

The selected Princess runtime adapter verifies credentials using the configured issuer/audience/allowed roles and
the provider's public asymmetric JWKS. `VERIFY_CREDENTIAL` requires no Supabase service-role/admin secret.

The publishable key used during the managed qualification is not admin authority and is not evidence that a
browser/native login implementation has been approved. Provider session revocation and provider-account deletion
remain unsupported by the Princess adapter. Operator cleanup uses owner-authorized provider controls outside the
adapter; any future server-side lifecycle adapter that needs elevated credentials requires its own least-privilege
review before composition.

### Protected runtime binding

The raw issuer contains the provider project reference and remains outside Git. The existing staging manifest is
also left byte-identical because the v4 qualification receipt binds its SHA-256. Runtime activation therefore uses
a separate protected profile channel rather than changing the manifest or committing the issuer.

`tools/build_supabase_staging_runtime_binding.py` consumes the exact protected v4 receipt plus the Git-safe account
snapshot and emits only safe binding fields: receipt/account/manifest/project hashes, source revision, issuer hash,
audience, allowed role and the stock-claims assertion. The API receives the raw issuer and this binding through
protected process configuration. Startup hashes the issuer, checks the qualified audience/role and evidence
anchors, and composes Supabase only for the exact `(staging, sandbox)` tuple. The binding does not authorize login,
refresh, provider lifecycle operations or production.

## Rate limits, retries and failure behavior

For the current **runtime verification** capability:

- `SupabaseJwksSource` performs one bounded HTTPS GET per source refresh with a 10-second default timeout;
- it performs no hidden HTTP retry;
- provider 429 becomes typed `RateLimited`;
- provider 5xx/network failure becomes typed `TransientUnavailable`;
- redirects, malformed/oversized JWKS and other permanent failures fail closed;
- the adapter owns bounded unknown-key refresh and will not repeatedly re-fetch inside its minimum refresh window;
- connector retry ownership remains the application/caller, matching the port's `CapabilityProfile` default.

Supabase also documents configurable Auth endpoint limits for sign-in/session operations. Public defaults are not
substitutes for the selected account's settings. **Before any application-managed Supabase login or refresh flow is
activated, T17 must capture the exact relevant selected-account Auth endpoint limits, the chosen retry/backoff
owner and the abuse-control policy as acceptance evidence.** This requirement is task-bound; it is not deferred to
a prospective PR number.

The evidence machinery for that gate is now defined in
[T17 Supabase Auth operational policy](T17_SUPABASE_AUTH_OPERATIONAL_POLICY.md).
`tools/build_supabase_auth_settings_snapshot.py` accepts only protected operator-captured
`GET /v1/projects/{ref}/config/auth` evidence plus the protected selected project ref, verifies the existing
Princess project-ref hash, and emits a narrow Git-safe snapshot. It does not call the Management API, hold a
Management API access token, activate application login or invent missing values from public defaults.

The selected-account Auth-settings snapshot is still **PENDING** until a real owner-authorized account export is
run through that tool. Tooling/tests alone do not close this acceptance gate.

The final staging evidence closeout also requires separate provider cleanup evidence. After the real conformance
witness, the owner-authorized operator must revoke all sessions for the disposable conformance test user and delete
that disposable Auth user. `tools/build_supabase_staging_cleanup_evidence.py` turns only the safe aggregate result
into Git-safe evidence; it does not perform the provider action and cannot claim project decommission. The atomic
closeout checker refuses PASS unless conformance, selected-account settings and cleanup evidence all validate while
this owner decision still says application login is not approved.

## Cost model

The source-bound account snapshot records the organization as Free. This staging decision therefore covers only
the current internal/disposable test-user scope and creates no paid-spend authorization. Supabase Auth pricing is
usage/MAU based under the provider's current pricing model; exact production plan, quotas, spend ownership and any
upgrade must be re-reviewed before production/live activation.

## Sandbox evidence and unsupported cases

The staging profile's live refresh/rotation/reauthentication/fence evidence is indexed in
[T17 managed-project evidence](T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md). The selected Princess adapter currently
advertises only `VERIFY_CREDENTIAL`.

Still unsupported or separately gated:

- provider-side session revocation **through the Princess adapter**;
- provider-account deletion **through the Princess adapter**;
- application-managed web callback/PKCE/access+refresh transport;
- Apple/Google provider configuration and private-relay recovery;
- cross-device recovery/linking;
- production/live identity;
- full staging API boot while unrelated ObjectStore/Payment/Abuse providers remain uncomposed.

## Incident and exit procedure

If the staged identity integration must be disabled or abandoned:

1. Disable/refuse the Princess staging identity composition path; never fall back to an unreviewed provider/profile
   or weaken JWT verification.
2. Stop issuing or refreshing credentials for the disposable staging test population.
3. Use owner-authorized Supabase controls to perform **global sign-out/session revocation** for affected disposable
   users so refresh tokens/session state are destroyed.
4. Keep the Princess `revoked_before` fence and the staging identity path disabled while already-issued access JWTs
   age out, because Supabase documents that revoked-session access tokens remain valid until their `exp`.
5. Delete the disposable Supabase Auth users through the provider's owner/admin controls once session revocation is
   recorded. Do not equate that deletion with Princess report/asset/ledger deletion.
6. Record safe completion evidence: action date, operator/owner role, affected test-population count (not user IDs),
   session-revocation result, provider-user deletion result, and any residual provider retention noted under the
   DPA/service documentation.
7. If the whole staging project is being retired rather than only the identity slice, perform a **separate
   owner-authorized project decommission/delete** and record its completion. Project deletion is destructive and is
   never implied by this connector rollback.
8. If any cleanup step cannot be evidenced, leave the exit state incomplete and keep the integration disabled.

Princess internal principals remain the account-continuity anchor. Provider replacement requires proven relinking
and never reconstructs ownership from matching email text.

## Review triggers

Re-review this record before any of the following:

- project region, organization plan or relevant support terms change;
- DPA/subprocessor terms materially change;
- selected credential claims/signing profile changes;
- Custom Access Token Hook or anonymous/OAuth-server profile changes;
- new data categories or sign-in methods are introduced;
- provider revocation/deletion capabilities are composed;
- staging use expands beyond internal/disposable test identities;
- application-managed login/refresh is activated without the T17 rate-limit/retry evidence above;
- any production/live composition or activation.

## Owner decision

The product/technical owner explicitly approved this narrow scope on 2026-10-01 by directing implementation of
the reviewed staging-verification slice after the account/processor and dumbassery reviews. This approval is
limited to the exact scope below; it is not application-login or production authorization.

```text
decision:               APPROVED
approver_role:          product/technical owner
decided_on:             2026-10-01
scope:                  staging/sandbox IdentityProvider VERIFY_CREDENTIAL
test_operations:        operator-controlled disposable test-user authentication + session issuance/refresh
application_login:      NOT APPROVED BY THIS DECISION
evidence:               this record + source-bound account snapshot + T17 managed-project evidence
expiration/review:      material account/region/terms/profile/data-scope change
production_activation:  false
global_gate_closure:    false
```

This APPROVED staging decision closes only this Supabase Auth staging test slice. It must not mark the
shared `processor_retention_contracts` gate globally complete, must not alter the pending consent/legal-basis
records, and must not be cited as production/live authorization.
