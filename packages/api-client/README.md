# Shared API transport and runtime guards

Source exports are in `src/index.ts`; transport and native operations live in `src/client.ts` and `src/operations.ts`. Credentials can be resolved per request so long-lived native clients do not keep stale bearers. Runtime guards validate returned objects; a TypeScript cast is not validation.

`TransportError` separates timeout/network/abort from an API response. Honor bounded Retry-After and operation-specific idempotency. Uploads go only to approved origins without the API credential; protected image/export downloads stay authenticated API operations. Portable hashing and strict URI parsing are shared, not alternate authorization logic. Read [API semantics](../../docs/reference/api.md), [native lifecycle](../../docs/architecture/mobile-lifecycle.md) and [package scripts](../../docs/reference/command-inventory.md).
