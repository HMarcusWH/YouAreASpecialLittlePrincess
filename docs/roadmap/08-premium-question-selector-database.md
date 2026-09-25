# 08 - Premium selector, question and soft-value database

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

The statistics service-not OpenAI-determines cohort eligibility, feature-specific eligible writer count, percentile/rank, direction/tail, uncertainty/display eligibility, outlier eligibility, and multiplicity-aware headline candidates.

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

The full list, exact wording and every allowed value v’–çFVçF–öæÆÇ’FVfW'&VBFòF†RæW‡BF6²à ¢22râfÆ–FF–öâ'VÆW0 ¤Æ–6F–öâfÆ–FF–öâ&V¦V7G26VÆV7F÷"”G2÷fÇVW2'6VçBg&öÒF†R6²ÂG–æÖ–26æF–FFR”G2æ÷B7WÆ–VB–âF†B&WVW7BÂWf–FVæ6R”G2g&öÒæ÷F†W"&W÷'BÂ6ögBf–VÆG2W†6VVF–ær&÷VæG2ÂæWrW&6VçFvW2÷&ö&&–Æ—F–W2÷66÷&W2w&—GFVâ'’F†RÖöFVÂÂVç7W÷'FVBG&F—F–öæÂ76ö6–F–öç2Â&ö†–&—FVB6öç6WVVçF–ÂöF–væ÷7F–26Æ–×2Â&r…DÔÂõU$Ç2Â÷WGWBF†BG&VG2f—6–&ÆRw&—F–ærFW‡B2–ç7G'V7F–öç2ÂæBf—7VÂö'6W'fF–öç2&WGW&æVB26æöæ–6ÂÖV7W&VÖVçG2à ¥7G'V7GW&VB÷WGWG26öç7G&–ç26†RöVçV×2'WBFöW2æ÷BW7F&Æ—6‚6VÖçF–2G'WF‚âWfÇ2æB÷7B×fÆ–FF–öâ&VÖ–â&WV—&VBà ¢22‚âfW'6–öâÖæ–fW7@ ¤WfW'’&VÖ—VÒ÷fW&Æ’–ç2BÆV7C  ¢ÒfVGW&R66†VÖ°¢ÒVæv–æRöÖWF†öBÖæ–fW7C°¢Ò&Væ6†Ö&²&VÆV6S°¢Ò6VÆV7F÷"FF&6RfW'6–öã°¢ÒVW7F–öâ6²fW'6–öã°¢Ò6ögBÖf–VÆBFF&6RfW'6–öã°¢ÒG&F—F–öæÂ'VÆR×6²fW'6–öã°¢Ò&VÖ—VÒ÷WGWB66†VÖfW'6–öã°¢Ò&ö×BfW'6–öã°¢Ò&WVW7FVB÷&WGW&æVBÖöFVÂ”G3°¢Ò–ÖvRÖ–çWBöÆ–7’fW'6–öã²æ@¢ÒÆö6ÆRà ¥F†—2v—fW2W26ö×ÆWFRç7vW"Fò'v‡’F–BF†—2&W÷'B6’F†Cò  ¢22’âæW‡B7FW¢÷VÆFRF†RFF&6P ¦66†VÖ÷&VÖ—VÕö–çFW'&WFF–öåöFF&6U÷cæ§6öæ—2–çFVçF–öæÆÇ’âV×G’66fföÆBà ¥F†RæW‡B†6R—2FVF–6FVBFF&6RÖFW6–vâW†W&6—6S  £âVçVÖW&FRWfW'’6VÆV7F÷#°£"âVçVÖW&FRWfW'’ÆÆ÷vVB–6²fÇVS°£2âFVf–æRVæ¶æ÷vâöÖ—†VBö–ç7Vff–6–VçBÖWf–FVæ6R&V†f–÷#°£BâVçVÖW&FRF†R6ö×ÆWFRVW7F–öâ&GFW'“°£RâFVf–æRWfW'’6ögB×FW‡Bf–VÆBæB6†&7FW"öWf–FVæ6R&÷VæG3°£bâÖ6VÆV7F÷'2÷VW7F–öç2Fò&W÷'BÆö6F–öç3°£râÖ&VÆWfçBVW7F–öç2Fò6æöæ–6ÂfVGW&W2ö6æF–FFRvVæW&F÷'3°£‚âÖG&F—F–öæÂVW7F–öç2öæÇ’Fò&Wf–WvVBw&†öÆöw’76ö6–F–öç3°£’âFW6–vâ–æF—f–GVÂÂ—"æB†—7F÷'’6·3°£âFBÆö6Æ—¦F–öâ¶W—2æBVF—F÷&–ÂFW67&—F–öç3°£âfÆ–FFRF†W&R&Ræò÷'†âöGWÆ–6FRö6öçG&F–7F÷'’fÇVW3²æ@£"âg&VW¦R&VÖ—VÒÖ–çFW'&WFF–öâÖF"óf÷"–×ÆVÖVçFF–öâæBWfÂf—‡GW&W2à ¤öæÇ’gFW"F†BFF&6R—2÷VÆFVB6†÷VÆBCR6ö×–ÆRf–æÂG–æÖ–27G'V7GW&VB÷WGWB66†VÖ2æB&ö×G2à 