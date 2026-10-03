# Current API semantics

The [generated route/request reference](api-routes.md) enumerates the literal decorators and request models in `apps/api/princess_api/app.py`. It is checked against source without importing or composing providers. Routes can still be conditional or disabled at runtime. [Environment configuration](configuration.md), current principal and service checks determine availability.

`contracts/http/openapi-components.json` contains generated **schema components**, not this entire endpoint/authentication contract. Product DTO authorities and generation are described in [generated assets](generated-assets.md). FastAPI's development schema can be inspected when a service is legitimately composed; no public interactive docs UI is promised.

## Authentication and ownership

Principal-bound routes use `Authorization: Bearer <opaque credential>`. The API authenticates it; clients do not authorize from decoded claims. Account-only operations additionally require an account principal. Cross-owner report/evidence reads generally conceal existence with 404. An ID, URL, comparison result or store redirect is not a permission.

Public surfaces include liveness/readiness, guest creation, notice/catalogue reads as composed and raw provider-event intake. Public event intake is not trust: provider signatures and bounded raw-body verification precede application grant logic. Development identity and signed local upload routes are environment-restricted, not production login/storage endpoints.

## Error boundary

Application `PortError` becomes a safe `{"error":"code"}` response. Validation errors from the HTTP framework may have a different body; clients must not assume every failure contains the application error shape.

| Failure | HTTP status |
|---|---:|
| PayloadTooLarge | 413 |
| RateLimited | 429, with Retry-After when supplied |
| DeadlineExceeded | 504 |
| TransientUnavailable | 503 |
| Unauthenticated | 401, WWW-Authenticate: Bearer |
| NotAuthorized | 403 |
| NotFound | 404 |
| Conflict | 409 |
| InvalidInput | 422 |
| Unsupported | 501 |
| AmbiguousOutcome / PermanentFailure | 502 |

`packages/api-client` keeps transport timeout/network/abort separate from a returned API error. A mutation with no response has an unknown outcome. Honor bounded Retry-After, recheck current session and recover the intended operation rather than issuing a new paid action blindly. Internal exception chains, paths and provider payloads do not belong in UI or telemetry.

## Operation-specific behavior

| Operation | Payload/result meaning | Retry / authorization constraint |
|---|---|---|
| Guest session | Returns principal ID, opaque guest token and optional expiry | Admission limited; do not create a new guest every route mount |
| Guest transfer | Account bearer + guest credential proof; returns transferred principal | Transfer and local purge are distinct; current relational ownership governs access |
| Permission decision | Purpose/scope/decision/notice and optional request ID; validated grant snapshot | Stable decision request ID prevents a lost response from reversing a newer decision |
| Reserve upload | Media type/challenge → signed method/URL, expiry and limits | Reservation can consume another quota slot; no universal idempotency key promise |
| PUT upload | Only to allowed origin; no API bearer token | Exact derivative bytes, bounds and ticket validity matter |
| Complete upload | SHA-256 → verified capture and dimensions | Same digest converges; different digest cannot silently replace immutable input |
| Start/read/cancel analysis | Capture → run ID/status; status includes report/error references | Start deduplicates the intended capture/config; recover/poll known run |
| List analyses/history | Principal-scoped recent runs or paginated reports | Discovery is not unauthenticated recovery; history cursor/limits remain bounded |
| Read report/evidence/source | Authorized projection, lineage-bound evidence or retained bytes | Recheck ownership and live retention/overlay state; do not expose object keys |
| Delete report/capture/account | 202 `DELETION_REQUESTED` | Access restriction precedes verified physical erasure; never label 202 fully erased |
| Compare | Kind + report IDs → same-owner unsaved comparison | Uses latest saved revisions; no persisted pair, partner grant or AI call |
| Catalogue/payment account/credits | Server product mapping, opaque account reference, platform-aware balance | A displayed price/store product or credit count is not authority to mint a grant |
| Native purchase claim | Rail + proof → outcome and finish instruction | Account required; provider verification and durable grant decide completion |
| Provider events | Bounded raw signed payload → normalized event outcomes | Duplicate/reordered/missed events converge through ledger/reconciliation |
| Premium request/status/read | Intended report operation → job; saved validated overlay on read | Account, credit, permission, suitability and enabled switches; never generate on read |
| Export request/status/file | Report/layout/scope → export job, then authenticated bytes | Cards need current ordinary-sharing scope; 202 is not a finished file |
| Feedback | Owner/report/target + request ID → redacted stored feedback | Sensitive content is not telemetry; withdrawal/retention are separate |
| Push/preferences | Current principal/environment binding and preferences | Device token rotation/switching rebinds; notification does not authorize access |

## Client and server references

[API source](../../apps/api/princess_api/app.py) owns routing and HTTP request models. [Application services](../../src/princess_app/application/) own business operations; [native client operations](../../packages/api-client/src/operations.ts) and [client transport](../../packages/api-client/src/client.ts) guard the returned wire values. Product schemas describe saved report/evidence/overlay contracts; small endpoint DTOs additionally have explicit runtime guards.

For report downloads use the API's authenticated byte methods. Do not open an export URL externally and expect session cookies or a bearer token to follow. Presigned storage URLs are separate scoped capabilities and must not receive the API credential.

## Planned is not callable

Invitation/share-grant/contribution product routes discussed in older roadmap chapters are design ownership, not automatically implemented endpoints. Use the generated method/path list for current presence and the task graph for missing features. Extending a route requires source, client guard, tests and this reference to change together; prose must never announce an endpoint that does not exist.
