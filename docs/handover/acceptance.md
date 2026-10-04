# Handover acceptance and verification record

**Status: receiving-maintainer acceptance pending.** Documentation implementation, automated checks, application qualification and public release are separate outcomes.

## Automated verification

The `Documentation handover` workflow checks internal documentation links, generated route/request/configuration/command inventories, explicitly registered source paths and package scripts, selected shell syntax, negative controls and roadmap drift. It does not execute arbitrary Markdown code fences, install provider SDKs, use protected credentials, reset an external database, make a model call or sign a native binary.

See [testing](../development/testing.md) for the ordinary application pipelines. The documentation PR's workflow records are the evidence for its exact head; the [post-#76 record](current-state.md) is retained earlier evidence, not a substitute. Record failures and repairs rather than editing a receipt to say PASS.

## Independent receiving-maintainer drill

| Step | Required observation | Status |
|---|---|---|
| Scope | Explain implemented versus qualified/enabled/pending capabilities without chat history | PENDING RECIPIENT |
| Fresh setup | Reproduce one documented supported host profile; record OS, architecture, runtimes and commit | PENDING RECIPIENT |
| Standalone APK | Download the merged-`main` `inktrospect-android-handoff-<sha>` artifact, verify `sha256sum -c` against its `.apk.sha256`, read `BUILDINFO.json`, check out exactly its `source_commit`, then `adb reverse tcp:8000 tcp:8000` and `adb install -r` on an emulator or USB device; confirm it launches without Metro | PENDING RECIPIENT |
| Free journey | With the local API/worker on host `127.0.0.1:8000`: synthetic capture → upload → saved report → reopen, on the installed handoff APK (and/or the dev client) | PENDING RECIPIENT |
| Evidence/export | Inspect report/evidence and authorized PDF, including retained/not-retained behavior | PENDING RECIPIENT |
| Failure recovery | Identify an interrupted operation and resume without inventing a new paid operation | PENDING RECIPIENT |
| Small change | Locate source, regenerate only intended outputs and run the owning checks | PENDING RECIPIENT |
| Operations | Explain completed versus outstanding counters, deletion versus erasure, and safe rollback | PENDING RECIPIENT |
| UX artifact | Verify `docs/design/artifacts/2026-10-04-v3/` with `sha256sum -c SHA256SUMS`, extract it outside the checkout and compare it with current source (not over it) | PENDING RECIPIENT |
| Assets/access | Confirm access/custody of any other approved design archives and accounts through private channels | PENDING OWNER/RECIPIENT |
| Remaining work | Locate identity/store/push/model/calibration gaps in existing tasks | PENDING RECIPIENT |

A Node/controller API journey is not a launched native UI test. The CI packaged emulator journey qualifies the handoff APK on one emulator; it does not replace the recipient's own drill. Native compilation is not a physical-device or store transaction test. A documentation reviewer may accept the documentation changes while these recipient/device steps remain open, but must not call the independent handover completed.

## Receipt fields

Record source SHA, date, executor and role, host/architecture, exact toolchain, commands and exit codes, synthetic fixture identities, approved safe artifacts, failures, repaired documentation and unresolved questions. Put private account/contract receipts outside Git. Do not include credentials, signed URLs or private samples in terminal transcripts.

External provider/store policies were not refreshed by this documentation rewrite. The existing dated research remains dated. Verify applicable current requirements when the owning integration or release work is actually performed.

## Safe scope of this documentation change

No feature activation, real charge, provider cleanup, database migration, new project license, participant recruitment, gate approval or task closure is implied. Runtime edits are limited to explanatory comments/docstrings and are checked separately from executable code.
