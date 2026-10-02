# T17 Supabase staging runtime conformance

**Status: PENDING REAL STAGING RUN. Tooling exists; no PASS is claimed by this file.**

This record is the Git-safe index for the next T17 operational witness. The owner-approved scope is still only the
qualified **staging / sandbox** `IdentityProvider` capability `VERIFY_CREDENTIAL`. PR #56 composed that exact
profile; `tools/verify_supabase_staging_runtime.py` now provides the operator-only harness that can prove a real
already-issued disposable staging access JWT passes the actual Princess composition and application identity path.

A code merge, synthetic test or this PENDING template is not a real Supabase conformance PASS.

## Path under test

```text
protected v4 qualification receipt
        |
        +--> build_binding() using the checked-in account snapshot
        |
protected issuer + receipt-derived runtime binding
        |
        +--> reviewed staging manifest
        |
        +--> compose_identity_provider()
        |
        +--> SupabaseJwksSource
        |
        +--> SupabaseIdentityProvider.verify_credential()
        |
real disposable staging access JWT
        |
        +--> IdentityService
        |
        +--> InMemoryIdentityStore
        |
        +--> stable ACCOUNT principal
```

The harness deliberately does **not** start the complete FastAPI staging process. Full API startup still has
unrelated ObjectStore/Payment/Abuse provider gates. It also deliberately does not use PostgreSQL, a Supabase SDK,
a publishable/anon key, a secret/service-role key, a password or a refresh token.

## Operator command

Run the command from the repository root on a clean checkout at
`7cf6371a1daec3cfd46f4adf35d6175c57452cc0`, the frozen witness revision required by the closeout checker. All
protected paths must be absolute and resolve outside the Git checkout. The raw issuer is read from a protected file
so it cannot leak through shell history/process arguments. The complete three-class procedure is documented in
[T17 Supabase staging Auth operator runbook](T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md).

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

The access JWT must already have been obtained through the separately approved operator-controlled disposable
test-user procedure. This tool does not perform sign-in or refresh and therefore does not activate
application-managed authentication.

The checkout must be clean. The harness records the exact Princess commit before writing the safe index.

## Required PASS record

A real PASS replaces this template with a generated Git-safe record containing only these evidence classes:

- receipt version/date and exact Princess commit;
- SHA-256 of the protected operational receipt;
- opaque protected-evidence reference;
- existing v4 qualification/account/manifest/project evidence hashes;
- receipt-derived issuer/audience/role hashes;
- runtime-binding hash;
- boolean witnesses that live JWKS retrieval occurred, the credential verified, `IdentityService` authenticated it,
  repeat authentication converged on one ACCOUNT principal, usable authentication freshness/session identity were
  present and the credential was unexpired;
- explicit false values for application login, production activation and global processor-gate closure.

The full operational receipt remains outside Git even though its schema is privacy-minimized.

## Material forbidden from Git or ordinary logs

Never commit or print:

- access or refresh JWTs/tokens;
- password, publishable/legacy-anon key, secret key or service-role key;
- provider subject UUID or session UUID;
- Princess principal ID;
- raw issuer URL or project reference;
- raw JWKS or key material;
- email/phone/private account metadata;
- login URLs or provider responses containing credential material.

The harness rejects protected input/output paths inside the repository and maps unexpected failures to one generic
safe error instead of forwarding provider/library exception text.

## Cleanup after the real run

The conformance harness has no provider admin credential and intentionally cannot revoke/delete the disposable
provider identity. After a successful witness, the authorized operator must:

1. globally revoke/sign out the disposable Supabase session(s);
2. delete the disposable Supabase Auth user using owner-authorized provider controls;
3. keep in mind that already-issued access JWTs can remain cryptographically valid until their `exp`;
4. retain only safe cleanup evidence (date, operator role, population count and success/failure), never provider
   user/session identifiers.

Do not mark provider cleanup as performed merely because the conformance receipt says PASS.

## Scope non-claims

Even after a PASS, this record does not prove or authorize:

- complete staging API startup or ObjectStore/Payment/Abuse composition;
- application-managed sign-in, PKCE, refresh-token transport or public onboarding;
- provider logout/deletion through the Princess adapter;
- Apple/Google/private-relay/recovery behavior;
- Supabase Storage/database use as the Princess application data plane;
- production/live identity;
- global `processor_retention_contracts` closure.

Production/live remains a separate managed-project qualification and human approval gate.
