# Consent, rights and collection contracts (T03 draft)

Status: `DRAFT_PENDING_OWNER_REVIEW`. Human-readable specification: [docs/privacy](../../docs/privacy/README.md).

These are versioned draft contracts. T01 owns the final product wire DTOs and code generation. It maps these schemas into `contracts/product/v1` and generated Python/TypeScript. Until then, the IDs, enums and semantics here are the source, and any change must keep the validator and fixtures green.

## Layout

| Path | Contents |
|---|---|
| `v1/schemas/*.schema.json` | JSON Schema 2020-12 documents: shared definitions; purpose, notice, retention, lineage, source-rights and pilot-gate registries; consent events; scenario fixtures; collection protocol and collection manifests. |
| `v1/purposes.json` | Purpose registry v1: 9 draft purposes and 2 that are not offered. |
| `v1/notices.json` | Draft notices with English and Swedish choice copy. Not legal text; no effective dates. |
| `v1/retention.json` | Retention classes. Every period is null pending an owner decision. |
| `v1/deletion_lineage.json` | Artifact-kind DAG and deletion actions. |
| `v1/source_rights.json` | Code, data and model-weight rights per source; all pending review. |
| `v1/pilot_gate.json` | `pilot_rights_consent` gate: `PENDING`, with 11 owner decisions outstanding. |

<a id="fixtures"></a>
## Fixtures

All fixtures are synthetic. They contain opaque IDs and hashes of labels, never real handwriting.

- `v1/fixtures/scenarios/`: thirteen append-only event logs with expected outcomes. They cover:
  - grant, deny and withdraw;
  - declining keeps Free;
  - payment is not AI consent;
  - the uploader lacks author authority;
  - withdrawal during use;
  - a reused obsolete notice;
  - a purpose version change;
  - partner comparison versus sharing;
  - precheck, eligibility and evidence;
  - a pilot signed agreement;
  - restrictive choices failing closed;
  - eligibility bound to the grant;
  - a service purpose change requiring the current version's grant.

  Scenarios run in fixture mode, the only mode in which draft purposes are usable.
- `v1/fixtures/collection/`: fourteen collection manifests, each with its own synthetic consent log and the error codes it should produce. They include a duplicate specimen counted as a writer, a repeat capture filed under another writer or pointing to a later capture, a release without permission, a withdrawal before the cutoff or before publication (`publish_at`), a page written after the cutoff, and session 2 without a baseline.

## Validation

```bash
python tools/validate_consent_protocol.py
python -m pytest -q tests/test_consent_protocol.py
```

The schema validator supports a strict keyword subset and fails on anything else, so a schema can never silently lose a constraint. Objects are closed, and integers exclude booleans and floats. JSON with duplicate keys or `NaN`/`Infinity` is rejected.
