# Ground-truth line and word benchmark

This is an offline engineering evaluator, never imported by the Free engine.
It measures one-to-one IoU (threshold 0.5), precision/recall/F1, count MAE,
matching centroid errors and annotated false-zero word pages, by paper/split.

Run with a locked Python environment from the repo root:

    PYTHONPATH=src python -m evaluation.segmentation.benchmark --manifest /approved/manifest.json --image-root /approved/images

Manifest: JSON with schema_version 1, split (synthetic/development/holdout),
and a specimens list. Each record has specimen_id, writer_group, capture_group,
image_path (relative to image-root), sha256 (SHA256 of exact file bytes),
paper (blank/lined/grid/form/unknown), lines (list of x,y,width,height boxes),
and optional words boxes. Omit words if unannotated; [] means annotated
empty. Annotate in the same analysis-canvas coordinate frame returned by
prepare_context, not the original frame if resized or rotated.

For real images, source consent/rights review is required before executing;
the additional --allow-authorized-real switch is only a local safety guard,
not proof of permission. Never check specimens into Git or emit pixels in CI.
Synthetic results are regression checks, not empirical accuracy. Freeze
writer-disjoint holdout partitions and targets before parameter selection.

Experimental word grouping can be compared only offline with --shadow-words; a generated visual cluster is not a validated linguistic word. Do not automatically activate or use its output as PAGE_WORD_COUNT.
