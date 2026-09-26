# ADR-008 — Vendor-neutral operations and explicit analytics

[Index](README.md) · [Telemetry](../connectors/telemetry.md) · [Analytics](../connectors/analytics.md) · [Operations](../roadmap/18-observability-support-and-cost-control.md).

Status: IMPLEMENTATION_DEFAULT for OTel-compatible traces/metrics and redacted structured logs; export/analytics vendors pending.

Keep domain code independent of telemetry vendors. Use bounded attributes and privacy-safe exception mapping. Product analytics uses an allowlisted event contract with its own purpose/consent/retention. Financial and deletion audit requiring durability remains a separate restricted store. Default report session replay/autocapture is off.

Evaluate exporter stability, sampling, SDK side effects, retention/region, access, alert routing and costs. An analytics product is not a reason to send exact feature vectors or screenshots. Disabled analytics must not degrade Free or paid report access.

Acceptance: redaction tests on success/error/native crash paths, exporter outage/backpressure, event-schema rejection and actual alert/runbook exercises. T28 builds seams; T24 names owners and validates operations. No provider approval or service-level guarantee is inferred from installing an SDK.
