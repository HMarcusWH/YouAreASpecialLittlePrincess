> Historical construction handoff, retained as provenance. T26 and its T15 consumer have since been implemented. Current source/status: [interpretation database](../../schema/graphology_interpretation/v1/README.md). Do not alter frozen foundations or treat this record as authorization to activate content.

# Post-merge handoff: construct the actual database

**Current scope: supporting research only. Next scope: T26 database construction in a separate PR after this research import is merged.** No production values, schema enums or task-completion statuses are changed by the import.

## Start from the inspected material

Read [the foundations report](foundations-v0.1/graphology_foundations.md), [source register](foundations-v0.1/sources.json), [catalogue navigation](foundations-v0.1/catalogue_index.md) and [blueprint metadata](foundations-v0.1/blueprint/metadata.json). Run the integrity checker before using the records. The 89 questions and 44 value sets are a research draft, not a completed dictionary of historical graphology or an activated rule pack.

The research's core organization is observation -> within-sample hierarchy -> school-specific combinations -> qualified interpretation. Database-relative rarity runs alongside this process, not in place of it. Ordinary dominant features must remain available as well as outliers.

## Intended construction sequence

1. **Sources and assertions.** Carry source IDs, author/edition, exact location, access depth, claim type, source-fidelity status, empirical status and reproduction restrictions into the database. Curriculum/abstract references do not supply uninspected numerical methods.
2. **Concepts and senses.** Preserve named schools and original terms. Record exact/broader/narrower/related/unmapped relationships; no universal synonym substitution or cross-school score averaging.
3. **Observation definitions.** Add applicable script/task/acquisition context, required glyph/region evidence, method/version and missingness. Keep frequency, degree/intensity, within-sample prominence, certainty and reference rarity separate.
4. **Questions and selectors.** Map every research question to a reviewed production decision. Candidate origin (`FIXED`/`DYNAMIC`) and cardinality (`SINGLE`/`MULTIPLE`) are separate axes. Preserve read-only ownership for user, deterministic and rule-engine results. Record approved exclusions and new additions explicitly.
5. **Traditional associations.** Review premises, alternatives, conjunctions, modifiers, counter-signs and applicability against inspected sources. The two historical examples remain research-only until their gaps are addressed. No source-backed eligible candidate means abstention, not a model-invented meaning.
6. **Output and report mappings.** Complete language keys, bounded soft fields, evidence links, individual/pair/history packs and measured/traditional/visual labels. The same saved report data drives UX, cards and PDF.
7. **Compilation and evaluation.** Add schema/reference/ownership tests, pack compilation, missing/conflicting-evidence cases and a migration report. Promotion into the production scaffold is an explicit reviewed operation, not a file copy.

This is a handoff derived from the supplied research; it does not claim any of these production steps have been completed.

## Outstanding source and rubric work

The draft explicitly leaves original Moretti/Klages/Pulver methods, edition-specific sign definitions, numerical/visual rubrics, licensed exemplars and translations for further research or review. `currency` is a recorded term without a guessed operational definition. Do not invent millimetre bands, decimi ratings, clinical meanings or source quotations to fill gaps.

The documented source-access limitations stay visible: a practitioner exposition citing a founder is not direct inspection of the founder; an institutional abstract is not review of the full paper. An allowed model candidate is not proof that the sample supports it. Image/measurement conflict may suppress a dependent interpretation; it does not authorize the model to rewrite a canonical measurement.

## Completion evidence for the later PR

The T26 PR should identify the merged research commit and hashes, include a traceability map from draft IDs to production IDs or reviewed exclusions, show test results actually executed, state source/rubric gaps and disabled capabilities, and describe migrations/rollback. Preserve this frozen research snapshot for comparison.

This supporting-materials merge is the sequencing gate requested by the owner. It is not approval of every draft interpretation or evidence that personality predictions are validated. Do not change `tasks.json` to DONE until the actual database task and its separate review requirements are satisfied.
