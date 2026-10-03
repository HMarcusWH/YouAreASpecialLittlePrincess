# Offline report renderer

This Node/Chromium child receives an authorized saved projection through stdin under the export-worker boundary; it owns layout, not authorization, private SQL, storage credentials or inference. Use `pnpm --filter @princess/render run build`; install the workspace's pinned Chromium for source-tree tests or use the qualified export-runtime image. `pnpm --filter @princess/render inspect:artifacts` generates synthetic review outputs, not a public user export.

Read [setup](../../docs/development/local-setup.md), [testing](../../docs/development/testing.md), [runtime packaging](../../infra/runtime/README.md) and [accepted design](../../docs/design/ACCEPTED_DOSSIER_REFERENCE.md). A PDF/export must use the same authorized saved facts; changing a template does not authorize missing Premium or partner scope. Downloads need authenticated transport, and externally saved copies cannot be recalled.
