# Evidence-support repair candidate — synthetic research only

**Origin:** Controlled local output audit, 20 October 2026. Uploading these source
repairs to a review branch does not activate them or certify handwriting accuracy.

## Reproduced issues

- Original `legacy` on synthetic blank ruled paper detected 11 printed lines and
  generated plausible handwriting highlights; blank synthetic graph paper produced
  a false full-page line.
- Heavily downscaled synthetic photos lost much of their line/word-group evidence
  but still produced specific quantitative interpretations.
- The Free `SAMPLE_SUITABILITY` section relied on image dimensions even when no
  handwriting-dependent observations were available.
- “Detected words/components” overstates the geometric detector's semantics.

## Included safeguards and ownership

- Deterministic `evidence-support/1` is **disabled by default** in `GraphologyEngine`.
  Research use requires `PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN=1` in private
  `PRINCESS_ENV=local|test` and a matching, explicitly pinned
  `PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256` for API and analysis-worker startup.
  Public guest, staging and production opt-ins are refused even when the flag is
  present. The job's already-stored processing digest must match the worker.
- If the narrow structural guard abstains, 60 handwriting-dependent canonical
  measurements are `MISSING` (not zero), false LINE/WORD/COMPONENT regions are
  omitted, and versioned evidence contains no observations. Four exact image facts
  remain. Existing unguarded measurements, digests and report defaults remain
  unchanged.
- Guarded jobs alone write `individual-report/3` for new sample-suitability
  behavior. Historical `/1` and `/2` assemblies and revision rules remain
  unchanged. Default report **writer** stays `/2`; `/3` is a private research
  opt-in reader/writer only.
- **Editorial exception for label copy:** the report presentation v1 *label* for
  PAGE_WORD_COUNT changes to “Detected geometric word groups” / “Upptäckta
  geometriska ordgrupper” across source, Python, product JSON and TypeScript.
  This clarification intentionally affects display copy for previously saved
  reports; immutable numerical facts, report digests, versions and stored
  `ReportDocument` payloads do not change. Human owner approval is required
  before merging this backwards-visible editorial change. If that is not
  approved, revert the four label changes and make a versioned presentation
  registry/client selection in a separate PR; do not silently substitute labels.

## Verification boundaries

The initial synthetic test evidence showed 25 valid actual Free reports from 30
image/profile scenarios (five conservative quality refusals), no numerical drift
in 20 unaffected accepted cases, and corrections to the five weak cases. Python
3.13 local probe results are not accepted as supported CI; check locked Python
3.10/3.11/3.12 exact-head workflows and app/web/native/contract checks in PR.

No human handwriting/consent evidence is published. No Premium model call or
personality, diagnosis, writer identity, deception or pressure inference is
introduced. Keep legacy production and public `qualified-v2` activation OFF.
T11 participant rights and [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92) remain independent.

## Remaining release gates

1. Independent implementation/security review of the opt-in, output missingness,
   immutable template `/3` and render/export/projection parity.
2. Owner decision about changing the existing presentation/1 display label.
3. Approved real-photo evaluation of rejection rates before broadening the
   synthetic-only guard; no claims of accuracy from font-derived images.
4. Controlled rollout and rollback; `PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN`
   remains unset/`0` outside explicitly authorized local/test infrastructure.

## Follow-up repair batch (merge checks remain mandatory)

The current PR repair batch additionally covers:

- Combined Railway private test-stack forwarding for the independently pinned evidence-support flag, with public-guest rejection on both roles.
- Retention of only safe profile/policy provenance on withheld measurements; all measured-dependent metadata and confidence remain suppressed.
- Visible SAMPLE_SUITABILITY/INELIGIBLE explanation in web/native and export, and a neutral, image-only share-card fallback when no handwriting facts are supported.
- Unit, PostgreSQL worker/persistence, projection/revision and EN/SV renderer regression coverage, including synthetic false-abstention boundaries.
- The guarded analysis digest derives from the source policy version, so a future policy bump changes its processing identity without perturbing guard-off legacy hashes.

These changes do **not** imply that the owner has approved the presentation/1 retroactive copy change, that an independent security review completed, or that real-handwriting accuracy was calibrated. Inspect exact-final-head CI and render artifacts before determining merge readiness. Guard activation remains private local/test only; T11 and Issue #92 remain separate production/public gates.

## Genuine /3 render inspection qualification (PR #96 follow-up)

The Application environments `live-web` job now generates an actual
`GraphologyEngine(evidence_guard_enabled=True)` synthetic ruled-paper result,
assembles immutable `individual-report/3`, projects it through the production
Python `project_report` path, and renders EN/SV A4, Letter, square and story
outputs through the same bundled offline Chromium renderer. Its upload artifact
is `t06-guarded-v3-inspection-<commit>`. The included manifest binds source
report digest, analysis config, artifact hashes and dimensions. The synthetic
case must preserve 64 facts, four exact image values, 60 missing handwriting
values and `INELIGIBLE` sample status. No handwriting photo or personal data is
used. Visual inspection of actual PDF pages and cards is still a **human review
step** and must not be inferred from upload success.

## Post-review UX and eligibility corrections (2026-10-20)

The P1 findings from the assistant-led visual review were addressed on this
research-only PR branch. For v3 reports with `section.sample=INELIGIBLE`:

- The stored measured-notice localization key changes to `notice.image_only`,
  making no assertion that the four available image facts are handwriting.
- Premium is `INELIGIBLE`, not `LOCKED`; an enabled caller-supplied PURCHASE
  action is omitted by server projections; direct `CommerceService.request_premium`
  rejects before consuming/reserving any credit; attaching a Premium overlay
  in a revision or initial assembly is rejected.
- English and Swedish section headings use a reviewed shared localization map
  with section-specific names for size/ink families. Existing /1 and /2 facts,
  saved notice keys, templates, and numerical data remain unchanged. This is a
  presentation-copy improvement when older reports are reopened.
- Fully missing measurement families collapse into honest, counted summaries.
  Their underlying canonical facts remain in the persisted report and all
  authorized projections. Web details and native toggles expose the full rows
  interactively; print PDF omits repetitive detail rows while explaining their
  unavailability. No facts become fabricated zeroes.
- The research guarded v3 render-inspection harness checks EN/SV explanatory
  notices, correct localized headings, payment unavailability, compacted
  families, and A4/Letter PDF length, plus all four share-card outputs.

These are premerge changes to the unreleased `/3` research template. They are
not a production release, not consent for retroactively changing the separate
`presentation/1` PAGE_WORD_COUNT label, not real-handwriting calibration,
and not an independent external code/security signoff. T11 and #92 remain open.

The rejected-sample suitability section additionally keeps four exact image
facts visible and groups its six missing sample descriptors behind the same
expandable web/native details. The printed version keeps the image facts and
one missing-values summary, reducing the synthetic PDF without dropping any
stored facts.
