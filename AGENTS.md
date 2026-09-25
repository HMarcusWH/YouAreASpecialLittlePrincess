# Coding-agent instructions

This repository contains a deterministic handwriting measurement library. Read `ROADMAP.md` and the relevant documents in `docs/roadmap/` before implementing product features.

## Non-negotiable boundaries

- Free runtime is literally zero AI: no learned model weights, neural OCR, local classifiers, embeddings, or provider calls. Development tools may use AI. Method-level capabilities and transitive dependencies enforce this; `free_compute` alone does not.
- Preserve the canonical feature IDs, units, definitions, coordinate frames, missingness and provenance. Do not rename unrelated numbers into schema compliance. A semantic change requires a versioned migration and tests.
- Existing `AnalysisResult.measurements` is one aggregate per feature ID. Regional observations belong to an explicit additional contract, not a silent dictionary-key change.
- Measured geometry, statistical reference claims, and traditional/playful interpretation are different evidence classes. Do not infer diagnosis, intelligence, criminality, deception, employment suitability, or relationship outcomes.
- No invented confidence, percentile, rarity, writer count, legal clearance, test result, or provider compatibility. Unknown is not zero. Synthetic fixtures are labelled synthetic and excluded from reference statistics.
- The interactive report, social cards, and PDF use one immutable report snapshot and the same numerical facts. UI expansion, reopening, sharing and exporting never call a model.
- No raw handwriting, private crops, transcripts, credentials, production database dumps, or user-specific vectors in Git, CI logs, analytics, or public fixtures.
- Upload consent, reference-corpus contribution, retention, third-party AI processing, and public sharing are distinct decisions. Corpus publishing and deletion are privileged workflows.
- A timeout does not prove a provider call was never executed. Make application publication and billing idempotent; do not promise exactly-once external execution.

## Workflow

Choose one ready task in `docs/roadmap/tasks.json`. Respect its dependencies and human gates. Keep PRs bounded; avoid concurrent edits to schema/model contracts without coordination. Never merge or change branch protection merely to bypass a failing check.

Existing core checks, from the repository README:

```bash
python tools/generate_feature_contract.py --check
ruff check src tests tools
python -m compileall -q src
pytest -q
```

New product tests described in the roadmap do not exist until their tasks add them. Do not report a planned command as executed. Record interpreter/dependency versions and actual results in the PR. Pin dependencies and generate a reviewable lock/update process in T00/T01.

Before completion, check authorization and tenant boundaries, missing/partial results, zero denominators, method/version mismatch, export parity, retry/duplicate behavior, consent withdrawal, and rollback. Add negative tests, not just a happy-path screenshot.

Owner gates include corpus recruitment/rights, source-rule review, API account/region/spend, production payments, and public release. Implement mocks and disabled capabilities while those gates remain open; never fabricate their approval.

## Graphology research and T26 sequencing

Before question/selector or traditional-rule work, read [the research index](research/graphology/README.md) and [database handoff](research/graphology/DATABASE_HANDOFF.md).

The `research/graphology/foundations-v0.1/` snapshot is supporting material, not an active rule pack. The owner requires this supporting-materials PR to be merged before T26 database construction starts in a separate PR. Do not mark T26 complete or populate the production scaffold as part of the research import.

Preserve source access limits and draft IDs. Source fidelity, empirical support, observation feasibility, within-sample importance and reference rarity remain separate. Any correction or production promotion needs explicit provenance and review rather than a silent edit to the frozen snapshot.

Run `python tools/check_graphology_research.py` and `python tools/test_graphology_research.py` for this supporting-materials import. They are offline integrity/structure tests, not model or personality-validity tests.
