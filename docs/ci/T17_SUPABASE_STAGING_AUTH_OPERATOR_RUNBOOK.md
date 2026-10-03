# T17 Supabase staging Auth operator runbook

**Status: OPERATOR ACTION REQUIRED — no PASS is claimed by this file.**

This runbook is the execution checklist for the three real evidence classes required by
`tools/check_supabase_staging_auth_closeout.py`. It does not replace the protected operator procedures and must not
be used to hand-author PASS artifacts.

## Fixed revisions

Runtime conformance is frozen to:

```text
ce6fe884305de93c6a13d091b31a3ff0d72dc5bf
```

The evidence branch must be created from current `main` containing the post-#60 closeout tooling and this
runbook. Do not pin evidence assembly to a historical main SHA.

The frozen SHA above is only the runtime witness binding. Cleanup v2 and final evidence assembly must use current
code from the evidence branch.

## Protected material

Keep all of the following outside Git:

- v4 qualification receipt;
- raw Princess staging issuer;
- disposable staging access JWT;
- raw Princess staging project ref;
- raw `GET /v1/projects/{ref}/config/auth` response;
- protected runtime-conformance receipt;
- protected cleanup attestation;
- any Management API/admin credential used by the authorized operator;
- provider subject/session identifiers, email/phone and other private account metadata.

All protected file arguments below must be absolute paths outside the checkout.

## 1. Runtime conformance witness

Create or use a clean checkout at the frozen witness SHA and verify it is clean:

```bash
git rev-parse HEAD
git status --porcelain
```

Expected HEAD:

```text
ce6fe884305de93c6a13d091b31a3ff0d72dc5bf
```

`git status --porcelain` must be empty before running the witness.

Run:

```bash
PRINCESS_SUPABASE_STAGING_CONFORMANCE=1 \
python tools/verify_supabase_staging_runtime.py \
  --qualification-receipt-file /protected/supabase-identity-qualification-v4.json \
  --issuer-file /protected/princess-staging-issuer.txt \
  --access-token-file /protected/disposable-staging-access.jwt \
  --receipt-output /protected/supabase-staging-runtime-conformance.json \
  --safe-index-output docs/ci/T17_SUPABASE_RUNTIME_CONFORMANCE.md \
  --protected-evidence-ref operator-local:princess-staging-runtime-conformance
```

Do not edit the generated PASS index. Retain the protected receipt outside Git.

## 2. Selected-account Auth settings

Capture the real selected Princess staging project's current Management API response for:

```text
GET /v1/projects/{ref}/config/auth
```

Keep the raw response and project ref outside Git. Do not substitute documentation defaults.

From a checkout containing the current builder, run:

```bash
python tools/build_supabase_auth_settings_snapshot.py \
  --project-ref-file /protected/princess-staging-project-ref.txt \
  --auth-config-file /protected/princess-staging-auth-config.json \
  --captured-date YYYY-MM-DD \
  --protected-evidence-ref operator-local:princess-staging-auth-config \
  --output docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json
```

The v2 builder must source the exact selected-account values for all allowlisted `rate_limit_*` fields and
`security_sb_forwarded_for_enabled`. It hashes the exact protected Management API response bytes into
`source_response_sha256` and records only an opaque `protected_evidence_ref`; the operator cannot hand-enter
the source digest.

## 3. Dispose of the witness identity

After a successful runtime witness, use owner-authorized Supabase controls to:

1. revoke/sign out all sessions for the one disposable conformance test user;
2. revoke provider refresh/session state for that user;
3. delete that disposable Auth user;
4. leave the Princess staging project intact.

Already-issued access JWTs may remain cryptographically valid until `exp`; do not record cleanup as instantaneous
access-token invalidation.

The protected cleanup attestation must describe exactly one affected test user and must not contain provider
user/session identifiers or a hand-entered conformance receipt digest.

Required safe facts:

```text
checked_date:                                 YYYY-MM-DD
operator_role:                                product/technical owner
affected_test_population_count:               1
all_sessions_for_test_user_revoked:           true
provider_refresh_state_revoked:               true
disposable_auth_user_deleted:                 true
persistent_princess_binding_created_by_witness: false
application_login_active:                     false
jwt_age_out_required:                         true
project_decommission:                         NOT_APPLICABLE
production_activation:                        false
protected_evidence_ref:                       operator-local:<safe-reference>
```

`checked_date` must be the same as or later than the bound runtime-conformance receipt's `checked_date`.
The cleanup builder rejects evidence that claims cleanup occurred before the witness.

## 4. Generate cleanup v2 on current code

From the current evidence branch containing cleanup-v2 tooling:

```bash
python tools/build_supabase_staging_cleanup_evidence.py \
  --project-ref-file /protected/princess-staging-project-ref.txt \
  --cleanup-input-file /protected/princess-staging-cleanup.json \
  --conformance-receipt-file /protected/supabase-staging-runtime-conformance.json \
  --output docs/ci/T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json
```

The builder validates the protected runtime receipt and derives `conformance_receipt_sha256` from its exact bytes.

## 5. Assemble only Git-safe evidence

The evidence PR must ultimately contain these three real artifacts:

```text
M docs/ci/T17_SUPABASE_RUNTIME_CONFORMANCE.md
A docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json
A docs/ci/T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json
```

Then reconcile the T17 status/evidence docs without widening application-login or production authority.

## 6. Atomic closeout

Run:

```bash
python tools/check_supabase_staging_auth_closeout.py
```

The required success line is:

```text
PASS: Supabase staging Auth evidence gates are complete without widening login/production authority
```

The final checker independently requires:

```text
runtime conformance checked_date
    <= Auth settings captured_date
    <= cleanup checked_date
```

Same-day capture/cleanup is valid. A failure is a finding. Do not alter generated evidence or weaken validators to
force PASS.

## 7. Privacy review before ready-for-review

Inspect the complete diff and reject the PR if it contains any raw credential or provider identity material,
including JWT-shaped strings, refresh tokens, API/admin keys, raw project ref, raw issuer URL, provider user/session
UUIDs, Princess principal IDs, email/phone, raw JWKS, raw Management API responses or protected receipt contents.

## Authority boundary

Even after a successful closeout, these remain unchanged:

```text
application_login:      NOT APPROVED BY THIS DECISION
production_activation:  false
global_gate_closure:    false
```

T17 therefore remains `IN_PROGRESS`; application-managed Auth/session implementation is a later disabled/reviewed
software slice.
