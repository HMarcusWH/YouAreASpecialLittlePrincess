<!-- roadmap-v2-navigation -->
> **Building the app:** [complete roadmap](ROADMAP.md) · [coding-agent entry](AGENTS.md) · [documentation index](docs/roadmap/00-index.md) · [detailed task briefs](docs/roadmap/06-agent-backlog.md).
> The web/iOS/Android product is planned in the linked roadmap. The library documentation below describes the existing measurement core, not a claim that the full consumer app is already implemented.

# YouAreASpecialLittlePrincess — Canonical Measurement Engine

Deterministic handwriting-image descriptors with a schema-enforced interface.
**272 defined features ≠ 272 implemented or validated features.** The core currently
registers **64 features**; 208 remain definition-only. Unavailable implemented
features return explicit missing records, not invented numbers.

## Architecture

```text
image → preprocessing → line/word/component segmentation
      → shared MeasurementContext (including experimental x-height)
      → quality / segmentation / size / layout / baseline / spacing / slant / ink
      → AnalysisResult → runtime schema + region validation → canonical JSON
```

`GraphologyEngine` orchestrates the pipeline; extractors share immutable image
arrays and segmentation primitives. Duplicate IDs, unknown IDs, wrong units,
invalid types/ranges, non-finite values and broken region references fail loudly.
The 272-feature database is authoritative; a generated, packaged 29 KB projection
provides the runtime contract. CI checks that it has not drifted.

## Install and run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python tools/generate_feature_contract.py --check
ruff check src tests tools
pytest -q
princess-graphology path/to/handwriting.png --pretty
```

```python
from princess_graphology import GraphologyEngine

result = GraphologyEngine().analyze_file('handwriting.png')
print(result.to_json())  # Validated again; strict JSON, no NaN/Infinity.
```

The CLI accepts grayscale, BGR and BGRA uint8 images; alpha is composited on white.
Original image dimensions are separate from analysis-canvas dimensions. Result
metadata supplies both affine coordinate maps and method/frame caveats.

## A real fixture result

The following is an excerpt from the committed synthetic text fixture, not an
invented confidence example. Run `tools/example_result.py` to regenerate it.

```json
{
  "X_HEIGHT_PX": {
    "raw_value": 17.0,
    "unit": "px",
    "confidence": null,
    "n_observations": 48,
    "method_version": "component_height_mode_v1",
    "quality_flag": "EXPERIMENTAL"
  },
  "WORD_SPACING_REL": {
    "raw_value": 1.1470588235294117,
    "unit": "xheight_ratio",
    "confidence": null,
    "n_observations": 4,
    "method_version": "accepted_box_gap_rel_v1",
    "quality_flag": "EXPERIMENTAL"
  }
}
```

`confidence: null` means **uncalibrated**, not zero confidence. Missing observations
have `raw_value: null`, `quality_flag: MISSING`, and a reason. Only decoded-input
metadata calculations currently have exact conditional confidence. No detector
confidence is manufactured from a sample count or aesthetic regularity.

## Implementation and evidence status

| Status | Meaning |
|---|---|
| DEFINED | Database feature exists, but no method is registered. |
| IMPLEMENTED | Executable method is registered; contract/numerical tests exist. |
| EXPERIMENTAL | Implemented estimate/index still lacks real-data accuracy calibration. |
| VALIDATED | Reserved for documented empirical validation; synthetic tests are insufficient. |

The four input-size metadata features are exact conditional on the decoded array.
Other core estimates are experimental; none are claimed empirically validated.
See [measurement methods](docs/measurement_methods.md) for formulas, denominators,
coordinate frames, minimum observations, sign conventions and known limitations.

No OCR, UI, personality interpretation, topology expansion or pretrained signature
weights are added here. The optional SigNet architecture and independently
implemented z-score/cosine/Euclidean/Mahalanobis utilities remain separate.

## Source decisions and scientific boundary

Preprocessing adapts NitinRamchandani/ocr-preprocessing-tool; word proposals adapt
githubharald/WordDetector. Titan's legacy thresholds are historical references,
not a trained personality classifier. JJ Shay is a comparison/statistical design
reference, not the source of production comparison mathematics. The selected
optional signature architecture is **luizgh/sigver**, without pretrained weights.
See [deployment provenance](schema/implementation_sources.json),
[source notes](provenance/SOURCES.md) and `THIRD_PARTY_NOTICES.md`.

Static darkness/thickness are image proxies, **not physical pen pressure**.
Traditional graphology interpretation remains separate and must not be represented
as validated psychological assessment. Passing a schema test proves interface
consistency, not handwriting-estimation accuracy or personality validity.

Breaking bootstrap change: do not rename old JSON fields and reuse their values.
Re-analyze source images; margins, CVs, thickness sampling and frames changed.
