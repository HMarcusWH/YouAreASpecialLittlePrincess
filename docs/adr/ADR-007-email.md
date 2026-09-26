# ADR-007 — Transactional notification email

[Index](README.md) · [Mail connector](../connectors/email.md) · [Operations](../roadmap/18-observability-support-and-cost-control.md).

Status: IMPLEMENTATION_DEFAULT for outbox delivery; Resend or equivalent is CANDIDATE pending T24/provider decision.

Email is a notification of committed state, never the purchase/report source of truth. Separate identity-provider login/security email from app notifications. Use versioned templates, minimal safe variables, authenticated sender domain and durable delivery keys. Provider idempotency windows supplement rather than replace our outbox deduplication.

Selection compares region/retention, sender setup, delivery webhooks/signatures, suppression, limits, costs and replacement. No mail provider receives private handwriting or full Premium reports by default.

Acceptance: retry after remote acceptance, duplicate worker, bounce, suppressed recipient, stale/deleted account and provider outage without losing business state. Production gate requires approved sender, templates, recipient/privacy policy and support responsibility. Marketing is separate and disabled until explicitly scoped.
