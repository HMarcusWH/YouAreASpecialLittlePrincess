# R5-F3 — private v3 export job, cache, revocation and client choices

**Status:** Stacked engineering candidate, **NOT RELEASED**. R5-F1 PR #131 → R5-F2 PR #132 → this R5-F3 PR. No activation in staging, preview, production, paid commerce, or public guest-only test. Existing v2 PDF/card exports stay the default and preserve their cache/rows/URLs.

**Referenced current handoff:** October 24–25 report Build Spec §9; R5 Free EX.04–EX.11; current generated `RenderEnvelope` and accepted Dossier design. The existing PostgreSQL `app.report_export.params` JSONB and `template_version` column are reused—no migration or schema mutation.

## Request and persistence identity

`POST /v1/report-exports` retains the old body shape and behavior when **both** `detail` and `include_image` are omitted. That continues `render-template/2`, the exact historical `params` object and stable `cache_key`; old PDF/card render/retrieval code and historical rows survive.

Explicit `detail=SUMMARY|FULL` and/or `include_image: boolean` requests `render-template/3` **only** if the service is configured with `PRINCESS_RENDER_V3_RESEARCH_OPT_IN=1` in `PRINCESS_ENV=local|test`, outside `PRINCESS_TEST_PUBLIC_GUEST_ONLY=1`. Missing detail then selects `SUMMARY`, missing include_image selects false. Current private v3 is restricted to A4/Letter Free documents; existing share cards remain v2 and source-free. It refuses malformed, stringified or unknown flags and cannot silently fall back to v2 when disabled.

The service persists renderer/template identity, detail, include-image flag, source-report document digest, exact selected cleaned-image SHA (nullable), exact saved evidence digest (nullable), **image-retention permission epoch (nullable)**, font-policy pin and render-policy pin. These values are reconstructed/checked when dequeued and on every file request; the v3 cache hashes the saved authorized report view (excluding generation time), source report/revision/asset disclosure, presentation/locale/layout/detail, versioned renderer/font/policy, evidence digest and cleaned image SHA/size. It does not hash private base64 into the cache key, and never treats report ID or a prior permission state alone as authorization. Historical v2 cache algorithm unchanged.

## Runtime/access fences

1. **Request:** The authoritative `ReportReader` resolves the latest saved revision and current source rights, checks exact evidence lineage, and (if include_image=true) the owner-scoped retained original, **current per-specimen image_retention permission**, trusted source asset SHA/size, decoded pixel digest/EXIF frame and cleaned raster. No URL can be supplied by a client. A versioned row is only queued for that exact candidate digest.
2. **Render:** The worker reconstructs the exact persisted request and source pins. It rejects changes in current evidence, report revision, current image retention and asset contents before invoking the v3-only subprocess. After producing bounded PDF/PNG bytes and writing the derivative, it independently reconstructs that current envelope again. A failure/revocation makes the job FAILED (or bounded retry for transient provider errors) and queues erasure of orphan derivative bytes. The subprocess still gets no model/DB/object-store/session secrets.
3. **Publish:** Within the fenced PostgreSQL lease transaction, it locks the current report, refuses any newer saved revision or different document digest; when source was included, revalidates a live owner-matched ORIGINAL asset and non-deleted capture bound to the saved source SHA. Only then can a READY export refer to the derivative.
4. **Download:** Each v3 file GET reconstructs the current authorized envelope before reading the cached bytes, hashes those bytes, and reconstructs the envelope again after the read; any stale/revoked source refuses output, atomically marks the export REVOKED and queues asset erasure. Already downloaded external copies **cannot be recalled**.

## Client boundary

Web and native accept explicit Summary/Full and opt-in source image only in private test UX; the default remains no source. The web server must opt in explicitly in a local/test backend and not a public guest-only preview. The native app requires `INKTROSPECT_RENDER_V3_PRIVATE=1` *at build time* on a local/test development build with the development identity path; staged, store and remote guest binaries refuse the setting before any network call. Both depend on independently matching private API/export-worker configuration and cannot enable server v3 just by changing a client toggle. The shared API client supports versioned request/status semantics while omitted options retain old bytes.

## Acceptance and operational follow-up

Run the exact-head locked Python 3.10/3.11/3.12 core suites, real disposable-PostgreSQL `tests_app/test_exports_v3.py`, browser/client/native tests, offline Chromium renderer tests, full application environments, roadmap/docs, and native foundation. Specifically assert source grants revoked mid-render and **during stored-file retrieval**, old cache parity, v3 distinct full/summary/source caches, surviving historical rows, source proof/geometry, no credential leakage, no paid content, and no mutation of report/evidence. Preview visual PDF/screen artifacts and physical-device acceptance remain separate owner gates; synthetic passing CI is not a real-person permission/accuracy claim.

**Rollback:** disable the private opt-in on API and export worker; historical v2 queue/rows remain routable through their original template version. Do not delete v3 rows without their asset/tombstone records. Keep T21 `IMPLEMENTED_PENDING_REVIEW`, T17 and Issue #92 open, and never call R5-F3 a public release merely because the code merged.
