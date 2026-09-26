# Product contract v1

T01 makes this directory the **wire-contract source of truth** for the product layer. It does not replace the 272-feature numerical database, the reviewed T26 interpretation database, or T03 consent policy. It references and binds those authorities by version and digest.

## One construction path

`tools/generate_product_contracts.py` loads the reviewed source schemas, feature authority, T26 database, T03 purpose registry, and method-capability declarations. It rejects duplicate keys, unsupported or unbounded schema constructs, unsafe/external references, missing canonical features, method cycles, and incompatible source structure before it emits anything.

The generated bundle is:

- `manifest.json` — contract members, authority digests, root schemas and bundle digest;
- `src/princess_contracts/generated.py` — generated Python wire DTO declarations and embedded authority data;
- `packages/contracts/src/generated.ts` — generated TypeScript wire declarations with the **same field names**;
- `contracts/http/openapi-components.json` — OpenAPI 3.1 schema components derived from the same roots;
- `schema/method_capabilities/resolved.json` — transitive learned/provider dependency resolution.

Generated artifacts are reviewable outputs, not independent authorities. CI regenerates them in memory and requires byte-for-byte equality.

## Runtime boundary

`princess_contracts.runtime.compile_document()` is the only authoritative raw-object construction path. A valid input produces an immutable `ValidatedDocument`; any schema or semantic issue produces `value=None`. Callers must not construct an authoritative product object by parsing a JSON object into a language-specific interface and skipping this step.

Cross-document rules remain explicit operations because they require two already-validated values:

- `validate_projection(report, view)` proves that a view is an authorization-filtered subset of one saved report, not a second report engine;
- `validate_premium_output(packet, output)` proves that model output cannot escape the frozen packet's questions, candidates or support facts.

Canonical JSON is UTF-8 JSON with stable object-key ordering and finite values only. Digests are over canonical DTO content, never `repr()`, localized display text, or provider objects.

## Handoffs

- **T02** persists contract values and authorization events; SQL/provider models do not become wire DTOs.
- **T05** fills `EvidenceBundle` with real repeated observations and coordinate provenance. It does not manufacture new feature IDs.
- **T09** builds immutable `ReportDocument` snapshots and authorization-filtered `ReportViewModel` projections.
- **T10/T17/T29–T31** consume generated TypeScript/API facts. Clients may lay them out differently but do not calculate a second measurement, percentile, entitlement or report truth.
- **T15** creates a bounded `PremiumPacket` from a saved report and T26; provider output must validate as `PremiumOutput` and then pass packet-level validation before storage.
- **T19** owns purchase/credit state. Entitlements authorize operations; they never rewrite measurements or report facts.

The generated TypeScript is intentionally toolchain-neutral in T01. T28 owns the pinned pnpm/Node workspace and TypeScript compilation environment; it must consume this exact generated surface rather than regenerating a different model.

## Change policy

Version contracts rather than silently rewriting saved report meaning. A change to a source schema, canonicalization semantics, authority binding, generated field, capability closure or compatibility rule requires regeneration, positive and negative fixtures, and review. A downstream task must not add a parallel DTO to bypass an inconvenient contract.
