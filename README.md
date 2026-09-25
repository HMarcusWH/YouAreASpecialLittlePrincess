# YouAreASpecialLittlePrincess — Graphology Engine Bootstrap

Hybrid deterministic handwriting-analysis engine built from the strongest parts of the five selected upstream projects.

## Architecture

```text
image
  -> geometry / deskew
  -> binarization / denoise
  -> hybrid line + word segmentation
  -> deterministic measurements
  -> normalized feature record
       |-> free mechanics dashboard
       |-> comparison engine
       |-> traditional graphology rules
       `-> optional signature embedding
```

## v0.1 scope

- preprocessing, deskew, binarization and denoise
- line/word segmentation
- margins, ink coverage and region extraction
- baseline angle/variance/waviness proxy
- word/line spacing
- slant measurements
- ink-darkness and stroke-width proxies
- real z-score, cosine, Euclidean and Mahalanobis comparison math
- project feature schema target
- optional SigNet architecture; no pretrained weights

### Source decisions

- **NitinRamchandani/ocr-preprocessing-tool (MIT):** preprocessing foundation.
- **githubharald/WordDetector (MIT):** scale-space word proposals, modernized for NumPy 2.
- **titanh3art/ml-graphology (MIT):** traditional threshold provenance only; no SVM personality classifier.
- **jjshay/handwriting-analysis (MIT):** comparison concepts reviewed, but statistical/authenticity code is not imported.
- **luizgh/sigver (BSD-3-Clause):** optional SigNet architecture only. No pretrained weights are distributed.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Run:

```bash
princess-graphology path/to/handwriting.png --pretty
```

## Scientific boundary

Mechanical image measurements are computational outputs. Traditional graphology personality interpretations are not scientifically validated psychological assessment and remain a separate explicitly-labelled layer. Static images do not provide physical pen pressure; darkness and stroke width are proxies only.

See `THIRD_PARTY_NOTICES.md` and `provenance/SOURCES.md`.
