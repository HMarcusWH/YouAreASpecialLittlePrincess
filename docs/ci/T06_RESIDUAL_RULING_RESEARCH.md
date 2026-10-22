# T06 residual ruling qualification — synthetic research only

**Source:** Main baseline `0c9470b0a0fdcb6ba3c45f17c6a1b94789e63b50` (merged PR #96). This is a research candidate for open [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92), **not** field-validated handwriting recognition or production release authorization.

## Implementation and provenance

- `evidence-support/3` is a versioned update to the existing opt-in guarded analysis. The flag `PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN=1` remains permitted **only** in explicitly paired and digest-pinned private local/test API + analysis-worker processes. Public guest, staging and production still reject it. Default guard-off processing hashes, outputs and the historical report writer are unchanged.
- A bounded independent retained-foreground audit counts (a) wide horizontal ink rows, (b) near-horizontal long Hough segments, and (c) page-width line boxes versus compact component support. It does not crop pages or alter pen/ruling pixels. The prior page-spanning, dominant-thin and low-resolution checks remain in front of the new checks to retain prior refusal reasons.
- Multiple suspect foreground bands cause **full conservative abstention even when a word detector admitted some groups**. Zero accepted word groups and zero accepted text lines are treated as unavailable evidence, not as proof a page contains no handwriting.
- The private `evidence_support_audit` records only versioned statuses, bounded counts and fixed reasons; it has no pixel arrays, boxes, source image paths, transcriptions, participant IDs, or raw detector payloads. Missing stages are JSON null, not fabricated zero.
- If abstaining, all 64 canonical features remain, with the four exact input-image facts still present and 60 unsupported handwriting-dependent facts `MISSING` with explicit reasons/null values. Suppress unsupported LINE/WORD/COMPONENT and baseline evidence; the existing `individual-report/3` projection and honest Premium eligibility behavior apply.
- The separately versioned guard digest prevents old v1/v2 guarded jobs from silently executing under policy v3. Explicit version changes require API/worker startup pin updates; an unmodified default remains legacy.

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
pen stroke. The repaired `evidence-support/3` groups line candidates by
slope, y position at a shared reference x and overlapping horizontal
support. A separate candidate requires independently separated long-band
evidence; this is still only a conservative visual proxy for ruling, not a
printed-vs-handwritten classifier.

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

All review repairs are changes to this **unreleased** v2 research candidate;
they cannot establish empirical real-handwriting accuracy or public
activation. Preserve the T11 source-rights gate, writer-disjoint holdout
and physical-handset requirements.

## Final v3 ruling-audit repairs (synthetic only)

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
- The research policy identity advances to `evidence-support/3`, keeping
  previous opt-in v1/v2 digests distinct while guard-off hashes remain unchanged.

These tests and controls do **not** approve protected source collection, empirical
T06 calibration, public/staging activation, physical handset testing or closing
Issue #92. Exact-head CI and independent code/security review remain required.
