# Third-party notices

This repository contains or adapts the source work listed below. Follow [provenance/SOURCES.md](provenance/SOURCES.md) and the [retained license-text inventory](docs/reference/component-index.md#retained-license-text-candidates) to retrieve the actual records. This notice is not a newly selected license for the whole project; the owner must confirm project distribution/contribution terms during handover.

- NitinRamchandani/ocr-preprocessing-tool — MIT — Copyright (c) 2026 Nitin Ramchandani
- githubharald/WordDetector — MIT — Copyright (c) 2018 Harald Scheidl
- titanh3art/ml-graphology — MIT — Copyright (c) 2018 Malemnganba Mutum, Dorendro Leimapokpam, Ameer Humjah
- jjshay/handwriting-analysis — MIT — Copyright (c) 2025 John (JJ) Shay (reviewed; no substantial source copied into core statistics)
- luizgh/sigver — BSD-3-Clause — Copyright (c) 2019 Luiz Gustavo Hafemann

No pretrained SigNet weights are included. Model-weight and dataset licensing must be audited separately before commercial distribution.

## Separate rights categories

Code, datasets, pretrained weights, fonts, prototype assets and user specimens need separate rights decisions. A permissive code dependency does not clear its dataset or weights. No project-wide LICENSE is created by this documentation change. See [access and assets](docs/handover/access-and-assets.md) and [source-rights policy](docs/privacy/source-rights.md).

## Grid-aware preprocessing inspiration (grid-v1; source-mined, not vendored)

- fchaussin/signature-remove-bg (fork HMarcusWH/signature-remove-bg at 9cae24e922319d0a72bfbc609db7ccf31fecbd31) — MIT; studied horizontal/vertical morphology and line-presence test. The mining package retains the source license.
- itayinbarr/heb-ocr (fork HMarcusWH/heb-ocr at 19b7c158d14e9293e0806f909f1d497cc4784eaf) — MIT code; studied orientation and periodicity. No OCR models, trained weights or data copied.
- opencv/opencv (fork HMarcusWH/opencv at 1e21d6ed7d44c4f7ae9efd4acf302d6cbdf32bff) — Apache-2.0, dependency API only; no OpenCV source copied.
- KadenMc/PreprocessingHTR — MIT; inspected as an experimental Fourier baseline only.
- TheJaydenProject/doc-scanner-cv — license not found; consulted for test design only, no source or fixtures copied.

The grid-v1 implementation is newly authored deterministic NumPy/OpenCV code. Code, datasets, models and user specimens remain separate rights categories. No repository-wide license is implied.

## TLC/HAT design studies (no upstream code or assets imported)

- Dr. Hussein Mohammed, `Text-Lines-Counter-TLC` — studied only the general projection-profile, Gaussian smoothing and peak-selection concepts. Repository LICENSE refers to AGPL-3.0 while its project About text cites CC BY-NC 4.0; rights for code/asset reuse are **not cleared**.
- Dr. Hussein Mohammed, `Handwriting-Analysis-Tool-HAT` — studied FAST/SIFT keypoint and nearest-neighbor matching concepts only. The same AGPL-3.0 versus CC BY-NC 4.0 discrepancy applies. No upstream code, reference datasets, weights, UI, or reported similarity percentages have been copied.

The optional shadow detectors and offline descriptor experiment use independently authored NumPy/OpenCV API calls. Research-only provenance is not authorization to deploy a writer-identification feature, import licensed samples, or use learned models in the Free runtime.
