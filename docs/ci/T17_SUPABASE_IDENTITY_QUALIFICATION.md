# T17 Supabase identity account qualification

**Status: staging/sandbox `INTENDED_RUNTIME_PROFILE` managed-project qualification PASSED 2026-10-01; production/live and activation remain PENDING.**

This document defines the safe evidence boundary for the owner-selected T17 Supabase Auth implementation provider. The 2026-10-01 owner-authorized staging/sandbox run passed as `INTENDED_RUNTIME_PROFILE`; that closes only the staging exact-profile technical gate. It does **not** approve processor/region/contracts, compose runtime identity, activate production identity, or qualify production/live. The separate owner decision is recorded in [T17 identity-provider decision evidence](T17_IDENTITY_PROVIDER_DECISION_EVIDENCE.md).

## Why the post-#46 hardening exists

Merged PR #46 established the first opt-in qualification harness, but its managed-project shape still trusted an
operator-supplied "refreshed access JWT" and did not retain every account-profile fact from the qualification
checklist. `supabase-identity-qualification/4` keeps those witnesses and additionally binds every receipt to an explicit project purpose without enabling login.

Synthetic CI remains offline. `MANAGED_PROJECT` mode is intentionally manual and provider-facing.


PR #48 factors the live JWKS read through the reusable `SupabaseJwksSource`: one fixed endpoint derived from the reviewed issuer, no redirects, bounded bytes/key count, and typed/redacted provider errors. The current qualification hardening applies the same policy shape to the live refresh exchange: HTTPS issuer validation, no redirects, `trust_env=False`, bounded response bytes and redacted transport failures. Synthetic qualification remains offline through injected fixtures/transports. None of this composes Supabase.

## Managed-project witness

The managed run uses an owner-authorized qualification project and:

1. reads an initial access JWT plus its refresh token from protected files;
2. accepts only a Supabase publishable key (or legacy `anon` key), never a secret/service-role key;
3. fetches the actual project JWKS from the configured issuer;
4. performs one real `grant_type=refresh_token` exchange;
5. proves the refreshed JWT keeps the same `session_id` and AMR-derived `auth_time` while `iat` advances;
6. stops and asks the operator to rotate the asymmetric signing key and complete a genuine new sign-in;
7. fetches JWKS again and proves the new sign-in uses a different trusted `kid`, while the prior signing key
   remains published/trusted;
8. proves the new sign-in has a new session and newer authentication freshness;
9. places the Princess `revoked_before` fence between refresh and reauthentication, rejects the old refreshed
   session as `session_revoked`, and accepts the genuinely reauthenticated session.

The tool never performs password login, key rotation, provider logout or provider-account deletion. Those human
provider actions remain external and owner-authorized.

### 2026-10-01 staging witness

The owner-authorized managed run completed against the intended staging identity profile with safe alias `princess-staging`, `environment=staging`, `provider_mode=sandbox`, and `project_binding=INTENDED_RUNTIME_PROFILE`. The protected receipt is bound to Princess commit `033b9b9c32ee296a28431fbe85d87f3c7ab9199d` and the checked-in staging manifest. The observed account profile had anonymous sign-in disabled, OAuth Server disabled, no Custom Access Token Hook, and asymmetric ES256/P-256 signing.

The live witness passed a real provider refresh on the original password-authenticated session, preserved session continuity and AMR-derived authentication freshness while issuance time advanced, rotated to a new ES256 signing key while retaining the prior asymmetric key in JWKS, completed a genuine second password sign-in with a new session and newer authentication freshness, and passed the Princess `revoked_before` fence in both directions. The full v4 receipt remains outside Git; only its digest/reference and safe witness summary belong in the Git-safe evidence index.

## Configuration facts recorded

A PASS receipt records only safe account-profile facts:

- checked date and Princess commit;
- safe project alias;
- reviewed `supabase/auth` source revision;
- issuer host plus issuer/JWKS URL hashes;
- configured audience and authenticated role;
- explicitly inspected anonymous-sign-in policy and OAuth-server status;
- Custom Access Token Hook state (`disabled` is required);
- asymmetric JWKS algorithms, key IDs, key count and before/after hashes;
- observed access-token algorithms and configured token lifetime as witnessed by `exp - iat`;
- AMR method names, never AMR timestamps;
- live refresh, signing-key-rotation, reauthentication and logout-fence witnesses.

It contains no access JWT, refresh token, rotated refresh token, subject, session ID, absolute authentication
timestamp, API key, issuer URL, JWKS body or provider secret. `provider_selection_claim` and
`production_activation` are always false.

## Protected inputs

Never commit or upload these files:

- initial access JWT;
- refresh token;
- publishable/legacy-anon API key;
- post-refresh genuine reauthentication access JWT.

For managed mode, the reauthentication token file may be absent or stale when the tool starts. After the live
refresh completes, the tool pauses. Replace/write that file only after the required signing-key rotation and
genuine new sign-in, then press Enter.

## Managed-project command

```bash
PRINCESS_SUPABASE_QUALIFY=1 \
python tools/qualify_supabase_identity.py \
  --project-alias <safe-alias> \
  --evidence-kind MANAGED_PROJECT \
  --project-binding <QUALIFICATION_ONLY|INTENDED_RUNTIME_PROFILE> \
  --environment <staging|production> \
  --provider-mode <sandbox|live> \
  --issuer '<exact-reviewed-issuer>' \
  --audience '<exact-reviewed-audience>' \
  --role '<exact-reviewed-role>' \
  --custom-access-token-hook disabled \
  --anonymous-sign-ins <enabled|disabled> \
  --oauth-server <enabled|disabled> \
  --api-key-file /protected/publishable.key \
  --initial-token-file /protected/initial.jwt \
  --refresh-token-file /protected/refresh.token \
  --reauth-token-file /protected/reauth.jwt \
  --output /protected/supabase-identity-qualification.json
```

The receipt must declare both what the managed project proves and which reviewed runtime environment it belongs to:

- `QUALIFICATION_ONLY`: a dedicated/disposable project used to prove provider/profile semantics. A PASS does **not**
  prove that the later runtime tenant/profile has the same settings.
- `INTENDED_RUNTIME_PROFILE`: the project/profile is the actual intended runtime identity profile **for the receipt's bound environment/provider mode**. A staging/sandbox PASS can close the staging technical exact-profile gate only; it does not qualify production/live. A PASS still does not approve processor terms, region/data handling, support, production secrets, callbacks/native configuration or runtime activation.

The v4 tool verifies `environment` + `provider_mode` against the checked-in environment manifest and records that manifest's SHA-256. Current reviewed pairs are staging/sandbox and production/live; local/test/preview are not managed qualification targets.

Use a dedicated owner-authorized `QUALIFICATION_ONLY` project when the signing-key rotation drill must not touch
the intended runtime tenant. If that path is used, a later exact-profile binding/equivalence witness remains required
before composition. Never relabel a `QUALIFICATION_ONLY` receipt as runtime-profile evidence.

Do not weaken the verifier to accommodate HS256/shared-secret signing, an enabled/unknown Custom Access Token Hook,
unknown account-policy settings, unchanged signing `kid`, stale reauthentication material, or refresh/AMR/session
drift.

Synthetic regression tests use `--pre-rotation-jwks-file`, `--jwks-file` and `--refreshed-token-file` instead of
provider network calls. A synthetic PASS is never managed-project evidence.

## Evidence retention

The exact generated receipt remains protected operational evidence and is valid only together with its recorded Princess commit and environment-manifest hash. Keep it outside Git (for example under the
operator's protected evidence store), compute its SHA-256, and commit only the safe reference/digest summary in
[T17 managed-project evidence](T17_SUPABASE_MANAGED_PROJECT_EVIDENCE.md). The receipt is intentionally redacted of
tokens/subjects/session IDs, but still contains operational metadata such as issuer host, key IDs, token lifetime
and account-policy settings that need not be public.

Never commit the initial JWT, refresh token, publishable key, reauthentication JWT or raw receipt by default.

## Human/account gates still separate

The dated Supabase-vs-Clerk comparison and 2026-10-01 owner selection are in [T17 identity-provider decision evidence](T17_IDENTITY_PROVIDER_DECISION_EVIDENCE.md). The owner record selects Supabase; this technical qualification receipt still cannot select a provider or create production approval.

A technical PASS does not establish any of these:

```text
provider selected                     RECORDED 2026-10-01 — SUPABASE AUTH
processor terms                       SEPARATE REVIEW REQUIRED
region/data handling                  SEPARATE REVIEW REQUIRED
retention/deletion                    SEPARATE REVIEW REQUIRED
support/subprocessors                 SEPARATE REVIEW REQUIRED
```

Record those decisions separately with owner/date/scope evidence. The qualification receipt deliberately cannot
turn them into approval claims.

## Still not activation

The ADR-002 provider-selection decision is recorded and the 2026-10-01 staging/sandbox `MANAGED_PROJECT` PASS closes the staging exact-profile technical gate. T17 still needs scoped processor/account evidence plus provider logout/deletion lifecycle, web PKCE/callback/origin integration, cross-device/account recovery, and applicable native Apple/Google/private-relay evidence. Production/live requires its own later qualification and approval.

Production login remains disabled until those gates close.
