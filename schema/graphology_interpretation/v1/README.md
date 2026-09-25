# Graphology interpretation database — v1 foundation

This directory is the production **ontology/provenance foundation** for T26. It is derived from the frozen research snapshot at `research/graphology/foundations-v0.1/` merged in commit `f96aa6b54cfaf91f0a8243e7c7e266baa053eedc`.

## Scope of this PR

Included:
- registered source metadata and access/reuse boundaries;
- five graphology tradition profiles plus the non-historical APPLICATION namespace;
- the 16 examination domains;
- source-backed school concepts;
- source claims/method constraints;
- one explicit safe concept non-equivalence already stated by the research;
- source/method gaps;
- complete research-to-production traceability for the records promoted in this slice.

Not included:
- observations or feature mappings;
- selector/value/question population;
- executable traditional associations;
- prompt packs, soft-text activation, report mappings or localization;
- any generated runtime interpretation artifact.

The existing `schema/premium_interpretation_database_v1.json` must remain `UNPOPULATED` after this PR. Nothing here authorizes model output or traditional interpretation.

## Files

- `manifest.json` — scope/version/count contract.
- `ontology/sources.json` — preserved source records with production provenance status.
- `ontology/schools.json` — tradition/application namespaces.
- `ontology/domains.json` — examination-domain registry.
- `ontology/source_claims.json` — source assertions, including research-only historical examples.
- `ontology/concepts.json` — named school/descriptive concepts; all ontology-only.
- `ontology/concept_relationships.json` — explicitly reviewed concept relations only.
- `traceability/research_to_production.json` — disposition for every promoted foundation record.
- `traceability/exclusions.json` — explicit scope exclusions for this PR.
- `traceability/source_gaps.json` — unresolved definitions/methods/reuse review.

## Validation

Run:

```bash
python tools/validate_graphology_ontology.py
pytest -q tests/test_graphology_ontology.py
```

The validator checks cross-references, counts, traceability coverage, source-gap coverage, non-executable historical claims, and that the compiled Premium scaffold is still unpopulated.
