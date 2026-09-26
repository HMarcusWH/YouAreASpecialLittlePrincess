# AnalyticsSink — explicit product events only

[Index](README.md) · [T17](../roadmap/06-agent-backlog.md#t17) · [Operations](../roadmap/18-observability-support-and-cost-control.md) · [Privacy](../roadmap/17-security-privacy-and-abuse.md).

`capture(event_name, safe_properties, consent_context, dedupe_key)` accepts only a versioned allowlist. Do not expose a generic arbitrary-object logging port to report components. Default sink may be disabled or a controlled internal event table; a vendor is selected separately in ADR-008.

Allowed event families describe workflow transitions: upload accepted, analysis completed, report opened, offer displayed, checkout started, purchase verified, Premium published, export created, share dialog opened, invitation redeemed and deletion completed. Properties are bounded enums/counts/buckets such as platform, report kind, outcome, available-feature count and latency bucket. Do not include exact handwriting metrics, raw vectors, text, names, private URLs, report screenshots, prompt content or payment proof.

Separate optional analytics consent from service processing and payments. Do not enable blanket autocapture/session replay on capture/report/payment pages. A delivery failure must not block analysis, a purchase grant or deletion. Handle events after logout/deletion according to the approved purpose and retention policy; use minimal pseudonymous identifiers only where justified.

Tests reject unknown event names/properties, private-value injection, oversized payloads and sending when disabled/consent-denied. Distinguish share initiation, artifact export, link redemption and referred completed analysis; no success callback becomes invented virality. Provider adapter testing validates SDK side effects and network behavior, not merely our payload schema.
