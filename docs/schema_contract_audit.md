# Schema-contract PR audit

Audited base: `a59c8d2dc1a91a2cec3a5ba10930b4831ba89d66`.
Authoritative database blob: `f8c2bb6ab48852e81ec88b84897fbe44d4f94c1c`.
Full source SHA-256: `5c21dfc9f594bbb1c2e9dad77e3b0664a0f53b33b33697311539f7b6ca52b607`.

## Corrections to the proposed plan

1. Validate at runtime and again on export, not just in CI. Generate the packaged
   contract instead of maintaining an independent hand-written ID list.
2. Preserve original acquisition dimensions and explicitly record analysis-canvas
   geometry, half-open regions and bidirectional transforms.
3. Margins divide by x-height; line length divides by canvas width. Baseline
   absolute slope is specified in degrees. Normalized does not always mean [0,1].
4. X-height/glyph statistics are component-based experimental proxies, not proof
   of lowercase glyph recognition. Missing/ambiguous normalizers propagate null.
5. CV requires adequate observations and a positive denominator. Unknown confidence
   is null, not a hard-coded probability. Stability indices are not confidence.
6. Reject duplicate measurements and validate JSON types, finite values, evidence
   enums, source references, region bounds, containment and parent cycles.
7. Slant axis direction must be sign-invariant and mirror correctly. Thickness must
   sample medial-axis distances, not average radii over every foreground pixel.
8. Use accepted, trimmed word boxes with unique overlapping-line assignment.
   Never turn overlapping boxes into artificial zero spacing by clamping.
9. Historical baseline labels used the opposite sign: convert their thresholds to
   the canonical positive-rising convention. No personality classifier is added.
10. Preserve research lineage in the original JSON; separate deployment provenance
    identifies `luizgh/sigver` and JJ Shay's design-reference-only role.

## Executed verification

Local environment: Python 3.13.5, NumPy 2.3.5, OpenCV 4.13.0, SciPy 1.17.0,
scikit-image 0.26.0, pytest 9.0.2.

- **91 tests passed**, including schema/negative tests, repeatability, no input
  mutation, scaling/mirroring, blank/uniform input, 20,000-component mode estimation,
  CLI JSON and the existing comparison-math test.
- `python -m compileall -q src`: passed for the local core source.
- `python tools/generate_feature_contract.py --check`: passed.
- Wheel build: passed. Installing it into an isolated target and running outside
  the checkout loaded the packaged contract and emitted 64 blank-image records.
- Git tree hashes verified that all changed source and test bytes match the local
  tested files; unchanged optional source blobs were retained by their base hashes.

The available local interpreter is **3.13**, not the requested 3.10/3.11/3.12 matrix.
Ruff is not installed locally. No local Ruff or three-version success is claimed.
The initial hosted workflow failed before returning executable step logs; it is
not evidence of passing tests. Final CI includes 3.10/3.11/3.12, Ruff, regeneration,
pytest, compilation and wheel-installed smoke tests. Require a successful hosted
run before treating that matrix as verified. Branch protection is not modified:
a workflow's existence alone does not make checks mandatory for merging.

## Explicitly deferred

No real-handwriting corpus validation, calibrated detector accuracy, UI, OCR,
topology expansion, signature weights, pressure inference or personality assessment.
The existing scale-space detector response/parameters are retained; word-detection
accuracy, multi-column handling, merged cursive and ruled backgrounds require a
separate labeled-data segmentation audit. Current tests do not establish those.

Two database issues outside this PR's emitted feature set must be resolved before
wiring the corresponding modules: several online peak/valley definitions declare
`FLOAT` despite a `vector` unit; `CMP_COSINE_SIMILARITY` declares a 0–1 score while
the existing standalone cosine utility can return negative values. No silent
conversion or schema rewrite is made here. These features remain definition-only
in this measurement engine. Generic vector validation is not a substitute for
feature-specific shape/vocabulary/ranked-payload contracts.

Old bootstrap output must be remeasured from source images, not relabeled.
