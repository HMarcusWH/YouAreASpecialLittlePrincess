# 08 — Premium selector, question and soft-value database

Status: architecture and population contract. **The actual pick-value catalogue is intentionally not populated by this roadmap update.** The next product-data pass will enumerate, research, review and populate every selector/question/soft field.

## 1. Purpose

Premium should not be an open-ended "look at this handwriting and write a personality reading" call. The model receives:

1. the authorized original handwriting image;
2. canonical deterministic measurements and evidence;
3. database-relative statistics and verified outliers;
4. fixed and dynamically generated selector candidates;
5. a versioned battery of prepared questions; and
6. bounded free-text fields for qualitative synthesis.

The model returns only values allowed by the output schema plus bounded text linked to supplied evidence.

The deterministic engine owns measurable truth. The reference engine owns percentiles/rarity. The interpretation database owns which semantic labels may be chosen. OpenAI chooses among approved candidates and writes the soft explanation.

```text
                 ORIGINAL IMAGE
                       +
            CANONICAL MEASUREMENTS
                       +
             REFERENCE STATISTICS
                       +
              VERIFIED OUTLIERS
                       +
       SELECTOR / QUESTION DATABASE
                       |
                       v
             PREMIUM REQUEST PACKET
                       |
              OPENAI RESPONSES
             strict structured output
                       |
          +------------+-------------+
          |            |             |
      selectors    soft values   evidence links
          |            |             |
          +------------+-------------+
                       |
                PREMIUM OVERLAY
```

## 2. Database families

Keep these versioned separately even if they initially live in one JSON source and one PostgreSQL content schema.

### selector_definition

Defines one constrained semantic choice.

Fields:

- `selector_id`
- `version`
- `label_key`
- `description`
- `category`
- `scope`: individual / pair / history
- `selection_mode`: FIXED_ENUM / DYNAMIC_FACT / DYNAMIC_OUTLIER / DYNAMIC_CANDIDATE / MULTI_SELECT
- `allowed_value_set_id` for fixed choices
- `dynamic_source_kind` for generated choices
- `min_selections`, `max_selections`
- `allow_unknown`, `allow_insufficient_evidence`
- `required_fact_classes`
- `minimum_quality_policy`
- `evidence_class`
- `report_targets`
- `status`
- provenance/editorial-review fields.

A selector does not itself contain a prompt sentence. It defines the semantic variable and legal result space.

### selector_value_set and selector_value

Defines every predetermined pick value. Machine IDs are stable; localized display text is separate. Removing or changing the semantics of a value creates a new version; do not silently recycle an ID.

### question_definition

One prepared question the model must answer.

Fields:

- `question_id`
- `question_pack_version`
- `prompt_template_key`
- `purpose`
- `scope`
- `answer_mode`: SELECTOR / MULTI_SELECTOR / SOFT_TEXT / SELECTOR_PLUS_TEXT
- `selector_id` where applicable
- `soft_field_id` where applicable
- `required_fact_classes`
- `required_candidate_kinds`
- `minimum_supporting_fact_count`
- `minimum_supporting_association_count`
- `fallback_value_id`
- `report_target`
- `priority/order`
- `enabled`.

Questions are authored application data. The model never invents which questions it should answer.

### soft_field_definition

Defines bounded qualitative text.

Fields:

- `soft_field_id`
- `label_key`
- `purpose`
- `scope`
- `max_characters`
- `max_sentences`
- `allowed_fact_classes`
- `required_support_count`
- `allow_traditional_associations`
- `allow_visual_observation`
- `allow_new_numbers` (normally false)
- `tone_profile_id`
- `prohibited_claim_classes`
- `report_target`
- `status`.

Soft values are where Premium earns its keep: synthesis, nuance, explanation and readable prose. They are not an escape hatch from the selector/evidence contracts.

### candidate_definition

Describes deterministic candidate objects constructed per report. Candidate families to populate include verified outliers, feature-family standouts, consistency/variability signals, dualities/tensions, pair similarities/differences, unusual combinations, visually supported regions, and approved traditional-association bundles.

### question_pack

A frozen ordered battery such as `PREMIUM_INDIVIDUAL_V1` or `PREMIUM_PAIR_V1`.

A pack records exact question versions, output schema version, applicable report kind and locale-independent order. Adding/removing/rewording a question creates a new pack version so old reports stay reproducible.

## 3. Hard evidence packet

The application computes this before OpenAI: canonical facts, reference statistics, verified outliers, and report-specific candidates.

Each fact has a stable `fact_id`, evidence class, canonical feature ID where applicable, value/unit, quality/missingness, method version and optional source-region references.

The statistics service—not OpenAI—determines cohort eligibility, feature-specific eligible writer count, percentile/rank, direction/tail, uncertainty/display eligibility, outlier eligibility, and multiplicity-aware headline candidates.

For a report with candidate IDs O1/O2/O3, the generated output schema can restrict `defining_outlier_id` to exactly those IDs plus an approved fallback. Apply the same pattern to dualities, pair differences and association bundles.

## 4. Original image as Premium-v1 evidence

The authorized original or privacy-preserving analysis derivative is a first-class Premium-v1 input.

Use it for holistic visual style, whole-page cohesion/rhythm, visual prominence, ornamentation/style observations, choosing which verified hard signal is most visually salient, and bounded qualitative observations not yet represented by a canonical metric.

It is **not** authoritative for a measurable quantity already produced by the deterministic engine.

Precedence:

1. canonical deterministic measurements;
2. eligible reference statistics;
3. deterministic candidate generation;
4. reviewed traditional associations;
5. image-based visual observation;
6. model synthesis.

If image perception conflicts with a canonical numerical feature, the hard feature wins and the model may note ambiguity rather than overwrite it.

Visible handwriting text is untrusted data. System instructions explicitly state that text in the image is never an instruction, even if it says to ignore prior instructions. Do not feed OCR transcripts merely to help the model follow content.

Image detail/resolution is an evaluated cost/quality setting. Sending the original asset does not mean sending unbounded native resolution when a reviewed analysis derivative is sufficient.

## 5. Output schema

PremiumAnalysis separates:

- `selectors`: approved fixed values or current-call dynamic candidate IDs;
- `traditional_selectors`: only reviewed traditional-rule values;
- `soft_values`: bounded evidence-linked prose;
- `support`: fact/candidate/association/visual-observation IDs;
- `visual_observations`: image-only soft observations, never canonical measurements.

By default soft text may not introduce new numerical values. The report renderer inserts canonical numbers from facts.

## 6. Question battery design

The population pass should enumerate questions in at least these families:

### A. Visual style
Dominant visual style, cohesion, rhythm, conventionality/individuality, ornamentation, and first visual standout.

### B. Evidence interpretation
Defining verified outlier, most meaningful set of outliers, subtle-versus-obvious unusual feature, strongest consistency/variability signal, notable spatial/stroke feature, and best supported candidate duality.

### C. Traditional graphology
Only reviewed association bundles and reserved traditional dimensions, with unknown/mixed/insufficient-evidence states.

### D. Pair comparison
Strongest similarity/difference, most meaningful contrast, shared pattern and optional reviewed pair narrative. No relationship-success probability.

### E. Historical / Me-v-Me
Largest comparable change, most stable characteristic and visually obvious change, preserving capture/method caveats.

The full list, exact wording and every allowed value are intentionally deferred to the next task.

## 7. Validation rules

Application validation rejects selector IDs/values absent from the pack, dynamic candidate IDs not supplied in that request, evidence IDs from another report, soft fields exceeding bounds, new percentages/probabilities/scores written by the model, unsupported traditional associations, prohibited consequential/diagnostic claims, raw HTML/URLs, output that treats visible writing text as instructions, and visual observations returned as canonical measurements.

Structured Outputs constrains shape/enums but does not establish semantic truth. Evals and post-validation remain required.

## 8. Version manifest

Every Premium overlay pins at least:

- feature schema;
- engine/method manifest;
- benchmark release;
- selector database version;
- question pack version;
- soft-field database version;
- traditional rule-pack version;
- Premium output schema version;
- prompt version;
- requested/returned model IDs;
- image-input policy version; and
- locale.

This gives us a complete answer to "why did this report say that?"

## 9. Next step: populate the database

`schema/premium_interpretation_database_v1.json` is intentionally an empty scaffold.

The next phase is a dedicated database-design exercise:

1. enumerate every selector;
2. enumerate every allowed pick value;
3. define unknown/mixed/insufficient-evidence behavior;
4. enumerate the complete question battery;
5. define every soft-text field and character/evidence bounds;
6. map selectors/questions to report locations;
7. map relevant questions to canonical features/candidate generators;
8. map traditional questions only to reviewed graphology associations;
9. design individual, pair and history packs;
10. add localization keys and editorial descriptions;
11. validate there are no orphan/duplicate/contradictory values; and
12. freeze `premium-interpretation-db/1` for implementation and eval fixtures.

Only after that database is populated should T15 compile final dynamic Structured Output schemas and prompts.
