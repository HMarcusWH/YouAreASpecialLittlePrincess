# R5-F1 — Private Free RenderEnvelope authority (T21)

**Status:** Implementation slice for a future v3 renderer. **Not activated** on the public API, export worker, print/share UI, Railway, or native clients. It is not a public v3 export release or a replacement for the existing v2 render path.

**Base reviewed:** `main` `4f2f1338fb4517debec635f163ad71ff81775549` (2026-10-29).  
**Sources:** October 24–25 Free/Premium report build spec §9, master TODO EX.01–EX.03, existing generated `RenderEnvelope` + `RenderEnvelopeSourceImage` schemas and current code/ports.

## Implemented exact contract

- `application/exports/assets.py::prepare_authorized_render_assets` receives only a **server-resolved** `StoredObject`, already validated `ReportDocument`, exact authorized `ReportViewModel`, saved `EvidenceBundle`, live owner-specific access resolver, and storage port. It does not fetch URLs or accept user-provided crops/paths. It checks the stored report's current owner separately from immutable analysis owner (guest transfer is possible).
- The checked view must be a currently authorized `EXPORT` projection for the same report/revision/digest, list the input asset in `authorized_asset_ids`, and match the original `StoredObject.asset_id` and `sha256` in the saved analysis. The evidence bundle ID and *entire saved analysis reference* must match, its fact region references must exist, and its input coordinate-frame width/height must match the EXIF-oriented verified source pixels.
- Image access is rechecked **before and after** the storage read and image preparation. The stored bytes' exact SHA and size are checked before decode. The installed bounded imaging adapter rejects unsupported format, animated data, excessive dimensions, invalid EXIF and compressed pixel bombs before allocation. The source is EXIF-oriented, scaled without cropping to <=1600 px each axis and re-encoded deterministically to PNG or JPEG **without source metadata**. Fail closed if no quality level can fit <=2 MiB.
- An immutable internal `PreparedRaster` binds cleaned bytes *and* the exact original asset SHA, source asset ID, saved report digest/revision, and evidence digest. Only the cleaned image fields are serialized. The base64 transport is strict and canonical, with <=43 chunks of <=65,536 characters, <=2,796,204 total characters, final-chunk-only padding, verified cleaned-image SHA and exact decoded format/dimensions.
- `compile_free_render_envelope` accepts `SUMMARY|FULL` and A4/Letter or existing card layout names but no paid content. It requires a validated, immutable view, matching saved evidence, correct projection type and source provenance. SHARE candidates intentionally cannot include raw handwriting or a full evidence bundle without a separately scoped sharing/redaction authority (R5-F3). Only schema-specified properties are forwarded; output is bound to `render-template/3`, `render-policy/3`, exact locale/generation clock and `presentation/1|2` according to the saved writer, with <=8 MiB canonical UTF-8 input. No new model calls occur.
- The **private** `ExportService.private_free_v3_candidate` method resolves the owner's latest saved snapshot and evidence, checks the stored evidence lineage via `ReportReader.evidence`, derives a fresh `EXPORT` projection, and invokes raster preparation only after an explicitly injected trusted capture lookup and valid request context. The ordinary `ExportService.request`, cache_key, Postgres adapter, export worker, existing HTTP export API, web renderer and native export controller are not modified. Old callers still use `render-template/2`, FULL and no image.

## Important limitations

This slice does **not** authorize a source merely because the raster was once valid: the R5-F2/F3 worker must re-resolve exact current permission, capture, evidence and report revision **before render and publication**, recompute the digest-pinned cache identity with disclosure/grant scope, and reauthorize again at download. Source-byte revocation during render must fence output. Do not route the new envelope to the existing renderer v2 parser or persist it under a legacy v2 cache key.

Only the private candidate assembly seam is installed. Production source-capture resolution, v3 CLI/Chromium integration, presentation details, request/default compatibility, JSONB versioned params, private PDF previews and device/web controls remain separately owned R5-F2/R5-F3. This is also not field validation of Issue #92, T11 human data rights, Premium v2 approval or permission to introduce provider credentials into the renderer.

## Regression witnesses

`tests/test_render_envelope_authority.py` covers: generated real-engine report/evidence matching, authorized raster and proof preparation, strict chunk/hash bounds, EXIF orientation and synthetic metadata removal, source absent with facts still readable, foreign-owner/source/digest and revocation refusal, mismatch of report revision/bundle/source, source-free projections unable to disclose pixels, and the independently inactive v2 legacy path.

Run on the exact PR head in supported lock-pinned Python 3.10/3.11/3.12 and backend application workflows:

```sh
python -m pytest -q tests/test_render_envelope_authority.py
python -m pytest -q
ruff check src tests tools
python tools/generate_product_contracts.py --check
python tools/documentation.py --check
python docs/roadmap/plan_tools.py --check
```

A green synthetic CI is *not* a source-rights or production authorization. T21 remains `IMPLEMENTED_PENDING_REVIEW` until its T17 dependency/owner gates are satisfied. Rollback is this self-contained module, candidate method and tests; no migration, queued-job schema, stored digest or public behavior changes.
