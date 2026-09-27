# Generated TypeScript contracts

`src/generated.ts` is generated from `contracts/product/v1/` by `tools/generate_product_contracts.py`. Do not hand-edit it and do not create a second client-side product model for the same wire objects.

T01 guarantees deterministic generation and parity with the Python wire names and OpenAPI components. T28 added the pinned pnpm workspace: this package is `@princess/contracts`, type-checked with the workspace TypeScript (`pnpm typecheck`). It still has no runtime dependency and no second generator.
