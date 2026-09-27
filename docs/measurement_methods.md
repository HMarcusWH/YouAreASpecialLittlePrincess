# Canonical measurement methods, core contract v1

The database defines 272 feature identities, types and units. Many of its
`formula_or_method` fields are null. The methods below resolve those operational
ambiguities; passing the structural contract does **not** establish algorithmic
accuracy or psychological validity.

## Frames, regions and input

Input is nonempty uint8 grayscale, BGR or BGRA. Alpha is composited onto white.
Other ranges/dtypes are rejected rather than silently guessing whether a float
means 0–1 or 0–255. Input arrays are not modified.

`IMG_WIDTH_PX`, `IMG_HEIGHT_PX`, `IMG_MEGAPIXELS`, `IMG_ASPECT_RATIO` describe the
original input. Result `width`, `height`, all region boxes and all other pixel
measurements describe the resized, deskewed **analysis canvas**. Boxes are
half-open `[x,x+width) × [y,y+height)`. Metadata contains both pixel-center affine
maps, including actual rounded x/y resize scales and deskew expansion.

Margins/utilization use analysis-canvas boundaries, including any deskew padding.
They do not identify physical paper edges. This first layout implementation assumes
one column; mixed columns, ruled backgrounds, figures and close crops need dedicated
segmentation/crop validation. Text-derived deskew cannot distinguish rotated paper
from intentional baseline tilt. `IMG_ROTATION_DEG` is the estimated input text
rotation, positive counterclockwise; applied correction has the opposite sign.
No usable skew evidence, disabled deskew or a search-boundary result yields missing,
not a fabricated zero. Baseline/slant are measured **after** this correction.

`page_0` is the analysis canvas. Lines belong to that page; words belong to exactly
one vertically overlapping line and are trimmed to foreground bounds. Components
are page-level connected-component regions; `COMPONENT` is a region primitive,
not a new feature ID or a claim to have recognized a glyph. Source references,
bounds, parent containment and cycles are checked before export.

## Confidence, missingness and statistics

`confidence: null`, `confidence_kind: UNCALIBRATED` means accuracy has not been
calibrated. It does not mean 0% or 100%. Only the four input-dimension calculations
currently use `1.0 / EXACT_CONDITIONAL`: exact given the decoded input array.
No line/word detection confidence feature is emitted. An eventual calibrated value
must have a separately documented calibration procedure and dataset.

Implemented-but-unavailable features still have a canonical record, `raw_value:
null`, `quality_flag: MISSING`, and a `missing_reason`. They never contain a fake
zero, an epsilon-denominator result or JSON NaN/Infinity. Means can have one sample;
variability/CV needs at least two. Population standard deviation uses `ddof=0`.
CV is std/mean only for positive means. A zero mean produces missing CV even when
std is also zero. `std_dev`, when supplied, has the **same unit as raw_value**.
The count census has one page observation even when its detected count is zero.
Pixel observations are not statistically independent strokes or letters.

`normalized` and `ratio` do not universally mean [0,1]: baseline waviness, aspect
ratios, x-height ratios and CV may exceed one. Explicit bounded scores/fractions
are checked separately. Units and names alone cannot validate a formula; numerical
and metamorphic tests are required in addition to schema tests.

## Operational definitions

| Family | Operational definition |
|---|---|
| Segmentation | Accepted line/word/final connected-component counts. Ink coverage is foreground pixels/canvas pixels. Text area is the enclosing line-bounds rectangle/canvas area, not the sum of overlapping rectangles. |
| X-height | Median of a dominant multiplicative ±factor-1.15 height cluster among eligible components. At least six inliers and half of eligible components; a competing disjoint cluster of at least 80% of the winning count makes the estimate missing. Sorted-window search uses linear auxiliary storage. |
| Component eligibility | Height ≥ max(3, 0.2 × median line height); width/height in [0.12,2.5]; at least five ink pixels; not touching the canvas boundary. This is a geometric filter, not lowercase recognition. |
| Glyph size | Mean/CV of eligible component height, width and width/height. The database permits glyph/component proxies; joined cursive, punctuation and all-capital samples can still mislead these descriptors. |
| Margins | Top/left text-bound coordinate, or canvas extent minus bottom/right text-bound edge, divided by the shared x-height. No x-height means these four values are missing. |
| Margin variability | Population CV of per-line left/right margins. Symmetry is `1-abs(left-right)/(left+right)`; zero total horizontal margin makes symmetry missing. |
| Centers/utilization | Text-bound center or extent divided by corresponding canvas dimension. |
| Line length | Mean(line width/canvas width), **not** line width/x-height; variability is CV of line widths. |
| Line drift | Least-squares slope of normalized start/end x-coordinate against normalized vertical line-center position. At least two distinct vertical positions. |
| Baseline angles | Linear regression of the 82nd-percentile foreground y in sampled columns of each line; at least six occupied samples. Positive angle rises to the right. Mean absolute angle is `BASELINE_ABS_SLOPE` in **degrees**, not abs(mean angle) or a dimensionless tangent. |
| Baseline waviness | Mean per-line population standard deviation of linear-fit residuals divided by shared x-height. |
| Baseline curvature | Mean absolute quadratic coefficient/4/x-height, with observed x span mapped to [-0.5,0.5]. This is normalized fitted sag relative to the chord, not differential geometric curvature. |
| Baseline stability | `1/(1+waviness)`, an engineering index, not a probability or empirically calibrated scale. |
| Line spacing | Mean clear vertical whitespace between consecutive, horizontally overlapping line boxes. Not baseline-to-baseline distance. Negative/overlapping gaps are excluded and counted in method metadata, never clamped to zero. |
| Word spacing | Mean clear horizontal gap between adjacent accepted words on the same assigned line. Unassigned/cross-line ambiguous proposals are rejected, duplicate/nested proposals suppressed, overlapping gap pairs excluded. Relative spacing divides by x-height; CV uses the gap vector. |
| Slant | Principal contour axis of elongated components, oriented upward before measuring from vertical. Positive means top leans right. External contours only; height ≥8 px, ≥12 contour points, covariance eigenvalue ratio ≥2, accepted abs(angle) ≤60°. Component axes are stroke-slant proxies, not recognized stroke segments. |
| Slant fractions | Left <−5°, vertical [−5°,5°], right >5°. These partition accepted observations. Extreme abs(angle) ≥30° is a separate overlapping fraction. Consistency is max(0,1−population_std/60). Thresholds are explicit engineering choices. |
| Darkness | `1-gray/255` at accepted foreground pixels, without separate contrast normalization. Mean/std/CV; saturation means gray ≤5 (near-black clipping), **not color saturation**. Deskew/resize interpolation can affect these values. |
| Thickness | Twice Euclidean distance to background, sampled on scikit-image's medial axis of a background-padded mask. Seeded tie-breaking makes repeats deterministic. This replaces averaging distances over every foreground pixel. Pixel-grid, junction and endpoint biases remain. |
| Stroke uniformity | `1/(1+width_CV)`, an engineering index. No physical pen-pressure feature is emitted. |

## Status and downstream migration

`DEFINED`: identity exists in the database; no extractor is registered.
`IMPLEMENTED`: an executable method is registered and covered by contract tests.
`EXPERIMENTAL`: implemented estimator/index lacks appropriate real-data calibration.
`VALIDATED`: reserved for separately documented empirical validation. These are
capabilities/evidence dimensions, not a claim that every implemented method is validated.
This PR registers 64 features; 208 remain definition-only. Four input metadata
calculations are exact conditional on decoding. All remaining outputs are marked
experimental or missing. Synthetic tests do not promote anything to VALIDATED.

Unknown confidence and missing values must be handled before comparison. Align by
feature ID **and method/frame compatibility**, select jointly observed dimensions,
and use a reference scaling/covariance model; never replace missing values with zero
or compare arbitrary pixel scales. This PR does not implement that comparison-policy
layer. Existing comparison math is unchanged. Historical `baseline_band` now accepts
the canonical positive-rising angle sign; other historical bands remain uncalibrated.

Old bootstrap JSON cannot be migrated by renaming keys: margins, CVs, width sampling
and coordinate conventions changed. Re-analyze retained images. No compatibility
shim or silent reinterpretation of old numbers is provided.

## Runtime contract and provenance

`tools/generate_feature_contract.py` projects all 272 IDs, units, data types, scopes,
input modes and evidence enums into a 29 KB packaged JSON resource with the full
source SHA-256. It must not be hand-edited. CI checks regeneration, every emitted
measurement, negative cases and wheel-installed operation outside the source tree.
The full 194 KB research database is not needed at runtime.

The core supports scalar numeric measurements. The validator also checks structural
vector/enum compatibility for future stages; the source database does not specify
all vector lengths, enum vocabularies or distribution semantics. Adding those
extractors requires corresponding semantic contracts and tests, not merely passing
this generic validator. Scope is retained as provenance; current engine outputs are
page-level aggregations of line/word/component observations, with source regions.

Research-source records remain unchanged. `schema/implementation_sources.json`
records actual deployment provenance, including selected `luizgh/sigver` and JJ
Shay's design-reference-only role. Existing third-party notices remain intact.

Method reference: [scikit-image medial_axis API](https://scikit-image.org/docs/stable/api/skimage.morphology.html#skimage.morphology.medial_axis).

## Evidence payload (`evidence/1`, T05)

`GraphologyEngine.analyze_with_evidence(image)` returns the unchanged `AnalysisResult` plus a separate evidence payload computed from the same measurement context. The aggregates and the payload call the same observation functions (`baseline_fits`, `slant_candidates`, `line_gaps`, `word_gaps`, the component size lists), so an evidence-derived mean, median or percentile reproduces the canonical aggregate exactly; `tests/test_evidence.py` checks this.

| Observation family | Keyed feature (primary estimand) | Method | Rejections recorded |
|---|---|---|---|
| Per-component slant axis | `SLANT_ANGLE_MEAN` | `oriented_component_axis_v1` | `not_elongated`, `outside_accepted_range` |
| Per-line lower-envelope fit | `BASELINE_ANGLE_MEAN` (+ up to 12 `BASELINE_POINT` regions per line) | `bottom_quantile_angle_v1` | lines with fewer than six samples are not observations |
| Adjacent line / word box gaps | `LINE_SPACING_PX`, `WORD_SPACING_PX` | `accepted_box_gap_px_v1` | `overlapping_boxes` |
| Filtered component boxes | `GLYPH_HEIGHT_MEAN`, `GLYPH_WIDTH_MEAN` | `component_box_size_v1` | — |
| X-height inlier components | `X_HEIGHT_PX` | `component_height_mode_v1` | — |

An observation is one sample of the population behind a feature family; it is keyed to the family's primary feature so the T01 compiler can check its canonical unit, type and method. Histograms and traces must be drawn from these observations, never from a fitted curve.

Frames: `frame_input` (the image given to the engine) is the root; `frame_analysis` is its child with the `analysis_to_original` matrix as `transform_to_parent`. Upstream crop or perspective rectification is attached with `princess_app.domain.evidence.prepend_source_frame`, and `map_point` composes the chain. `page_0` is the analysis canvas, not a detected paper edge.

Bounds: at most 4096 regions (page and lines, then baseline points, words, components) and 20000 observations; truncation is reported in `warnings` and observation region links are pruned to kept regions. Non-finite values are never emitted. `princess_app.domain.evidence.build_evidence_bundle` binds the payload to an `AnalysisReference`, fills method versions from the resolved capability manifest and compiles it as a T01 `EvidenceBundle`; any contract issue yields no value.
