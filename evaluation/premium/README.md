# Premium output adversarial cases (T15)

`adversarial_cases.json` holds synthetic mutations of one valid Premium output
for the synthetic fixture report in `fixtures/reports/`. Each case applies a
JSON-pointer patch to the baseline and names the issue codes the validator
must raise. `tests/test_premium.py` runs every case; a case with an empty
`expect` must validate.

These cases prove the **programmatic** guardrails only: contract shape,
frozen IDs, cardinality, support confinement, text bounds, numerals, links and
a keyword screen for prohibited inference classes. They are not a model
evaluation. Semantic quality, writer-disjoint scenario coverage, Swedish and
English human review and the launch rubric belong to T16 and require the
`api_access_spend_before_live_calls` gate before any live provider call.

No case contains real handwriting, transcriptions, prompts sent to a provider
or provider responses.

## Deterministic dynamic-candidate support

T15 treats every dynamic generator used by `PREMIUM_INDIVIDUAL_GRAPHIC_V1`
as either explicitly supported or explicitly unavailable. The registry is
application-owned; it does not edit or activate the frozen T26 database.

| Generator | State | Deterministic basis / reason |
|---|---|---|
| `GEN_LINE_EDGE_TREND_V1` | supported | `LINE_START_DRIFT`, `LINE_END_DRIFT`; candidates name the supplied trend facts, not threshold buckets |
| `GEN_INK_APPEARANCE_FACT_V1` | supported | requires `INK_DARKNESS_CV`; `INK_DARKNESS_MEAN` may accompany it as context; image proxy only |
| `GEN_THICKNESS_FACT_V1` | supported | requires `STROKE_WIDTH_MEAN`; `STROKE_WIDTH_CV` may accompany it as context; image proxy only |
| `GEN_MEASUREMENT_CONFLICT_CANDIDATE_V1` | unavailable | no deterministic image-vs-measurement conflict detector |
| `GEN_MARGIN_DESCRIPTION_V1` | unavailable | current canvas/text bounds are not verified physical page boundaries |
| `GEN_ORNAMENT_DESCRIPTION_V1` | unavailable | glyph-level flourish feature is not implemented in the current 64-feature runtime |
| `GEN_REPEATED_FORM_DESCRIPTION_V1` | unavailable | no repeated-form detector |
| `GEN_COPYBOOK_DIFFERENCE_V1` | unavailable | no approved copybook context |
| `GEN_INITIAL_STROKE_DESCRIPTION_V1` | unavailable | no reliable glyph-level initial-stroke implementation |
| `GEN_TERMINAL_STROKE_DESCRIPTION_V1` | unavailable | no reliable glyph-level terminal-stroke implementation |
| `GEN_PPI_FORM_DESCRIPTION_V1` | unavailable | no English PPI example/context pipeline |
| `GEN_SIGNATURE_TEXT_DIFFERENCE_V1` | unavailable | no authorized signature/body-region product workflow |
| `GEN_SIGNATURE_TEXT_PATTERN_V1` | unavailable | no authorized signature/body-region product workflow |
| `GEN_GRAPHIC_SIGN_V1` | unavailable | no deterministic graphic-sign detector |
| `GEN_SUPPORT_GROUP_V1` | unavailable | traditional runtime content remains inactive |
| `GEN_COUNTEREVIDENCE_GROUP_V1` | unavailable | traditional runtime content remains inactive |
| `GEN_LOCAL_ONLY_SIGN_V1` | unavailable | no deterministic graphic-sign detector |
| `GEN_GRAPHIC_COMBINATION_V1` | unavailable | no deterministic graphic-sign detector |

The three supported producers expose neutral candidates backed by present
`READY`/`UNCALIBRATED` report facts. They do not manufacture categories such
as “light/medium/dark” or “thin/normal/thick”: T26 requires a documented,
versioned rubric before numerical thresholds may create such classifications.
Zero is a valid fact value and does not become missing.

The individual pack still requires an authorized image at the **pack** level.
Fact-backed dynamic questions therefore cannot accidentally turn Premium into a
text-only/model call when the image grant or retained image is unavailable.
Candidate kind and support IDs are checked against T26 and the exact report
before packet publication.

