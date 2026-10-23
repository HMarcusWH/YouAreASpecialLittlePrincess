# T06 residual ruling qualification — synthetic research only

**Source:** Main baseline `0c9470b0a0fdcb6ba3c45f17c6a1b94789e63b50` (merged PR #96). This is a research candidate for open [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92), **not** field-validated handwriting recognition or production release authorization.

## Implementation and provenance

- `evidence-support/5` is a versioned update to the existing opt-in guarded analysis. The flag `PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN=1` remains permitted **only** in explicitly paired and digest-pinned private local/test API + analysis-worker processes. Public guest, staging and production still reject it. Default guard-off processing hashes, outputs and the historical report writer are unchanged.
- A bounded independent retained-foreground audit counts (a) wide horizontal ink rows, (b) near-horizontal long Hough segments, and (c) page-width line boxes versus compact component support. It does not crop pages or alter pen/ruling pixels. The prior page-spanning, dominant-thin and low-resolution checks remain in front of the new checks to retain prior refusal reasons.
- Multiple suspect foreground bands cause **full conservative abstention even when a word detector admitted some groups**. Zero accepted word groups and zero accepted text lines are treated as unavailable evidence, not as proof a page contains no handwriting.
- The private `evidence_support_audit` records only versioned statuses, bounded counts and fixed reasons; it has no pixel arrays, boxes, source image paths, transcriptions, participant IDs, or raw detector payloads. Missing stages are JSON null, not fabricated zero.
- If abstaining, all 64 canonical features remain, with the four exact input-image facts still present and 60 unsupported handwriting-dependent facts `MISSING` with explicit reasons/null values. Suppress unsupported LINE/WORD/COMPONENT and baseline evidence; the existing `individual-report/3` projection and honest Premium eligibility behavior apply.
- The separately versioned guard digest keeps prior guarded v1/v2/v3/v4 jobs distinct from active v5 evaluation. Explicit version changes require API/worker startup pin updates; an unmodified default remains legacy.

## Synthetic regressions

`tests/residual_ruling_cases.py` synthesizes grey/blue/dark paper ruling, page/table backgrounds, perspective, near-edge strokes, and ground-truth masks/page polygon/word-group boxes. These are OpenCV-generated shapes, not human handwriting or benchmark ground truth for people.

Run the focused suite:

```sh
python -m pytest -q tests/test_residual_ruling_guard_v2.py tests/test_evidence_support_guard.py tests/test_qualified_segmentation_v2.py
python -m pytest -q
ruff check src tests tools
python tools/documentation.py --check
```

Checks cover deliberately fooled accepted-word candidates with retained ruling, angle tolerance, bounded stage diagnostics, no false factual zero, full evidence withholding, and an explicit *positive* accepted synthetic handwritten-like case. A pipeline quality refusal remains a refusal and never silently drops from accuracy denominators.

## Gates that are NOT closed

- T06 remains **PLANNED** and T11 pilot consent/rights authorization remains **IN_PROGRESS/PENDING**. No human photo is uploaded to CI or published.
- Do **not** close Issue #92 based on synthetic results. Exact authorized original-photo reproduction with SHA and coordinate lineage, protected annotated writer-disjoint development/validation/holdout, independent agreement analysis, preregistered nonempty/empty acceptance thresholds, comparison against legacy/grid-v1/qualified-v2, resource budgets and real physical Android handset proof are still required.
- The synthetic evaluator's own `ENGINEERING_PASS` or this guard's no-abstention status is not a scientific accuracy certificate, permission to process a real source, or a hardware attestation.
- Rollback is to keep the research opt-in disabled. Existing saved report/feature identities and offline exports are never rewritten.

**Review disposition:** Do not merge before exact-head Python 3.10–3.12, app/backend/native/release/docs/roadmap CI, independent correctness/security review, and synthetic evidence inspection. Merging does not turn this on publicly.


## Review repair pass: four correctness findings

The one-stroke Hough false-positive review showed that midpoint-only grouping
could claim two separate ruling bands from duplicate fragments of one thick
pen stroke. The historical v2 repair grouped fragments using slope and reference-x position.
The current v4 implementation uses 17-column foreground-ribbon continuity,
whole-group compatibility and an explicit insufficient-support state when
contradictory Hough directions cannot justify a unique physical-band count.
This is only a deterministic visual proxy, not a printed-vs-handwritten
classifier.

There are now two explicit foreground scopes for the guarded qualified-v2
profile. `pre_line_ruling_audit` contains bounded row/Hough counts on the
**post-grid, pre-qualified-lines** retained mask. Its counterpart in the
guard audit has `foreground_stage=qualified_line_selected` and describes
only the *post-selection* mask. A high preselection ruling count by itself
does not force abstention when the qualified line filter has excluded the
paper artifact: otherwise every legitimate ruled-writing input could be
rejected. These counters contain no pixels, mask crops or region locations.
Other profiles report `foreground_stage=denoised_foreground`.

Word proposal diagnostics and final canonical reattachment are separate:
`word_stages.counts` describes the original detector/qualification path;
`word_stages.reattachment.counts` describes only the subsequent
`attach_words` pass. An uninvoked stage returns JSON null counters and
no fabricated zero accepted-group count. Both are allowlisted, bounded
integer-only traces. The second pass must not overwrite rejection counts
from the original detector.

### Regressions required for review closeout

- Actual pinned OpenCV single thick stroke, single slanted stroke and long
  underline yield one Hough physical-band candidate, not two; two physically
  separated rules yield two.
- Actual guarded engine with synthetic gray-ruling and clear writing must
  **accept** verified line/word evidence and source-frame overlays. This
  non-vacuous acceptance case must not quietly catch-and-pass on refusal.
  Synthetic unclear/same-hue cases remain explicitly unavailable/refused.
- Blank/no-line full-engine outputs show `not_invoked` and null detector
  counters. Injected qualified-v2 detector rejection counts must survive
  the canonical reattachment unchanged.
- The 64 canonical IDs, four exact image properties and truthful missingness,
  private opt-in API/worker fingerprint, and guard-off defaults stay unchanged.

All review repairs are changes to an **unreleased** research candidate;
they cannot establish empirical real-handwriting accuracy or public
activation. Preserve the T11 source-rights gate, writer-disjoint holdout
and physical-handset requirements.

## Historical v3 ruling-audit repairs (superseded; synthetic only)

- Hough detections are grouped by actual foreground-ribbon continuity over 17
  fixed sampled columns, requiring complete group compatibility. This separates
  intersecting shallow paper lines without splitting a single thick stroke.
  Exceeding 8192 raw Hough detections or 512 qualifying candidates makes the
  stage unavailable and the guarded sample abstain.
- One-quarter-degree angle voting at bounded image size detects thin, subdegree
  synthetic ruled lines missed by earlier one-degree voting. This establishes no
  sensitivity figure for natural handwriting photographs.
- `hough_status` explicitly distinguishes checked, skipped-small-canvas,
  skipped-dense-foreground, unavailable-foreground and budget-exceeded cases.
  A skipped or unavailable Hough stage has `near_horizontal_long_bands: null`
  instead of a falsely measured zero. Research-guard processing abstains when
  that stage is unavailable, preserving the 60-dependent-measurement missingness
  and region-withholding rules.
- Word detector and final reattachment are separate ephemeral traces across all
  guarded profiles. Only fixed allowlisted counts from `word_stages.reattachment`
  may be serialized; the raw reattachment dictionary never enters report metadata.
- The historical v3 policy established a distinct digest from v1/v2; v4
  supersedes v3 for the optional guarded candidate. Guard-off hashes remain unchanged.

These tests and controls do **not** approve protected source collection, empirical
T06 calibration, public/staging activation, physical handset testing or closing
Issue #92. Exact-head CI and independent code/security review remain required.

## Historical v4 audit closeout candidate (superseded; synthetic only)

- `_distinct_hough_bands` admits only integer OpenCV `N×4` or `N×1×4`
  segment layouts and valid in-canvas endpoints, plus `None` for measured
  no-detection. Wrong ranks, dimensions, types and coordinates yield
  `malformed_response` with a null band count, not a fake budget failure.
- Exact `budget_exceeded` applies only when a bounded count is exceeded.
  Unsupported sampled foreground or strongly contradictory Hough directions
  inside one merged ribbon yield `insufficient_support` instead. Some very
  thick merged shapes are fundamentally non-identifiable from these pixels;
  there is no assertion that all crossings can be resolved.
- The authoritative engine always requires the foreground audit. Legacy
  `support_warning` compatibility contexts lacking optional `mask` retain
  previous structural decisions but cannot certify a real image. Structural
  rejection precedence, including low-resolution cases, is preserved.
- The mandatory synthetic positive runs `GraphologyEngine` without oracle
  detector boxes. Source-generated, independently annotated pen-word and
  ruling pixel masks are transformed to the analysis frame. One-to-one box
  matching, substantial pen coverage, bounded geometry and ruling-area
  contamination reject oversized/page-spanning false regions. A deliberately
  invalid oversized geometry must fail the same acceptance helper.
- `evidence-support/4` changes the guarded processing identity; previous
  guarded v1/v2/v3 jobs cannot execute against this method unnoticed.
  Unchanged guard-off legacy profiles remain the production default.
- No real-photo error rates, T11 rights clearance, independent approval,
  public promotion, participant data or resolution of Issue #92 follow from
  these synthetic engineering tests.

## V5 residual-ruling review repairs (synthetic-only candidate)

- **Grid-connector false merger:** the previous 17-column signature could count
  two distinct thin near-horizontal rules as one whenever a thin vertical grid
  connector joined both at each sampled x-coordinate. Physical-band equivalence
  now checks local predicted y separation against robust observed vertical ink
  thickness at the sample column and offsets ±7 px. Thin perpendicular bridges
  therefore cannot by themselves justify merging two 70-px-separated rules.
  Regular denser grid intersections may be `insufficient_support` rather than
  a confidently incorrect single band.
- **Thin subdegree false negative:** if the qualified HoughLinesP result has 0
  or 1 band and foreground stroke-equivalent is below a fixed, sparse-signal
  bound, use a restricted-angle standard Hough candidate check. Each standard
  Hough peak is only a proposal: require observed ink at at least 78% of
  sampled points along a full-width near-horizontal candidate (±1 px support),
  then deduplicate using the same foreground-ribbon physical-band grouping.
  Never publish raw accumulator-peak counts as physical lines.
- **Resource and uncertainty limits:** supplementary scanning is gated by
  previously verified primary status, canvas downsampling to 1024 px, the
  existing ≤35% foreground coverage gate, and bounded candidate counts
  (8192 raw / 512 supported). Malformed responses, actual budget overflows
  and unsupported geometric evidence remain distinct status values; null
  counts represent unavailable evidence. Existing preselection and
  postselection audits do not overrule valid handwriting solely because
  ruling existed before successful segmentation.
- **Reproducibility:** local development probes used OpenCV 4.13.0; the
  authority is exact-head locked CI with reviewed OpenCV 5.0.0.93 across
  Python 3.10, 3.11 and 3.12. Synthetic regressions cover connector
  aliasing, periodic connectors, 1-pixel shallow slopes, long underlines,
  thick single strokes, ordinary compact writing and pathological detector
  responses.
- The opt-in guard identity advances to `evidence-support/5`. The prior v4
  policy and hashes remain historical, while the public guard-off default
  and its fingerprint do not change.

This patch does not prove all physically distinct lines can be recovered from
arbitrary pixels. No physical handwriting corpus accuracy claim, real-source
permission, production activation, T06 completion or Issue #92 closure
follows from synthetic success. Confirm all seven exact-head workflow
families and re-review any substantiated new findings before merge.
