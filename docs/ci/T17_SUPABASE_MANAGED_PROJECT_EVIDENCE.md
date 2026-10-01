# T17 Supabase managed-project evidence

**Status: PENDING LIVE MANAGED_PROJECT RUN.**

This is the Git-safe evidence index for the owner-selected Supabase Auth implementation provider. It is not the
qualification receipt itself and must never be filled with invented PASS data.

The protected receipt is produced by `tools/qualify_supabase_identity.py` using
`supabase-identity-qualification/4`. Keep that JSON outside Git. After an actual owner-authorized run, record only
the safe binding below plus the receipt SHA-256 and an opaque protected-evidence reference.

## Required evidence record

```text
provider:                    supabase-auth
receipt_version:             supabase-identity-qualification/4
evidence_kind:               MANAGED_PROJECT
project_binding:             <QUALIFICATION_ONLY|INTENDED_RUNTIME_PROFILE>
environment:                 <staging|production>
provider_mode:               <sandbox|live>
environment_manifest_sha256: PENDING
checked_date:                PENDING
princess_commit:             PENDING
receipt_sha256:              PENDING
protected_evidence_ref:      PENDING

result:                      PENDING
live_provider_refresh:       PENDING
same_session_refresh:        PENDING
refresh_auth_time_unchanged: PENDING
signing_key_rotation:        PENDING
genuine_new_session_reauth:  PENDING
reauth_auth_time_advanced:   PENDING
revoked_before_old_rejected: PENDING
revoked_before_new_accepted: PENDING

provider_selection_claim:    false
production_activation:       false
```

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
