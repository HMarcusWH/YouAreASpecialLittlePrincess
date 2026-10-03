# T17 Supabase Auth operational policy

**Status: TOOLING READY — SELECTED-ACCOUNT AUTH SETTINGS SNAPSHOT PENDING. Application-managed login/refresh remains disabled.**

This record defines the T17 operational policy that must be satisfied before Princess activates any application-managed
Supabase sign-in or refresh flow. Public Supabase documentation is provider behavior evidence; it does not substitute
for the actual selected staging project's settings.

The selected staging project remains bound by the existing Git-safe project-ref hash and account evidence. The raw
project ref, Supabase Management API access token, and raw Auth configuration response remain outside Git.

## Selected-account evidence source

Current Supabase documentation exposes the effective Auth configuration through:

```text
GET /v1/projects/{ref}/config/auth
```

Current rate-limit documentation also shows that project Auth limits can be inspected through that Management API
and that IP-limited Auth endpoints use provider-side throttling. The safe capture tool for Princess is:

```text
tools/build_supabase_auth_settings_snapshot.py
```

The operator must provide:

```text
--project-ref-file   /protected/princess-staging-project-ref.txt
--auth-config-file   /protected/princess-staging-auth-config.json
--captured-date      YYYY-MM-DD
--protected-evidence-ref operator-local:princess-staging-auth-config
--output             docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json
```

Both protected inputs must be absolute paths outside the Git checkout. The tool performs no provider request and
accepts no Supabase Management API token, application API key, password, access token or refresh token.

The generated `supabase-auth-settings/3` snapshot is Git-safe only because it allowlists reviewed non-secret
fields, hashes the raw project reference before comparison with the already-qualified Princess staging project
binding, hashes the exact protected Management API response bytes into `source_response_sha256`, records only
an opaque `protected_evidence_ref`, and derives `evidence_sha256` over the complete Git-safe snapshot envelope.
The source-response digest is derived by the builder and is never supplied by the operator. The envelope digest
makes valid-looking post-generation edits to that digest, capture metadata or safe evidence references fail closed
unless the complete safe artifact is deliberately regenerated.

## Required selected-account fields

The real snapshot must contain the selected staging account's exact current values for:

- `rate_limit_anonymous_users`;
- `rate_limit_email_sent`;
- `rate_limit_sms_sent`;
- `rate_limit_verify`;
- `rate_limit_token_refresh`;
- `rate_limit_otp`;
- `rate_limit_web3`;
- `security_sb_forwarded_for_enabled`.

Missing values are not filled from documentation defaults. Unknown provider fields are ignored rather than copied
into Git. The reviewed safe projection remains independently canonicalized and SHA-256 bound. The complete v3
Git-safe envelope is also canonicalized and hashed, so unrelated raw provider fields leave the projection digest
unchanged but still change the source-response/envelope evidence because the exact protected response bytes changed.

The generated snapshot must always state:

```text
snapshot_version:             supabase-auth-settings/3
source_response_sha256:       <derived from exact protected /config/auth bytes>
evidence_sha256:              <derived from complete Git-safe snapshot envelope>
protected_evidence_ref:       <opaque safe reference>
contains_secrets:             false
application_login_activation: false
production_activation:        false
```

A generated snapshot is account evidence, not an activation command.

## Retry ownership

Princess keeps connector retry ownership at the **application/caller** boundary, matching the existing
`CapabilityProfile.retry_owner = "application"` default.

For future application-managed authentication:

| Failure class | Princess policy |
|---|---|
| Invalid input / bad credentials / unauthenticated | No automatic retry. User action or a new authentication ceremony is required. |
| Permanent provider rejection | No automatic retry. |
| Provider 429 / typed `RateLimited` | Do not retry before the provider cooldown / `Retry-After` evidence. No tight loop and no local backoff that ignores the provider throttle. |
| Provider 429 without a trustworthy cooldown hint | Surface rate limiting and stop automatic retry. A later transport implementation may define a bounded local cooldown only with explicit evidence. |
| Network failure / provider 5xx translated to `TransientUnavailable` | Eligible only for bounded, application-owned retry once the actual login/refresh transport exists. This policy intentionally does not invent retry counts or delays before that transport is selected. |
| Invalid/revoked/reused refresh credential | Do not loop. Clear or fence the unusable local refresh state and require authentication according to the later reviewed session design. |

Any future Supabase SDK/client integration must have its own retry behavior reviewed. Hidden SDK retries must not
silently become a second retry owner.

## Refresh concurrency

Application-managed refresh must be **single-flight per session**. If several Princess requests discover that the
same session needs refresh, they must converge on one refresh exchange rather than fan out parallel refresh calls.

This is required because provider limits are shared operational ceilings; they are not a per-request invitation to
consume the full available quota.

The exact locking/storage mechanism belongs to the later application-session implementation. This document fixes
the invariant, not the implementation primitive.

## Abuse controls

Provider rate limits are a last-line provider control, not Princess's complete abuse policy.

Before public login, Princess must preserve these boundaries:

- the selected account's effective rate-limit values are treated as upper provider constraints, not per-user budgets;
- application admission/cooldown controls must prevent one account/session/client from deliberately exhausting a
  shared provider bucket;
- bad-credential responses must not create an automatic retry loop;
- credential bodies, passwords, access/refresh tokens and provider secrets must never enter ordinary logs;
- request bodies and callback inputs remain bounded and validated;
- provider anonymous sessions remain outside the already-qualified Princess profile;
- enabling CAPTCHA, social login, passkeys, phone auth or other new authentication methods is a separate product/
  account/client configuration decision and is not implied by this policy.

### IP forwarding

Current Supabase documentation states that `Sb-Forwarded-For` based Auth rate limiting must be explicitly enabled
and that forwarded end-user IP use requires a server-side secret API key; publishable and legacy anon/service-role
keys are not sufficient for that feature.

Therefore this PR only **records** `security_sb_forwarded_for_enabled`. It does not enable IP forwarding, add a
Supabase secret key, or trust arbitrary client-supplied forwarding headers. Any later decision to use this feature
requires a separate least-privilege and trusted-proxy review.

## Gate interaction

The final staging closeout is atomic across three evidence classes:

```text
real staging runtime conformance PASS
                 AND
selected-account Auth settings + operational policy evidence
                 AND
disposable provider cleanup evidence
                 |
                 v
application-auth implementation may proceed under a separate disabled/reviewed scope
```

The conformance harness merged in PR #57 remains a separate live witness, and cleanup remains a separate
owner-authorized provider operation. The final closeout checker also requires the Auth-settings capture date to be
the same as or later than the conformance date and cleanup to be the same as or later than both. This policy cannot
convert any PENDING state into PASS. The existing 2026-10-01 owner decision still does not approve
application-login activation or production/live identity.

## Evidence status

The file below must be generated from a real selected-account Management API export before this gate can be called
complete:

```text
docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json
```

Until that file exists with validated selected-account values, the Auth limits part of the T17 acceptance gate
remains **PENDING**.

## Current provider references

Checked 2026-10-02:

- Supabase Auth rate limits: https://supabase.com/docs/guides/auth/rate-limits
- Supabase Management API Auth config: https://supabase.com/docs/reference/api/v1-get-auth-service-config
- Supabase CAPTCHA guidance: https://supabase.com/docs/guides/auth/auth-captcha
- Supabase security configuration index: https://supabase.com/docs/guides/security/product-security

These public references describe provider behavior only. The selected-account snapshot remains the authority for
Princess staging account values.
