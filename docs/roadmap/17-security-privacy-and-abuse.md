# 17 — Security, privacy, consent and abuse controls

[Index](00-index.md) · [Data](01-data-architecture.md) · [Intake/API](05-release-operations.md) · [Connectors](../connectors/README.md) · [Tests](16-testing-evals-and-quality-gates.md).

## Trust boundaries

Treat uploaded bytes, image text, filenames, client metadata, deep links, store proofs, webhook bodies, generated model text and cached report payloads as untrusted. Authenticate a principal, authorize the object/operation, validate input, perform the bounded use case, then recheck authorization at publication/asset issuance. Database and storage identifiers are not access tokens.

Protect account/sample/run/report/region links with composite constraints and non-owner runtime-role tests. No API/worker uses a database superuser or BYPASSRLS role for ordinary access. A sharing grant is an explicit field projection, not a right to query private rows. Partner comparison requires both authorized inputs and a separate disclosure scope.

Session freshness is separate from token freshness. Logout-everywhere and account deletion set a durable local `revoked_before` fence; a provider merely minting a new token after that time is not proof that the person reauthenticated. Only a trustworthy authentication-time/session mechanism selected under ADR-002 may reopen the account after the fence. Unknown freshness fails closed, impossible future authentication times are rejected before account state changes, and provider-side session revocation must not be claimed unless the selected adapter actually performs it.

## Safe media intake

Allow only reviewed raster formats and normalize through constrained decoding. Enforce compressed bytes, decoded pixels, dimensions, animation/frame count, decode time, CPU/memory and worker concurrency. MIME extension/client headers are hints, not verification. Strip unnecessary EXIF/location metadata from derived images. Preserve transform lineage and author-approved original retention separately.

Presigned uploads are bearer capabilities. Do not analyze a mutable object that can still be overwritten using a live upload URL. Bind completion to verified bytes/checksum/version and copy/promote to an immutable internal key or use tested version/conditional semantics. A storage ETag is not universally a content hash. Reject arbitrary user URLs and internal-network fetches; the model/render workers receive only server-approved assets.

Rate limits cover account, guest session, network signal, decoded work, storage, exports, payment-verification calls and model spend. Abuse challenges and device attestation supplement quotas; neither proves identity or replaces consent. Unknown attestation outcomes have documented fallback behavior. Turnstile or another third-party risk service is not part of the deterministic measurement computation; keep it outside the Free inference dependency graph and provide a controlled fallback when unavailable.

## Consent, purpose and retention

Implement append-only grant/withdrawal events with subject, purpose, policy version, scope, actor, effective time and evidence reference. The T03 draft contracts, fixtures and reference evaluator are in [docs/privacy](../privacy/README.md). Separate service processing, saved visual history, third-party AI image processing, reference contribution, public example sharing and partner comparison. No prechecked donation, coerced share or inferred model consent from payment alone.

The app initially targets an owner-approved adult/non-consequential use case. Do not infer age from handwriting or use the playful brand as permission to collect children’s data. Exact age eligibility, parental requirements, controller/legal basis, region, retention and notices are human policy decisions and release gates. Engineering must support denied/unknown states rather than fabricating legal clearance.

Deletion revokes access first, marks a tombstone/epoch, cancels queued work, prevents stale publication and removes originals, derivatives, exports, object versions, shared routes and applicable corpus membership. Store/legal accounting records are retained only under the separately approved obligation and purpose. Reconcile backups using tombstones before restoring service. Provider retention and already downloaded exports cannot be promised instantly revocable.

## Premium and content safety

Do not treat handwriting text as instructions. No tool calling, browsing or autonomous retrieval in initial Premium. Provider outputs are untrusted structured data: reject unknown/support IDs, raw HTML/URLs, new numerical claims, disallowed consequential inferences and cross-report evidence. Safely escape all text and use content security policies; do not pass model strings to a template compiler.

A reviewed T26 structure is not empirical graphology validation. A label or entertainment disclaimer does not excuse false capabilities or harmful claims. Keep mechanics/proxies/reference/traditional/AI evidence labels attached on every surface. Add user feedback/report-content flow and restricted human review with consent before exposing private samples to support personnel. Do not enable public galleries or social feeds in v1.

## Commerce, native and sharing security

Verify store/backend proofs and environment/account binding before grants. Webhook replay and direct native claim converge on the same unique transaction. A URL or push notification must never contain a usable purchase credit or authorize a report. Redacted share tokens are unguessable, hashed at rest, scope-bound and revocable; use short asset tickets and conservative cache rules.

Mobile secure storage contains credentials only. Clear caches on sign-out/account switch, guard late responses, bound temporary exported files and review OS backup behavior. Universal/App Links require verified domain association and route allowlists. Native signing/release keys are protected separately from runtime credentials.

## Threat-model deliverables

T23 must publish a reviewed threat model with assets, actors, trust boundaries, abuse cases, mitigations, residual risks and owner decisions. Include upload bombs, storage overwrite races, IDOR/cross-tenant access, share metadata leakage, SSRF in render/vision inputs, prompt injection, forged/reordered store events, duplicate credit spend, deletion races, compromised notification tokens, SDK data leakage, stale mobile clients and backup resurrection.

No unreviewed processor receives private writing through telemetry, analytics, design files, CI fixtures or crash dumps. See [18](18-observability-support-and-cost-control.md) for allowlisted observability and [19](19-provider-decision-register.md) for data-processing approval records. T25 requires the actual security/privacy evidence, not a statement that the framework is secure.
