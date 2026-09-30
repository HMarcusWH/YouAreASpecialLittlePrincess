# TelemetryExporter — safe operational evidence

[Index](README.md) · [T28](../roadmap/06-agent-backlog.md#t28) · [T24](../roadmap/06-agent-backlog.md#t24) · [Operations](../roadmap/18-observability-support-and-cost-control.md) · [ADR-008](../adr/ADR-008-observability.md).

Instrument application ports/use cases with OpenTelemetry-compatible traces/metrics and redacted structured logs. Export destinations are composition/configuration choices, not domain dependencies. Use stable low-cardinality names, bounded attributes and correlation IDs. Keep operational, financial audit and optional product analytics data separate.

Allow environment, service/version, operation class, safe outcome, latency, queue age, attempt count, resource usage and approved provider usage/cost totals. Remove authorization/cookie headers, signed URLs, raw requests/responses, handwriting content, prompt packets, private vectors and native screenshot breadcrumbs. Automatic HTTP/DB instrumentation needs explicit sanitization and cardinality tests.

The exporter has bounded buffering, backpressure/drop policy and failure handling. Telemetry outage must not block a ledger commit, deletion or Free report. Do not retry logs forever or fill disk with private payloads. Restricted audit events needing durability use their own database/outbox contract, not best-effort telemetry.

Fakes capture only approved fields and simulate exporter outage/full buffer. Tests include redaction at exception paths, provider error payloads, URL query strings, native breadcrumbs and user-controlled metric labels. T24 supplies dashboard/alert owners and retention/access approval; T28 only supplies seams and development defaults. Source E28 in [22](../roadmap/22-research-and-source-refresh.md).


## T24 operational posture mapping

`operational-snapshot/1` is mapped provider-neutrally through this port before
any dashboard vendor is selected. The mapper consumes only the fixed
`OperationalSnapshot` / reviewed `OperationalAlert` values and uses the
existing bounded attributes (`environment`, `operation`, `outcome`,
`error_code`); it does not add a generic arbitrary-label surface.

Every reviewed operational dimension emits a count gauge, including zero for an
empty/missing database aggregate. Age/attempt gauges are emitted only when
meaningful; capability and fired-alert records use fixed reviewed names/codes.
The application mapper imports no adapter, SQL or provider SDK. The operator
composition currently supports the fake exporter only; sandbox/live exporters,
routing, retention and production thresholds remain ADR-008/T24 deployment
decisions.
