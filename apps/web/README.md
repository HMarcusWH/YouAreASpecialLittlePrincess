# Web client (T17, Free journey)

Next.js 16 / React 19, presentation only (ADR-001). The FastAPI service owns authorization, consent, jobs, the ledger and reports; this app never talks to the database, a payment provider or a model.

- **Session**: `app/api/session/*` keeps the API credential (guest capability or, in local/test, a fake-provider ID token) in an HttpOnly, SameSite=Lax cookie. Client code never sees it.
- **Proxy**: `app/api/v1/[...path]` forwards only allowlisted routes to `PRINCESS_API_BASE`, attaches the credential server-side and rejects cross-origin mutations. The signed local upload PUT is forwarded only in local and test.
- **Validation**: payloads go through `@princess/api-client` runtime guards (`parseReportView`, `parseRunStatus`) before rendering. They are never cast into contract types.
- **Rendering**: `@princess/report-web` renders the saved `ReportViewModel` only: no computed percentiles, no model text, and "not measured" instead of zero. Colours and spacing come from `@princess/design-tokens`.
- **Pages**: `/start` (consent → upload → verify → permission → analysis), `/analyses/[runId]` (bounded polling that resumes the known run on refresh), `/reports/[reportId]`, `/settings` (account report-ready mail preference, sign out, sign out everywhere, delete account) and `/fixtures/[name]` (synthetic view fixtures, only with `PRINCESS_WEB_FIXTURES=1`).

Local run against the local API (see `infra/README.md` for the API and worker):

```bash
PRINCESS_API_BASE=http://127.0.0.1:8000 PRINCESS_ENVIRONMENT=local pnpm --filter @princess/web dev
# The API must issue upload URLs through this origin:
#   PRINCESS_PUBLIC_API_BASE=http://localhost:3000/api
```

Tests:

```bash
pnpm --filter @princess/web build && pnpm --filter @princess/web e2e   # fixture journeys (CI)
PYTHON=.venv/bin/python tools/run_web_e2e.sh                          # live journey on PostgreSQL
```

In a sandbox with a pre-installed browser, set `PRINCESS_CHROMIUM` to its executable instead of running `playwright install`.

PDF export is implemented through T21 and the renderer can also produce scoped share-card PNGs from authorized SHARE projections. The Free web product now includes current-principal saved-report history, stored baseline/spacing/slant evidence views, account report-ready mail preferences, and automated axe WCAG A/AA journey coverage. Not yet included: production account sign-in/cross-device recovery (waiting on ADR-002), Premium/paid states (T20), and share-link/invitation UI (T22).
