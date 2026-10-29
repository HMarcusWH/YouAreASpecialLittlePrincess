# Issue #92 — acceptance and provenance matrix

**Recorded against:** `main` `25e4fc2de069f2b4ea3ce0aa133739f733d0304f` (29 October 2026)  
**Owner:** T06 engineering + T11 protected empirical evaluation + native/release reviewers  
**Status:** synthetic engineering contract; **not** real-writer validation, rights approval, device signoff, public activation or Issue #92 closure.

This ledger reconciles [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92) with merged PRs [#80](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/80), [#93](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/93), [#95](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/95), [#96](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/96), and [#97](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/97). The repository contains experimental `qualified-v2` segmentation, `quality-policy/2`, and opt-in `evidence-support/5`; **legacy remains the default**, and the research switches are prohibited in public/staging/production. Closed PRs and synthetic checks are not proof of field accuracy.

## Execution contract

- **Known positive** means accepted **without a caught `GridQualityError`** and with genuine nonempty supported line/word regions in the correct transformed pixel frame. Count both guarded and unguarded `qualified-v2` candidates. A new algorithm cannot 'pass' simply by refusing all handwriting.
- **Known negative** means no authored handwriting measurement or false LINE/WORD/BASELINE evidence. A typed `GridQualityError` or `MISSING`/no region is acceptable; record rejection separately so coverage is not hidden.
- **Ambiguous** means abstention is acceptable until independently approved ground truth exists. `0` must not substitute for detector failure. `UNCALIBRATED` never means empirically validated.
- All samples in public CI are synthetic OpenCV shapes. *No private camera bytes, handwriting, participant IDs, sensitive digests, ground-truth coordinates or transcriptions* are committed or emitted to Actions.
- Real-source testing follows T11 permission and source-rights approval, independent annotation, writer-disjoint predeclared holdout, and a protected evaluation environment. Frozen holdout scores and acceptance thresholds must be set **before** results are viewed.

## Case register

| Case ID | Data origin / rights | Expected result | Current evidence / next witness | Owner / gate |
|---|---|---|---|---|
| `original-tabletop` | Private real-photo report, original bytes not retained in public repo; authorization pending | Correct ink-supported geometry **or** explicit refusal/MISSING; no page/table baseline, fictitious six lines or false 1.00 writing coverage | **NOT RETESTED.** Reproduce with exact authorized original bytes and camera-to-analysis transform | T11/T06, source-rights and private reproduction |
| `original-full-frame` | Private real-photo report; authorization pending | Similar acceptance, no neutral ruling as text | **NOT RETESTED.** Separate upload resize/rendition from original source SHA | T11/T06 |
| `original-tight-crop` | Private real-photo report; authorization pending | Same semantics despite framing; helpful localized rejection when ambiguous | **NOT RETESTED.** Compare captured bytes and provenance; framing-dependent abstention is reported | T11/T06/native |
| `synthetic-blank` | Public generated blank mask | No accepted text/baseline, independent image dimensions retained; no factual false-zero words | `test_predeclared_blank_never_becomes_positive_with_either_guard_state`, existing blank guard tests | T06 / synthetic negative |
| `synthetic-grid-only` | Public `grid_v2_cases.grid_only` with gray/blue/black rules | No handwriting-derived facts or regions; explicit abstention/refusal | `test_grid_without_text_is_not_authoritative_handwriting` | T06 / synthetic negative |
| `synthetic-ruled-positive` | Public `grid_v2_cases.page` (gray ruling + black synthetic pen) | Exactly one supported line and at least two geometric groups under **guard OFF and ON**, with real pen support, no invented paper-line boxes | `test_predeclared_ruled_positive_requires_real_ink_with_both_guard_states`, `test_real_engine_accepts_predeclared_clean_ruled_handwriting_positive` | T06 / non-vacuous positive |
| `synthetic-same-tone` | Public dark pen/rule ambiguity | Reject or withhold measurements, never destroy uncertain intersections and declare success | `test_same_tone_grid_and_pen_fail_closed_or_withhold_text` | T06 / synthetic negative |
| `synthetic-near-edge` | Public synthetic near-boundary pen mask | If supported, accepted evidence must overlap actual ink and preserve source transform; refusal recorded separately | `test_near_edge_pen_must_not_be_clipped_into_invalid_evidence`; strict positive pending development evaluation | T06 / conditional geometry |
| `synthetic-perspective` | Public synthetic page/table/perspective masks | Valid reversible frame mapping and no full-frame ruling leakage; refusal recorded | `test_inset_paper_perspective_never_launders_grid_into_layout` | T06 / conditional geometry |
| `real-writer-holdout` | Not collected or authorized; rights-controlled only | Predeclared nonempty accuracy AND aggregate coverage, false-zero/false-line/abstention bounds, baseline overlap, memory/latency; no holdout tuning | **PENDING T11.** Separate right-cleared annotations and independent review receipt, never public pixel data | T11→T06 empirical gate |
| `physical-android` | Authorized private capture, not public CI | Matching APK/backend/profile config and actual camera/evidence frame overlays, error/recovery behavior | **NOT PERFORMED.** Signed source-pinned device and private deployment receipt | T30A/T24/release gate |

## Implementation and release decision boundaries

1. Original issue describes a legacy/grid-v1 failure. Its exact current results on `qualified-v2+evidence-support/5` are **unknown**, not 'fixed' by PR merge.
2. The production `GraphologyEngine` defaults to `legacy`, `evidence_guard_enabled=False`; `resolve_analysis_runtime` only permits experimental profiles and guard in explicit private `local/test`. Preserve historical default config hashes and immutable report/analysis revisions.
3. New `individual-report/4` Free Dossier still lacks a release-qualified support path combining the v2 algorithm and v5 audit. This is **S92-05**, a separately reviewed candidate—not permission to toggle existing research flags publicly.
4. S92-02 through S92-07 require protected source-specific diagnosis, any resulting *targeted* algorithm/word-group improvements, real writer-disjoint validation, physical-device proof, and approval of a versioned rollout/rollback. A passing synthetic witness is not a substitute.
5. Keep Issue #92 open and T06 PLANNED until the real evidence/activation gate is satisfied. Do not change canonical 64 feature IDs, frozen research, historical result digests, product/identity/consent/commerce rights or production provider switches under this documentation/test slice.

## Executable checks and acceptance receipts

Run under the repository's supported hash-locked Python 3.10–3.12 matrix:

```sh
PYTHONPATH=src:tools:apps/api python -m pytest -q \\
  tests/test_qualified_segmentation_v2.py \\
  tests/test_residual_ruling_guard_v2.py \\
  tests/test_evidence_support_guard.py \\
  tests/test_grid_versioning.py \\
  tests/test_segmentation_benchmark.py \\
  tests/test_report_suitability.py
python docs/roadmap/plan_tools.py --check
python tools/documentation.py --check
```

The exact PR-head CI, visual/device and independent-review results belong in the PR acceptance receipt; this document does not claim these commands were executed locally. Changes to the synthetic policy or acceptance cases need a new reviewed matrix revision rather than weakening previously passing negative/positive witnesses.
