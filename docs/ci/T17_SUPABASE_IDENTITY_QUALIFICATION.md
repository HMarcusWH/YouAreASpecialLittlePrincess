# T17 Supabase identity account qualification

**Status: qualification tooling hardened; actual managed-project qualification PENDING.**

This document defines the safe evidence boundary for the T17 Supabase Auth candidate. It does **not** select
Supabase, approve a processor/region/contract, activate production identity, or claim that any managed project
has passed.

## Why the post-#46 hardening exists

Merged PR #46 established the first opt-in qualification harness, but its managed-project shape still trusted an
operator-supplied "refreshed access JWT" and did not retain every account-profile fact from the qualification
checklist. `supabase-identity-qualification/2` closes that evidence gap without enabling login.

Synthetic CI remains offline. `MANAGED_PROJECT` mode is intentionally manual and provider-facing.

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

Use a dedicated owner-authorized qualification project/profile for the signing-key rotation drill. Do not weaken
the verifier to accommodate HS256/shared-secret signing, an enabled/unknown Custom Access Token Hook, unknown
account-policy settings, unchanged signing `kid`, stale reauthentication material, or refresh/AMR/session drift.

Synthetic regression tests use `--pre-rotation-jwks-file`, `--jwks-file` and `--refreshed-token-file` instead of
provider network calls. A synthetic PASS is never managed-project evidence.

## Human/account gates still separate

A technical PASS does not establish any of these:

```text
provider selected                     OWNER DECISION REQUIRED
processor terms                       SEPARATE REVIEW REQUIRED
region/data handling                  SEPARATE REVIEW REQUIRED
retention/deletion                    SEPARATE REVIEW REQUIRED
support/subprocessors                 SEPARATE REVIEW REQUIRED
```

Record those decisions separately with owner/date/scope evidence. The qualification receipt deliberately cannot
turn them into approval claims.

## Still not activation

Even after a real `MANAGED_PROJECT` PASS, T17 still needs the explicit ADR-002 provider decision plus provider
logout/deletion lifecycle, web PKCE/callback/origin integration, cross-device/account recovery, and applicable
native Apple/Google/private-relay evidence.

Production login remains disabled until those gates close.
