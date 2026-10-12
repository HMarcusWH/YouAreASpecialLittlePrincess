# Qualified Segmentation v2 — review and release gates

This PR is an **experimental engine and measurement-validity** change, not a
claim of empirically validated handwriting segmentation or permission to
activate the new processing profile on public services.

## Immutable baseline and profile names

- Source branch: `feat/segmentation-v2-qualified-pipeline` from merged #80 (`dc1b586`).
- Historical `legacy` remains the implicit default. Its old analysis config
  hash and `grid-v1`'s pre-existing hash remain unchanged.
- V2 opt-in: `PRINCESS_ANALYSIS_PROFILE=qualified-v2`, only for local/test
  with `PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN=1`.
- Separate API and worker processes also require an identical
  `PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256`; the Railway combined test stack
  pins and passes the hash to both roles. Public guest-only remains legacy.
- V2 uses `quality-policy/2`. Existing feature IDs, units and stage equations
  remain canonical; the versioned processing config records new inputs and
  segmentation acceptance semantics without rewriting old report identities.

## Deterministic pipeline contract

`source pixels → optional qualified document ROI/homography → deskew →
periodic chromatic/gray ruling evidence → observed retained ink →
qualified text-line grouping → scale-aware WordDetector trace and conservative
geometric ink groups → MeasurementContext with qualification →
canonical facts with MISSING/null on unqualified support → immutable evidence
and saved reports → permission-filtered client projections`.

Any stage may refuse or withhold a family. In particular, a numeric zero from
`len(words)` is NOT factual zero when the proposed word groups did not qualify.
Page-border candidates cannot enter accepted LINE regions or baseline evidence.
Missing facts cannot provide content-selection support.

A word *group* is a geometric spacing proxy, not proof of a linguistic word.
Image darkness and stroke thickness remain photographic proxies, not pressure.

## Mandatory fixtures / acceptance

- Rights-safe full-frame gray and blue grid, dark-grid same-tone ambiguity,
  grid-only blanks, tabletop page rectangles, near-edge genuine ink, intersections
  and resized/perspective source-frame round trips. No real user writing in public
  CI, code review or Actions artifacts.
- Measure false authoritative line bands, line/word IoU/F1/count MAE, false-zero
  words, unavailable families, ink retention and baseline evidence consistency.
- Benchmark the **same** immutable images and annotations under `legacy`,
  `grid-v1` and `qualified-v2`. Rejections and partial results must be included
  in denominator/coverage; never quietly drop difficult samples.
- Licensed/consented real originals must be handled separately on a protected
  machine. Match exact stored source hashes, freeze writer-disjoint development
  and holdout manifests, independently review annotation disagreement, and
  pre-register acceptance thresholds + holdout manifest digest **before**
  evaluating the holdout. The offline protocol tool checks leakage and pins,
  not legal rights or scientific validity.
- Verify resource ceilings, CPU, memory and latency at real smartphone
  resolutions and the actual deployed wheel/worker—not only NumPy fixtures.
- Python 3.10–3.12, RLS/intake/report, generated-contract check, web/native
  compatibility and source-image overlay coordinates must pass on the exact head.
- Separate isolated Railway test deployment, pinned `/health/build` source SHA,
  signed APK artifact and *actual handset* test are required to approve public
  activation. Emulator success is not handset qualification.

## Quality, versioning and rollback

- Preserve all **64 implemented** Free feature IDs. If their evidentiary
  dependency fails, use existing engine `MISSING` with explicit
  `missing_reason`, null value and no misleading number/confidence.
- Existing product Quality has a separate `REJECTED` status; v2 does not
  silently add it to engine measurements. Whole-job ambiguity may fail closed
  with the existing `GridQualityError` codes and localized recapture guidance.
- Store the v2 configuration hash and `quality-policy/2` in each
  `AnalysisReference`. Do not reinterpret older `ReportDocument` snapshots.
  T18 comparison rejects unknown or mismatched processing hashes.
- Paper ROI detection is optional, conservative and reversible; when the actual
  paper boundary is not qualified, page-margin measurements remain missing.
- Keep `legacy` production-default at v2 merge. A later reviewed deployment
  and policy change is necessary to activate V2 broadly.
- Keep Issue #92 open until privately reproduced, writer-disjoint empirical
  criteria and installed-handset evidence are recorded. Do not close on green
  synthetic tests alone.

## Source and privacy policy

Deterministic OpenCV/NumPy only; **no learned local model, OCR, network AI,
face/person/writer identity model, or third-party source/code copied**.
Source code licenses do not establish rights to photographs or reference datasets.
No pixels, user specimen identifiers, paths or private diagnostics in public CI.

## Next evaluation-integrity slice — synthetic-only frozen runner

The protected real-data run remains **NOT AUTHORIZED** while T11
`pilot_rights_consent` is pending. This engineering slice does not change
the `legacy` runtime default or the 64 canonical Free outputs.

- Preserve the old v1 protocol checker for historical tests, but
  `score_holdout` no longer permits an unverified caller-supplied aggregate
  to return `accepted: true`.
- For v2 engineering tests, freeze **development, validation and holdout**
  synthetic manifest hashes. Partition by writer, capture, source specimen,
  input digest and specimen ID across all three splits. Missing `lines` and
  `words` annotations are unknown, not explicit empty ground truth.
- Pin the actual local checkout commit, evaluator file bytes, qualification
  implementation bytes and qualified-v2 processing configuration in a
  separately prepared reviewed synthetic policy. This is not signed
  execution attestation or permission to ingest real photographs.
- Run the full synthetic holdout through `run_frozen_synthetic_qualification`
  rather than passing the scorer an aggregate. Per-family annotated/nonempty
  coverage retains refused specimens in its denominator. Empty cases cannot
  inflate nonempty handwriting F1. Unset thresholds fail closed.
- Only the synthetic engineering receipt may say `ENGINEERING_PASS`.
  `public_qualification` remains `NOT_AUTHORIZED`; the redacted exporter
  never includes specimen-level IDs, paths or private digests.
- Run `python -m pytest -q tests/test_segmentation_qualification_integrity.py
  tests/test_qualified_segmentation_protocol.py
  tests/test_segmentation_benchmark_frames.py` and all exact-head CI. No
  empirical T06 completion, holdout opening, real-device signoff, Issue #92
  closure or production activation is permitted by a green synthetic run.

Next independent changes: paired comparison and source-frame annotation
families; separate T11-authorized real evaluation and finally exact-SHA
physical-handset qualification.

### Codex qualification integrity repairs

The synthetic v2 gate requires independently scored nonempty handwriting and explicitly annotated empty line/word conditions, with predeclared minimum empty counts, maxima for false-positive pages and minimum empty coverage. It accepts a validation split only under the explicit synthetic-fixture path and rejects duplicate JSON keys and nonfinite constants. Frozen manifest digests use the exact parsed input bytes.

The frozen policy now pins the actual reviewed CI dependency target on Python 3.10/3.11/3.12 (Linux x86_64), NumPy/OpenCV imported and distribution versions, the reviewed lock/manifest digests and the installed distribution map. Unreviewed environments refuse qualification; separate platform qualification needs its own approved lock. Neither source nor dependency hashes replace legal data authorization, independent photo ground truth or device checks.
