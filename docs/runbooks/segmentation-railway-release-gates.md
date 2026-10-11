# Segmentation release and Railway guest APK qualification

**Scope:** isolated Inktrospect guest-test environment, never production or a general user upload service.

## Immutable identity chain

1. Review and pin the intended `feat/grid-aware-preprocessing-v1` commit SHA.
2. Verify all exact-head CI (Python 3.10/3.11/3.12, release contracts, topology, native) and reviewer comments.
3. Review and separately authorize the specimen corpus in the source-rights register. Do not send or commit private original handwriting to public CI. Existing guest-test consent permits **synthetic only**.
4. Run the v2 segmentation benchmark in an approved local evaluation environment. Explicitly choose `annotation_frame: original_image` for source-photo coordinates; use the transform in `prepare_context` and report current vs shadow metrics separately.
5. Predeclare the acceptance policy and freeze a writer-disjoint holdout split **before** inspecting results. Require no unexpected loss of ink at grid intersections, safe handling of ambiguous paper, no regression in line/word geometry and improved false-zero word results if activating any new algorithm.
6. Keep TLC-inspired and whitespace-word grouping in shadow mode until there is sufficient rights-cleared real evidence. Changing authoritative algorithms requires a new versioned segmentation profile and analysis-config fingerprint; never quietly modify the canonical 272-feature semantics.
7. Deploy only the reviewed commit to Railway's dedicated `test` environment. Inspect the active deployment commit in Railway, not just the source branch. Ensure API/worker/postgres readiness, bounded memory, permissions, synthetic guest admission and no active deploy failures.
8. The read-only API `GET /health/build` must provide `source_commit_sha` from Railway's `RAILWAY_GIT_COMMIT_SHA`. If the deployment does not inject it, the endpoint returns 503: **investigate the integration rather than synthesizing a commit hash**.
9. Set GitHub Actions repository variable `REVIEWED_RAILWAY_BACKEND_SHA` to the exact active, independently reviewed Railway deployment commit SHA. This is an operator assertion that the APK workflow checks against the Railway-provided value.
10. Run the `Inktrospect Railway guest-test APK` workflow on the reviewed client branch. Success must include checked backend SHA, `analysis_config_sha256` from the saved evidence, generated product `contract_bundle_sha256`, synthetic upload/worker/report/evidence journey, Android build, package/signature verification and a SHA-256 integrity record.
11. Preserve the APK artifact's `.source-sha` (client source revision) and `.apk.sha256` next to the APK. Inspect the Android installed build and source-image line/word overlays on device. Build success without installation is **not** end-to-end device qualification.
12. Roll back to the exact previously healthy Railway deployment and its matching worker/configuration. Old queued jobs and old reports must not be remapped to a new pipeline or silently compared across incompatible method/config versions.

## Historical Railway failures (2026-10-10)

- Deployments `26af7930-2aeb-44bc-b281-29468de08aa8` and `952d878d-df78-4d69-a54f-a566d75ad4a4` launched Uvicorn but failed Railway's `/health/ready` check. Determine whether that was an incorrect healthcheck route/port, readiness dependency or initialization race before changing timeouts; logs alone do **not** prove which.
- Deployment `086939f0-852b-4acc-b4ae-a648b46f4245` also failed readiness and its worker logs contained `MemoryError`. Check Railway service memory limits, worker startup peak and duplicate process loading in the supervisor. Do not assume it was a segmentation algorithm regression.
- The later deployment `8ff5ebaa-4c42-4629-b5ae-f3a2adb4eef8` was healthy on old commit `eee883ce`. A healthy historical deployment does not validate future code or the new provenance endpoint.

## Release blockers and explicit deferrals

- Without rights-cleared, annotated real handwriting, do **not** claim empirical line/word accuracy or enable shadow detector output as authoritative Free measurements.
- Without exact deployed source SHA and contract compatibility, do **not** claim the guest APK was tested against the reviewed backend.
- Without a retained APK artifact and physical device result, do **not** claim installed Android validation.
- Without a resolved TLC/HAT license decision, do **not** copy their source/assets or introduce an identity-classification product feature.

Track those as three distinct gates: algorithm qualification, backend/client provenance, and physical device QA. Green synthetic CI is necessary but not a substitute.
