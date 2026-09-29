# T21 Dossier render inspection

**Status:** `PENDING_EXACT_HEAD_ARTIFACT_REVIEW`

This record closes only when the full-size synthetic artifacts produced by the retained Application environments workflow have been inspected on the exact PR head. A generated PDF/PNG or a passing unit test is not, by itself, visual inspection evidence.

## Bound implementation

- Report source: generated `individual-report/2` synthetic fixtures under `fixtures/reports/`.
- Renderer authority: `render-template/2`.
- Renderer: `apps/render`, offline Chromium, JavaScript disabled, network aborted.
- Formats: A4, Letter, 1080×1080 square card, 1080×1920 story card.
- Locales: English and Swedish.
- Source image: omitted from the reviewed EXPORT/SHARE projections.
- Population-relative claims: none.

## CI artifact contract

The retained web job generates and uploads `t21-render-inspection-<commit>` containing:

- `dossier-a4-en.pdf`
- `dossier-a4-sv.pdf`
- `dossier-letter-en.pdf`
- `dossier-letter-sv.pdf`
- `share-square-en.png`
- `share-square-sv.png`
- `share-story-en.png`
- `share-story-sv.png`
- `manifest.json`

The manifest binds each artifact to the source fixture/report revision, report template, renderer template, locale, layout, byte size and SHA-256, plus PDF page count or PNG dimensions.

## Machine qualification

Before visual disposition, the exact head must pass:

- canonical Python CI;
- roadmap integrity;
- backend/PostgreSQL export tests;
- web/package tests;
- production web build;
- fixture/accessibility browser journeys;
- real Free upload → report → export journey;
- T21 print geometry / heading / reading-order tests;
- T21 fixed-card canvas tests;
- renderer no-network/security tests.

## Full-size inspection checklist

Record PASS/FAIL for every item after downloading the exact-head artifact bundle:

| Check | Disposition |
|---|---|
| A4 EN: no clipped/overlapped content or blank pages | PENDING |
| A4 SV: long labels/captions remain readable | PENDING |
| Letter EN: no clipped/overlapped content or blank pages | PENDING |
| Letter SV: long labels/captions remain readable | PENDING |
| First Reveal hierarchy reads before mechanical sections | PENDING |
| Colophon/methodology remains readable and in logical order | PENDING |
| Tagged PDF / one logical H1 / heading order machine checks | PENDING |
| Square EN/SV: all disclosed content stays inside canvas | PENDING |
| Story EN/SV: all disclosed content stays inside canvas | PENDING |
| Cards contain no source image, name, signature or private transcription | PENDING |
| Evidence class / calibration wording remains visible | PENDING |
| No percentile, rarity, confidence-percentage or physical-pressure upgrade | PENDING |

## Exact-head disposition

- Commit: PENDING
- Application environments run: PENDING
- Artifact ID/name: PENDING
- Manifest SHA-256: PENDING
- Reviewer: PENDING
- Reviewed at: PENDING
- Overall disposition: PENDING

T18/T20 remain responsible for adding their own comparison/history/Premium export-parity fixtures before those owning tasks claim parity. T21 does not synthesize absent content.
