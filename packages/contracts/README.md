# Generated TypeScript contracts

`src/generated.ts` is generated from `contracts/product/v1/` by `tools/generate_product_contracts.py`. Do not hand-edit it and do not create a second client-side product model for the same wire objects.

T01 guarantees deterministic generation and parity with the Python wire names and OpenAPI components. T28 added the pinned pnpm workspace: this package is `@princess/contracts`, type-checked with the workspace TypeScript (`pnpm typecheck`). It still has no runtime dependency and no second generator.

## Maintainer navigation

Generated declarations are outputs of `tools/generate_product_contracts.py` and the source authorities under `contracts/product/v1`. Do not hand-edit generated types or use a cast as a trust-boundary validator. Field names, versions and missingness must remain identical across Python/TypeScript consumers.

Read [product authority](../../contracts/product/v1/README.md), [generated assets](../../docs/reference/generated-assets.md) and [API semantics](../../docs/reference/api.md). Regenerate and run the owning drift/positive/negative tests after source changes; small endpoint DTOs also need their explicit client guards.
