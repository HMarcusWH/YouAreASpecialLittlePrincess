# ADR-009 — Layered admission and abuse controls

[Index](README.md) · [Abuse connector](../connectors/abuse-challenge.md) · [Security](../roadmap/17-security-privacy-and-abuse.md).

Status: IMPLEMENTATION_DEFAULT for quotas/risk layers; web challenge and native integrity configuration pending T04/T29.

Protect anonymous CPU/storage/export admission and paid verification/model budgets with independent quotas, concurrency limits and cost breakers. A web challenge such as Turnstile and native App Attest/Play Integrity can provide scoped risk signals. They are not identity, consent or financial proof and do not run inside the deterministic Free inference worker.

Choose fallback behavior for provider outage, unsupported device and uncertain integrity. Do not make an unavailable challenge either an unbounded bypass or universal permanent denial. Avoid unnecessary stable tracking identifiers and record provider data categories/retention.

Acceptance: replay/wrong-action/wrong-app token rejection, challenge unavailable under bounded load, cross-account access still denied after challenge success, quota races and cost limit enforcement. Production approval includes risk thresholds, privacy trade-offs and support recovery.
