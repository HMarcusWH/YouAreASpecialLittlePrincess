# R5-F2 — isolated render-template/3 Free renderer

**Scope:** PDF and existing redacted share-card render from the strictly validated `RenderEnvelope` prepared by R5-F1. Private, explicit child entrypoint only. **Not** public export admission/queue/cache activation (R5-F3), Premium-v2 publication, calibration signoff or device release.

**Stacking:** this PR targets the R5-F1 branch `task/T21-r5-f1-render-source-authority`; review F1 separately and merge it first. Merge/rebase this PR onto main only when F1 is accepted. Never allow a new v3 PDF to share the legacy v2 cache identity.

## V3 transport

- Existing `node dist/render.mjs` and `SubprocessRenderer.render` keep the old 2 MiB v2 `{view,layout,locale,generated_at}` wire format, offline browser and output. V3 requires the **explicit** `--envelope-v3` CLI arg or `SubprocessRenderer.render_envelope_v3(ValidatedDocument)`. The old mode refuses the v3 discriminator so source-image requests cannot silently lose the image.
- V3 accepts at most **8 MiB UTF-8** (strict stream limit and parse limit), exact reviewed `RenderEnvelope` field names, `render-template/3`, `render-policy/3`, contract version 1.0.0, `presentation/1|2`, `SUMMARY|FULL`, A4/Letter/square/story and en/sv presentation locale.
- V3 calls the established API-client guards for `ReportViewModel` and `EvidenceBundle`. The view clock, display locale, projection type and Premium scope must agree with the envelope. `premium` remains null; R5-P must introduce a separate qualified reader, never reuse this Free path for paid content.
- A rendered source image must have a current authorized input asset in the already supplied projection, a saved evidence bundle with the matching original `frame_input` root, no missing fact-to-evidence region refs, and a valid uniform source downscale. The parser reconstructs raster bytes from **canonical** base64 chunks (<=43 x <=65536, total <=2,796,204), checks SHA-256, PNG/JPEG container dimensions and <=2 MiB decoded input. The only image URI is a renderer-generated `data:image/png|jpeg;base64,...`, never an external URL, path, SVG, iframe or arbitrary caller-provided data URI.
- V3 CSP defaults to no resources; only when a verified raster is present does it allow `img-src data:`. Chromium remains JavaScript-disabled, offline, all network routes aborted and without DB/storage/model/secrets. Output remains <=10 MiB and subprocess timeout unchanged. Subprocess stderr is reduced to known short error codes.

## Free print composition

- `packages/report-web/src/Print.tsx` adds `summaryView` and an optional `PrintSourceEvidence` presentation. Summary selects only authorized first-reveal, sample, chapter and supported connection sections, with at most two saved facts per section and no recalculation. Existing saved facts, quality/limitation labels, stable feature IDs and source-region references are untouched.
- FULL retains all authorized source facts/method IDs, notices, the technical appendix and saved evidence observations. No model is called on render/reopen. PDF source evidence is generated only from an explicitly supplied verified raster and saved measured/proxy fact regions mapped to `frame_input` using the existing matrix mapping. No PAGE/false baseline outlines or invented geometry. A display cap of 24 regions is explicit.
- Layout uses the already accepted Inktrospect paper/ink/red-pencil tokens and separate EN/SV print labels. No new font files, percentile/rank claims, invented handwriting or user HTML. A4 and Letter tagged PDFs and redacted square/story card output keep the same existing print/screenshot limits. SUMMARY page count is a target, not a reason to truncate headings or pad pages.

## Tests and acceptance

- `apps/render/test/render-v3.test.ts` generates **synthetic PNGs in memory** and checks explicit v3 mode, old v2 compatibility, SUMMARY vs FULL authorized fact density, EN/SV tags, saved-source SVG overlay, JPEG/PNG integrity gates, bad hashes, forbidden remote/unknown fields, orphaned/mismatched frames, no paid scope and successful A4/Letter PDF rendering including a checked real embedded raster.
- `tests/test_render_subprocess_v3.py` verifies the Python adapter only passes a compiled `RenderEnvelope` to the explicitly selected child, with an environment limited to PATH/HOME/qualified Chromium and no source/purchase/model credentials. It verifies failure/timeout/output-size handling and rejects raw unvalidated dictionaries.
- Run exact-head JS typecheck/render tests, browser/print inspections, Python 3.10–3.12 and application/roadmap/renderer build checks. Manual PDF/PNG visual inspection is a **separate acceptance**, not inferred from unit tests.

## Next and rollback

**R5-F3:** Add exact versioned export job params, v3 cache, source disclosure controls and live access/region/lease rechecks at request, render publish and file retrieval. Wire actual web/native UI choices with legacy omitted defaults. Never publish source-enabled bytes on a v2 cache key. Revoke/erase a v3 artifact if access, report revision, source image, evidence, grant or the current entitlement changes.

Rollback: remove the explicit v3 CLI, renderer helper, optional print props and tests; leave historical `render-template/2` users/artifacts untouched. The Free source authority remains gated on separate F1 acceptance. T21 remains pending its T17 prerequisite.
