# T06 residual ruling qualification — synthetic research only

**Source:** Main baseline `0c9470b0a0fdcb6ba3c45f17c6a1b94789e63b50` (merged PR #96). This is a research candidate for open [Issue #92](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/issues/92), **not** field-validated handwriting recognition or production release authorization.

## Implementation and provenance

- `evidence-support/2` is a versioned update to the existing opt-in guarded analysis. The flag `PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN=1` remains permitted **only** in explicitly paired and digest-pinned private local/test API + analysis-worker processes. Public guest, staging and production still reject it. Default guard-off processing hashes, outputs and the historical report writer are unchanged.
- A bounded independent retained-foreground audit counts (a) wide horizontal ink rows, (b) near-horizontal long Hough segments, and (c) page-width line boxes versus compact component support. It does not crop pages or alter pen/ruling pixels. The prior page-spanning, dominant-thin and low-resolution checks remain in front of the new checks to retain prior refusal reasons.
- Multiple suspect foreground bands cause **full conservative abstention even when a word detector admitted some groups**. Zero accepted word groups and zero accepted text lines are treated as unavailable evidence, not as proof a page contains no handwriting.
- The private `evidence_support_audit` records only versioned statuses, bounded counts and fixed reasons; it has no pixel arrays, boxes, source image paths, transcriptions, participant IDs, or raw detector payloads. Missing stages are JSON null, not fabricated zero.
- If abstaining, all 64 canonical features remain, with the four exact input-image facts still present and 60 unsupported handwriting-dependent facts `MISSING` with explicit reasons/null values. Suppress unsupported LINE/WORD/COMPONENT and baseline evidence; the existing `individual-report/3` projection and honest Premium eligibility behavior apply.
- The separately versioned guard digest prevents an old `evidence-support/1` job from silently executing under policy v2. Explicit version changes require API/worker startup pin updates; an unmodified default remains legacy.

## Synthetic regressions

`tests/residual_ruling_cases.py` synthesizes grey/blue/dark paper ruling, page/table backgrounds, perspective, near-edge strokes, and ground-truth masks/page polygon/word-group boxes. These are OpenCV-generated shapes, not human handwriting or benchmark ground truth for people.

Run the focused suite:

```sh
python -m pytest -q tests/test_residual_ruling_guard_v2.py tests/test_evidence_support_guard.py tests/test_qualified_segmentation_v2.py
python -m pytest -q
ruff check src tests tools
python tools/documentation.py --check
```

Checks cover deliberately fooled accepted-word candidates with retained ruling, angle tolerance, bounded stage diagnostics, no false factual zero, full evidence withholding, and an explicit *positive* accepted synthetic handwritten-like case. A pipeline quality refusal remains a refusal and never silently drops from accuracy denominators.

## Gates that are NOT closed

- T06 remains **PLANNED** and T11 pilot consent/rights authorization remains **IN_PROGRESS/PENDING**. No human photo is uploaded to CI or published.
- Do **not** close Issue #92 based on synthetic results. Exact authorized original-photo reproduction with SHA and coordinate lineage, protected annotated writer-disjoint development/validation/holdout, independent agreement analysis, preregistered nonempty/empty acceptance thresholds, comparison against legacy/grid-v1/qualified-v2, resource budgets and real physical Android handset proof are still required.
- The synthetic evaluator's own `ENGINEERING_PASS` or this guard's no-abstention status is not a scientific accuracy certificate, permission to process a real source, or a hardware attestation.
- Rollback is to keep the research opt-in disabled. Existing saved report/feature identities and offline exports are never rewritten.

**Review disposition:** Do not merge before exact-head Python 3.10–3.12, app/backend/native/release/docs/roadmap CI, independent correctness/security review, and synthetic evidence inspection. Merging does not turn this on publicly.
