# T17 Supabase managed-project evidence

**Status: PASS — staging/sandbox `INTENDED_RUNTIME_PROFILE` qualified 2026-10-01. Production/live remains unqualified.**

This is the Git-safe evidence index for the owner-selected Supabase Auth implementation provider. It is not the
qualification receipt itself and must never be filled with invented PASS data.

The protected receipt was produced by `tools/qualify_supabase_identity.py` using
`supabase-identity-qualification/4` and remains outside Git. The record below contains only the safe staging binding,
receipt SHA-256 and an opaque protected-evidence reference. It does not qualify production/live or activate identity.

## Required evidence record

```text
provider:                    supabase-auth
project_alias:                princess-staging
receipt_version:             supabase-identity-qualification/4
evidence_kind:               MANAGED_PROJECT
project_binding:             INTENDED_RUNTIME_PROFILE
environment:                 staging
provider_mode:               sandbox
environment_manifest_sha256: bc9ef87478461e1a13098e116d34f46c7b84addefbdb65004a2e9a71aa642f1c
checked_date:                2026-10-01
princess_commit:             033b9b9c32ee296a28431fbe85d87f3c7ab9199d
receipt_sha256:              c9e23770d23b5b066cf32596d26bde5564bdd440d460074deb61d0cab1be85fe
protected_evidence_ref:      operator-local:princess-staging-v4-2026-10-01

result:                      PASS
live_provider_refresh:       PASS
same_session_refresh:        PASS
refresh_auth_time_unchanged: PASS
signing_key_rotation:        PASS
genuine_new_session_reauth:  PASS
reauth_auth_time_advanced:   PASS
revoked_before_old_rejected: PASS
revoked_before_new_accepted: PASS

provider_selection_claim:    false
production_activation:       false
```

## Qualified scope

This PASS binds only the owner-authorized **staging / sandbox** identity profile used for the 2026-10-01 witness. The live run used the stock claims profile with anonymous sign-in disabled, OAuth Server disabled, no Custom Access Token Hook, and asymmetric ES256/P-256 signing. It proved live same-session refresh, unchanged AMR-derived authentication freshness across refresh, asymmetric signing-key rotation with both old and new keys trusted, genuine new-session password reauthentication with newer freshness, and both sides of the Princess `revoked_before` fence.

This PASS itself does **not** approve processor terms, region/data handling, retention/deletion/support, callbacks/native configuration, production credentials or production/live activation. A separate 2026-10-01 owner decision now approves only the narrow staging `VERIFY_CREDENTIAL` test slice, and runtime composition must still prove its protected values match a receipt-derived binding before constructing the adapter.

## Project-binding meaning

`QUALIFICATION_ONLY` proves the reviewed Supabase credential/session mechanics on an owner-authorized
qualification project. It does **not** prove the exact later runtime tenant/profile.

`INTENDED_RUNTIME_PROFILE` means the rotated project/profile is the actual intended runtime identity profile for the recorded environment/provider mode.
A staging/sandbox PASS can close only the staging exact-profile technical gate; production/live requires separate environment-bound evidence. Any PASS still does not close
`processor_retention_contracts`, callback/native account configuration, provider lifecycle integration, secret
provisioning or production activation.

If a disposable `QUALIFICATION_ONLY` project is used, retain that PASS as provider/profile-mechanics evidence and
leave the exact runtime profile gate open until a separate reviewed binding/equivalence witness exists.

## Protected material

Do not commit or paste into this file:

- access JWTs;
- refresh tokens;
- publishable/legacy-anon API keys;
- reauthentication JWTs;
- raw JWKS documents;
- the full qualification receipt;
- private contracts or support/account correspondence.

A synthetic receipt cannot satisfy this record. A failed/incomplete live run remains PENDING rather than being
summarized as partial approval.
