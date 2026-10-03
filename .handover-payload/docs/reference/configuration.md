# Configuration and secret boundaries

[Generated declarations](environment-matrix.md) list the exact checked-in environment provider modes, switches and component secret/egress names. They are declarations, not proof that every adapter is implemented or approved. `parse_manifest`, `load_runtime_config`, runtime preflight and final composition enforce different layers of the boundary.

## Server runtime

| Name / source | Meaning |
|---|---|
| `PRINCESS_ENV` | local, test, preview, staging or production manifest |
| `PRINCESS_COMPONENT` | Fixed reviewed process role; not an arbitrary executable command |
| `PRINCESS_DATABASE_URL` | Runtime role connection for the selected component/environment; never use the migration owner for ordinary traffic |
| `PRINCESS_MIGRATION_DATABASE_URL` | One-shot migration/operator setup connection; separate from API credentials |
| `PRINCESS_SESSION_SECRET`, `PRINCESS_IDENTITY_AUDIENCE` | Local/composed session configuration; names and allowed components are manifest-bound |
| `PRINCESS_STORAGE_SIGNING_KEY` / `PRINCESS_STORAGE_READ_KEY` | Local store API/worker capability material, not native-public configuration |
| `PRINCESS_LOCAL_STORAGE_DIR` | Local private filesystem store, shared deliberately by relevant local workers |
| `PRINCESS_TOMBSTONE_DIR` | Forward deletion/revocation log; never restore backwards with the database |
| `PRINCESS_PUBLIC_API_BASE` | API origin placed in local signed upload tickets; must be reachable by the device |
| `PRINCESS_CHROMIUM` | Reviewed renderer-browser executable override when needed, not a browser URL |
| Protected Supabase inputs | Exact selected staging verification tuple and receipt-derived binding; see the dedicated runbook rather than copying private values here |

The complete names and current source uses are indexed by [command/config inventory](command-inventory.md). Do not put provider keys in `EXPO_PUBLIC_*`, `NEXT_PUBLIC_*`, native extras, URLs or logs. Not every operational directory is declared a secret, but its contents may still be sensitive.

## Native build-time configuration

These values are evaluated by `apps/mobile/app.config.ts`, included in the built configuration as appropriate and validated again by `src/config/runtime.ts` before network use.

| Variable | Meaning |
|---|---|
| `INKTROSPECT_APP_VARIANT` | development, staging or store; selects identifiers, scheme and defaults |
| `INKTROSPECT_API_BASE` | Required client-reachable API origin; staging/store require HTTPS |
| `INKTROSPECT_BACKEND_ENV` | Backend environment; must be compatible with the selected variant |
| `INKTROSPECT_UPLOAD_ORIGINS` | Comma-separated additional allowed storage upload origins |
| `INKTROSPECT_LINK_HOSTS` | Comma-separated configured verified-link hosts; actual domain verification remains an external setup |

The app name remains `Inktrospect` across variants because native generation/CI expect that workspace/scheme. Identifiers/schemes differ. Native permission/plugin/identifier changes require rebuilding; a JavaScript refresh is not sufficient. A store variant does not imply signing, catalogue, provider account or store approval.

No API origin should silently fall back to a production service. Development HTTP is deliberately bounded; test the actual emulator/device networking and origin allowlist.

## Capability switches

Switch names are generated from manifests. A value enables only the code path its implementation recognizes; it does not override missing provider composition or an owner approval. Disabling commerce does not stop required refund/provider-event reconciliation. Disabling new Premium work does not prove already accepted provider work was cancelled. Read the individual runbook before changing a switch.

## Environment examples and custody

The [local setup](../development/local-setup.md) uses visibly local-only non-secret example credentials. Never copy these into staging/production or into a shared public demo. Real values belong in an approved secret manager or protected operator environment. [Access and assets](../handover/access-and-assets.md) records the unresolved custody handoff without exposing values.

Configuration changes affecting provider scope, cost, retention, data residency, store rules or signing require the owning decision and current verification. This documentation pass does not refresh external policies or upgrade a version pin.