# Durable application workers

Entry processes: `analysis/run_worker.py` (deterministic analysis and erasure), `premium/run_worker.py` (bounded attempts and restored-attempt reconciliation), `export/run_worker.py` (authorized projection to bounded renderer output), `notifications/run_worker.py` (generic permitted mail/push delivery). Use each process's reviewed component manifest, worker role and required private storage.

See [lifecycles](../../docs/architecture/data-and-lifecycles.md), [local setup](../../docs/development/local-setup.md), [runtime images](../../infra/runtime/README.md) and [runbooks](../../docs/runbooks/README.md). Leases and fences reject stale publication. A worker restart is not permission to repeat ambiguous provider execution. Erasure events are dispatched only after required deletion verification. No production provider, notification channel or paid model is activated by starting a local fake-backed process.
