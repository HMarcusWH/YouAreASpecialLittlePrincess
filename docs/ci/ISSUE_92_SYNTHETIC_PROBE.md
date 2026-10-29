# T06 / Issue #92 — four-profile synthetic-only diagnostic probe

**Implemented candidate:** `evaluation/segmentation/issue92_probe.py` (`issue92-synthetic-probe/1`).

This tool compares four **already implemented** processing branches on **the same digest-verified, decoded synthetic pixels**:

1. `legacy` without an evidence guard;
2. `grid-v1` without an evidence guard;
3. `qualified-v2` without an evidence guard;
4. `qualified-v2` with `evidence-support/5`.

The probe **does not** accept any real-data mode. It refuses manifests that are not explicitly `schema_version: 2`, `split: synthetic`, `synthetic: true`, `annotation_frame: original_image`. Public fixtures must be **programmatically generated** and have no personal handwriting. A synthetic label is not proof of human-data rights; do not submit an actual photograph through this tool.

## Why an independent probe?

The established `evaluation/segmentation/benchmark.py` accepts three processing profiles, but has no fourth guarded-v5 branch in its ordinary evaluator. This additive probe **reuses its exact-file SHA, no-follow path admission, bounded header/decoder checks, original-to-analysis annotation mapping and bounded IoU matching**. It does not modify the frozen synthetic qualification runner, its approved policy hashes, or the published score definitions.

The output is a diagnostic receipt, **not** a qualification result. No source paths, writer/capture/specimen IDs, raw image bytes, source pixel digest, source coordinates or private overlays are included. It reports per-case ordinal, declared synthetic paper class, raw numeric line/word facts or null, page text-area ratio or null, accepted LINE/WORD region counts, baseline-point count, guarded word-stage counters, status, configured analysis SHA, bounded line/word matching and per-profile summary with nonempty F1 **and** nonempty coverage. Unknown annotation families remain null; absence of accepted word groups is never silently changed to observed zero.

The receipt always states `data_origin: SYNTHETIC_FIXTURE`, `public_qualification: NOT_AUTHORIZED` and no approved thresholds.

## Synthetic invocation

Generate a fixture manifest and source images **outside the repo** using the schema already supported by `benchmark.py`, with synthetic `paper` labels, original-frame line/word rectangle lists and exact encoded PNG/JPEG SHA-256. For example:

```sh
PYTHONPATH=src python -m evaluation.segmentation.issue92_probe \
  --manifest /tmp/issue92-generated/manifest.json \
  --image-root /tmp/issue92-generated
```

The probe shares the benchmark's strict source admission. Orientation other than EXIF=1 is refused rather than silently rotating source labels. Each candidate uses `GraphologyEngine.analyze_with_evidence`, so a guard-withheld result cannot emit authoritative LINE/WORD/BASELINE regions. A quality refusal is `REJECTED`, distinct from `MISSING` and from a measured numerical zero.

## Tests and limitations

Run `python -m pytest -q tests/test_issue92_probe.py tests/test_segmentation_benchmark.py tests/test_qualified_segmentation_v2.py` in the repository's reviewed, hash-locked Python matrix; then complete all triggered workflows on the **exact** PR head. Verify the positive guarded synthetic specimen is not a blanket refusal, that blank/unknown input stays unavailable, and that SHA/path/JSON corruptions fail closed.

This does **not** implement T11 real source permission, real-vs-resized original comparison, writer-disjoint empirical calibration, independent annotation, latency/RSS budgets or physical Android capture. Those remain in [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92) and must be completed in a separate protected runner and review process **only after owner rights approval**. In particular, a synthetic F1 or acceptance ratio must never be represented as a human handwriting accuracy claim.

**Rollback:** remove this standalone tool/tests/doc; the numerical core, legacy/public defaults, saved reports, source rights and active service configuration are not modified.
