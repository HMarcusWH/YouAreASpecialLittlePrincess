# T17 Supabase identity account qualification

**Status: tooling implemented; actual managed-project qualification PENDING.**

This document defines the safe evidence boundary for the T17 Supabase Auth candidate. It does **not** select Supabase, approve a processor/region/contract, activate production identity, or claim that any managed project has passed.

## What the harness does

`tools/qualify_supabase_identity.py` is an explicit opt-in, offline qualification command. It consumes an operator-captured JWKS document plus three short-lived access JWTs:

1. an initial real authentication;
2. a refresh of that same provider session;
3. a later genuine reauthentication/new provider session.

It verifies all three through the existing `SupabaseIdentityProvider`, proves that refresh keeps the original signed authentication freshness and session ID, proves that genuine reauthentication advances freshness on a new session, and exercises the Princess `revoked_before` fence between the refresh and reauthentication timestamps.

The harness makes **no network calls** and performs **no provider mutation or revocation**. Capturing/refreshing/reauthenticating the provider credentials is an owner-authorized external step.

## Safety boundary

Never commit or upload the input files. They may contain bearer credentials or account-specific JWKS material. Run from a protected workstation/runner and destroy the token files after the receipt is produced.

The receipt `supabase-identity-qualification/1` contains only:

- an operator-chosen safe project alias;
- evidence kind (`SYNTHETIC_TEST` or `MANAGED_PROJECT`);
- hashes of issuer and JWKS, not their raw values;
- configured audience/role and observed algorithms/counts;
- boolean relationship/fence witnesses;
- relative timing deltas;
- the pinned reviewed `supabase/auth` source revision.

It contains no JWT, refresh token, subject, session ID, absolute authentication timestamp, issuer URL, JWKS body or production secret. `provider_selection_claim` and `production_activation` are always false.

## Actual managed-project command

The command is intentionally gated:

```bash
PRINCESS_SUPABASE_QUALIFY=1 \
python tools/qualify_supabase_identity.py \
  --project-alias <safe-alias> \
  --evidence-kind MANAGED_PROJECT \
  --issuer '<exact-reviewed-issuer>' \
  --audience '<exact-reviewed-audience>' \
  --role '<exact-reviewed-role>' \
  --custom-access-token-hook disabled \
  --jwks-file /protected/jwks.json \
  --initial-token-file /protected/initial.jwt \
  --refreshed-token-file /protected/refreshed.jwt \
  --reauth-token-file /protected/reauth.jwt \
  --output /protected/supabase-identity-qualification.json
```

The three credentials must be collected in that order. Leave enough time between refresh and reauthentication for the timestamps to be strictly ordered. If the project has an enabled or unknown Custom Access Token Hook, an HS256/shared-secret profile, or token/session semantics different from the code-qualified candidate, stop and review rather than weakening the harness.

## Evidence still required before T17 can progress to activation

A PASS receipt is only technical account-profile evidence. Separately record and approve:

- explicit ADR-002 provider selection;
- managed-project deployed issuer/audience/roles and signing/JWKS settings;
- Custom Access Token Hook state;
- processor/subprocessor terms, region, retention/deletion and support obligations;
- provider logout/deletion lifecycle behavior;
- web PKCE callback/origin configuration and cross-device recovery;
- native Apple/Google/private-relay behavior where applicable.

Only after those gates may a later PR compose the provider or add production PKCE/access+refresh handling.
