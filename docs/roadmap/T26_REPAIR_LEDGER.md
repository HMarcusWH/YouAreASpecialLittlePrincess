# T26 Codex repair ledger

This repair round addresses every unresolved Codex review finding from PRs #4, #5 and #7 while keeping the database runtime-inactive and T26 pending review.

## PR #4
- Cross-school IHAS thread / Moretti Filiforme relation downgraded from `NOT_EQUIVALENT` to `UNMAPPED`.
- Research comparison pinned to the immutable import manifest and per-file SHA-256 hashes.
- Foundation trace production endpoints resolve to real typed objects.
- Stage contract validates manifest/T26/artifact states and exclusions.
- All ontology record families are checked for inactive/provenance-only status.
- Source-gap IDs/references/reuse-clearance coverage are validated.

## PR #5
- Observation membership now follows evidence semantics, not fixed/dynamic selector origin.
- Frozen observation envelope promoted losslessly.
- Candidate eligibility policy promoted as the canonical candidate policy.
- Research baseline restored to `f96aa6b…`; later merge commits live in construction lineage.
- Every selector/observation/mapping preserves the research operational guardrail.
- Soft fields are promoted and traced by the completed database.
- README updated to current architecture.
- Feature mappings have independent data-flow roles; spacing CV cannot drive spacing magnitude.

## PR #7
- Old staged tests are completion-aware but still require runtime inactivity.
- `ANSWER_STATE_V1` is compiled into the self-contained artifact.
- Runtime selection contract uses independent `selection_domain` and `cardinality` axes.
- All soft-field prompt keys receive English localization entries.
- All 50 canonical feature mappings are compiled.
- All 33 candidate kinds have stable generator contracts and all 35 dynamic selectors map to them; implementations remain explicitly deferred.
- Source and source-claim registries are compiled so provenance references close inside the artifact.

No new graphological interpretation claims or runtime activation are introduced by this repair.
