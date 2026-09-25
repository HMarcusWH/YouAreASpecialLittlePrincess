# Source provenance

| Source | License | Implementation role |
|---|---|---|
| NitinRamchandani/ocr-preprocessing-tool | MIT | Adapted geometry, binarization, denoise, glyph normalization/descriptors |
| githubharald/WordDetector | MIT | Adapted scale-space word proposals |
| titanh3art/ml-graphology | MIT | Historical thresholds/provenance only; no SVM personality model |
| jjshay/handwriting-analysis | MIT | **Comparison/statistical design reference**; production comparison mathematics independently implemented |
| luizgh/sigver | BSD-3-Clause | Selected optional SigNet architecture; no pretrained weights |

`src/princess_graphology` is canonical; upstream repositories are not vendored wholesale.
The schema's `sources` describe the database's research lineage, not a deployment
manifest. They remain unchanged to avoid erasing historical provenance. Actual
implementation choices are machine-readable in `schema/implementation_sources.json`.
In particular, `luizgh/sigver_wiwd` and `EB324/signature_verification` are research
references, **not the selected signature implementation**.

New measurement orchestration, contracts, tests and descriptor aggregation are
project code. Stroke thickness uses the installed scikit-image `medial_axis`
implementation; no third-party source is copied for this change. Existing notices
and license files remain in force. Signature code and weights are not loaded by
the core engine. Statistical comparisons remain descriptive, not identity or
authenticity probabilities.
