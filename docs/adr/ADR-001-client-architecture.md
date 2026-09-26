# ADR-001 — Web presentation and business authority

[Index](README.md) · [Web specification](../roadmap/10-web-client-and-api-integration.md) · [Module boundaries](../roadmap/09-connectors-and-provider-boundaries.md).

Status: IMPLEMENTATION_DEFAULT; exact versions/hosting selected and tested in T28/T17.

Use Next.js/React/TypeScript for web presentation, landing/share metadata and a thin secure-session boundary. Use FastAPI for all business authorization, job/ledger transitions and report assembly. Shared JSON Schema DTOs generate Python/TypeScript representations and API clients. Native clients consume that same API directly with the approved identity transport.

Considered: a static SPA with all behavior in FastAPI (simpler hosting but less server/session/share flexibility); a full Next backend (would split numerical/application authority); universal web/native UI components (risks confusing DOM/print with native accessibility). The default keeps server presentation flexibility without duplicating the domain.

Acceptance: no provider/SQL business logic in Next route handlers, no hidden paid fields in client JSON, secure cookie/CSRF/cache behavior, generated-client drift tests, same-fact web/native/print fixtures. A move to static hosting or a different frontend framework requires a scoped ADR with auth/deep-link/share/export impact. Existing engine packaging must remain unaffected.
