# Product, HTTP and policy authorities

[Product v1](product/v1/README.md) owns product wire schemas and generation. [Consent](consent/README.md) owns separately versioned draft policy/permission semantics. `http/openapi-components.json` is generated schema components, not a complete callable route reference.

Use [current routes](../docs/reference/api.md) for actual handlers and [generated assets](../docs/reference/generated-assets.md) for edits. Approval, runtime activation and schema validity are different states. Do not alter consent decisions or source digests during documentation work.
