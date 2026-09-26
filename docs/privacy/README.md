# Privacy, consent and collection drafts (T03)

[Index](../roadmap/00-index.md) · [T03 brief](../roadmap/06-agent-backlog.md#t03) · [Security/privacy chapter](../roadmap/17-security-privacy-and-abuse.md) · [Corpus chapter](../roadmap/02-corpus-benchmarks.md)

**Status: draft pending owner review.** Nothing here is a legal opinion, an approved notice, a decided retention period, a cleared dataset or permission to recruit anyone. The `pilot_rights_consent` gate is `PENDING` in [pilot_gate.json](../../contracts/consent/v1/pilot_gate.json). An agent cannot change that state.

## What T03 provides

| Deliverable | Human-readable | Machine-readable |
|---|---|---|
| Purpose-specific permissions, grant/deny/withdraw semantics | [Purposes and consent](purposes-and-consent.md) | [purposes.json](../../contracts/consent/v1/purposes.json), [notices.json](../../contracts/consent/v1/notices.json), [consent-event schema](../../contracts/consent/v1/schemas/consent-event.schema.json) |
| Retention configuration and deletion lineage | [Retention and deletion](retention-and-deletion.md) | [retention.json](../../contracts/consent/v1/retention.json), [deletion_lineage.json](../../contracts/consent/v1/deletion_lineage.json) |
| Source rights: code, data and model weights kept separate | [Source rights](source-rights.md) | [source_rights.json](../../contracts/consent/v1/source_rights.json) |
| Collection protocol, original prompts, capture/author guidance, pilot handoff | [Collection protocol](collection-protocol.md) | [content/collection/v1](../../content/collection/v1/manifest.json), [pilot_gate.json](../../contracts/consent/v1/pilot_gate.json) |
| Fixtures for grant, deny, withdraw and no-authority cases | [Fixture index](../../contracts/consent/README.md#fixtures) | `contracts/consent/v1/fixtures/` |

## Non-negotiable rules encoded here

- Service processing, saved history, third-party AI processing, ordinary sharing, partner comparison, reference contribution, engineering evaluation, support review and analytics are **separate purposes**. A grant covers exactly one purpose version and one scope.
- Every choice starts **unselected**. Declining any optional purpose leaves the Free report unchanged; the validator proves Free depends only on `service_processing`.
- A purchase or entitlement is **never** consent. Only the author (or, for account-level analytics, the account holder) can grant. An uploader cannot grant for someone else's handwriting.
- Withdrawal is always available, takes effect when recorded, and work already running must re-check permission before it publishes.
- Adult eligibility is self-declared without a birth date. Unknown is not adult, and age is never inferred from handwriting.
- Missing is not permission. No record means `NOT_ASKED`, not granted.

## Validate

```bash
python tools/validate_consent_protocol.py
python -m pytest -q tests/test_consent_protocol.py
```

The validator is stdlib-only. It enforces the JSON Schemas with a strict subset validator that rejects unsupported keywords rather than ignoring them. It then applies the semantic rules and runs every scenario through a reference permission evaluator. T01 maps these draft contracts into `contracts/product/v1` and generated DTOs. T02 implements the append-only ledger and must reproduce the evaluator's behaviour.

## Owner review checklist

The eleven decisions in [pilot_gate.json](../../contracts/consent/v1/pilot_gate.json) must be recorded before T11 may recruit anyone. They cover controller and legal basis, age threshold, retention periods, aggregates after withdrawal, notice wording, the collection agreement, compensation, recruitment channels, processors/regions, annotator access and prompt rights. Record each decision outside Git where it contains personal or contractual data, and reference it by `decision:<id>`.

- [Validated release boundary and migration](validated-release-boundary.md): compiled-policy API, immutable snapshots, release evidence, historical regression controls and runtime publication obligations.
