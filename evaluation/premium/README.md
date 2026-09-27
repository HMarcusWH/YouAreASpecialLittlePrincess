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
