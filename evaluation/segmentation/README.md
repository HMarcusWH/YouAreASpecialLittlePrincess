# Ground-truth line and word benchmark (qualified evaluator v2)

This is a **local, offline evaluation harness**, not a production Free measurement method or calibrated classifier.

Run from repository root in the locked Python environment:

`PYTHONPATH=src python -m evaluation.segmentation.benchmark --manifest /approved/manifest.json --image-root /approved/images --shadow-projection --shadow-words`

## Manifest and annotation geometry

Use a **schema_version 2** JSON manifest with explicit `"annotation_frame": "original_image"` for phone photos annotated in their original, decoded image coordinate frame, or `"analysis_canvas"` for deliberately preprocessed annotations. The runner maps all four corners of each original rectangle through the actual per-image `original_to_analysis` transform, clips to the canvas, and creates a half-open bounding rectangle. Boxes are `[x, y, width, height]` with positive dimensions. Mapping a rotated rectangle to an axis-aligned box adds known rasterization error.

Legacy schema_version 1 manifests still mean `analysis_canvas` unless explicitly labeled. For production-quality evidence, migrate to v2, don't guess coordinates.

Manifest has `split` (synthetic/development/holdout), and `specimens` objects with `specimen_id`, `writer_group`, `capture_group`, `image_path` (root-relative), exact encoded-file `sha256`, `paper` (blank/lined/grid/form/unknown), `lines` annotations, and optional `words`. Omitted `words` = **not annotated**, whereas `words: []` = annotated empty page. Real records require a reviewed `rights_decision_id`.

## Evaluation

Existing line and word detectors are scored separately from optional TLC-inspired line and whitespace-grouped word *shadow* candidates. Scores include one-to-one IoU (0.50 threshold), macro precision/recall/F1, count MAE, matched IoU, center error, false-zero word cases, rejections, and paper/split breakdowns. Missing annotations and unrun shadow methods are reported as null, not scored as zero. Candidate-limit truncation refuses a misleading partial score. Synthetic fixtures are **engineering regression evidence only**.

Max 256 specimens per run, 25MB per encoded file, 24 megapixels decoded and 4096 annotations per family per image. Images/digests are verified locally; the JSON output contains no pixels or region coordinates. These checks are guardrails, **not** a data-access control system. Keep source images, private specimen identifiers and full manifests outside public Git/CI.

Before claiming real accuracy: obtain consent and explicit per-use rights, freeze writer-disjoint development/holdout partitions, agree on annotation criteria, audit annotator disagreement, pre-register targets, and evaluate once on held-out samples. The `--allow-authorized-real` switch is a secondary guard, not proof of clearance.

Never promote shadow candidates to authoritative `PAGE_LINE_COUNT` or `PAGE_WORD_COUNT` from synthetic results alone.
