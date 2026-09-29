# T21 Dossier render inspection

**Status:** `PASS_CODE_HEAD_REVIEWED`

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
| A4 EN: no clipped/overlapped content or blank pages | PASS |
| A4 SV: long labels/captions remain readable | PASS |
| Letter EN: no clipped/overlapped content or blank pages | PASS |
| Letter SV: long labels/captions remain readable | PASS |
| First Reveal hierarchy reads before mechanical sections | PASS |
| Colophon/methodology remains readable and in logical order | PASS |
| Tagged PDF / one logical H1 / heading order machine checks | PASS |
| Square EN/SV: all disclosed content stays inside canvas | PASS |
| Story EN/SV: all disclosed content stays inside canvas | PASS |
| Cards contain no source image, name, signature or private transcription | PASS |
| Evidence class / calibration wording remains visible | PASS |
| No percentile, rarity, confidence-percentage or physical-pressure upgrade | PASS |

## Exact-head disposition

- Reviewed renderer code head: `b9ba872b3c3fabf298648afe6b5d88fc9c7d87f1`
- Application environments run: `36572933558` (PASS)
- Artifact ID/name: `11036491530` / `t21-render-inspection-874f6681fef936733a89244de2af87ccddf2d429`
- Artifact ZIP SHA-256: `c2614195fabba0a4fec8dffb4f2baa6fc96d146631d5a8b734ccd421b76a65fa`\n- Manifest SHA-256: `43d69a090adfce3da5e6cc8c223d695dfd8d288e13d91b3823d31bffd42f1624`
- Reviewer: assistant visual review of rendered synthetic artifacts in PR #34
- Reviewed at: 2026-09-29
- Overall disposition: PASS for the T21-specific v2 Dossier print/share review

Visual inspection covered all four PDFs and all four cards in the artifact bundle. The PDFs were rendered to PNG for page-by-page review; A4 EN has 6 pages, A4 SV 7, Letter EN 7 and Letter SV 7. Page sizes, embedded Unicode fonts and document outlines were independently inspected. No clipped text, overlapping elements, blank pages, broken Swedish glyphs or black-square glyph failures were observed. The First Reveal precedes the mechanical sections and the methodology/recall limitation remains readable at the end. Square/story cards stay inside the fixed canvas and contain no handwriting image.

T18/T20 remain responsible for adding their own comparison/history/Premium export-parity fixtures before those owning tasks claim parity. T21 does not synthesize absent content.

The PR may contain later documentation-only commits. Those heads must still pass the retained exact-head workflows before merge; a documentation-only head does not invalidate the reviewed renderer bytes, but its workflow disposition is recorded separately on PR #34.
