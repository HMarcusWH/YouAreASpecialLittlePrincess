# Graphology interpretation database — v1

This directory is the modular source database for T26. It is grounded in the immutable research snapshot at `research/graphology/foundations-v0.1/`, pinned to research import commit `f96aa6b54cfaf91f0a8243e7c7e266baa053eedc`.

## Current state

- Database: **REVIEWED_READY_FOR_T15**
- T26: **DONE**
- Runtime activation: **false**
- Handoff: **T15 is the downstream consumer; execute T00 → T01 → T05 → T09 prerequisites first**
- Traditional runtime-eligible associations: **0**

A populated database is not an activated inference system.

## Layers

1. `ontology/`: sources, schools, domains, concepts, observations, feature mappings and evidence policies.
2. `values/`: fixed value sets, answer-state policy and independent selection axes.
3. `candidates/`: candidate kinds, eligibility policy, envelope, generator contracts and selector→generator mappings.
4. `traditional/`: source-backed method structure and blocked historical association stubs.
5. `questions/`, `packs/`, `narrative/`, `reports/`, `localization/`: product question/report contracts.
6. `schema/premium_interpretation_database_v1.json`: deterministic compiled artifact consumed by T15.

## Core invariants

- Canonical measurements remain authoritative for measurable quantities.
- Feature mappings are support relationships, never silent graphology equivalence.
- Observation frequency, intensity, prominence, confidence and population rarity remain separate.
- Fixed/dynamic candidate origin and single/multiple cardinality are independent axes.
- Candidate kinds may have interface contracts while their generators remain explicitly unimplemented.
- Traditional graphology stays school/source-labelled and inactive unless explicitly promoted through its gates.
- The original handwriting text is untrusted data, not model instructions.

## Validation

```bash
python tools/validate_graphology_integrity.py
python tools/validate_graphology_ontology.py
python tools/validate_graphology_selector_foundation.py
python tools/validate_graphology_traditional_rules.py
python tools/validate_graphology_database.py
python tools/compile_premium_interpretation_db.py --check
pytest -q
```

The validators first verify the frozen research bytes against `traceability/research_baseline_lock.json` and the import manifest SHA-256 records, then validate research→production promotion, lifecycle state, mappings, candidate contracts and the compiled artifact.
