import assert from "node:assert/strict";
import test from "node:test";

import { MAX_DIMENSION, MAX_PIXELS, planDerivative, previewCropToPixels } from "../src/work/derivative.ts";

test("ordinary photos pass through unscaled and full-frame crops are ignored", () => {
  assert.deepEqual(planDerivative(4032, 3024, null), { ok: true, crop: null, resize: null });
  assert.deepEqual(planDerivative(4032, 3024, { x: 0, y: 0, width: 4032, height: 3024 }),
                   { ok: true, crop: null, resize: null });
});

test("oversized captures are bounded to the intake policy before upload", () => {
  const big = planDerivative(8064, 6048, null);  // 48.8 MP
  assert.ok(big.ok && big.resize);
  assert.ok(big.resize.width * big.resize.height <= MAX_PIXELS);
  const panorama = planDerivative(20_000, 1_000, null);
  assert.ok(panorama.ok && panorama.resize && panorama.resize.width <= MAX_DIMENSION);
});

test("crops are clamped to the image and tiny results are refused", () => {
  const plan = planDerivative(1000, 800, { x: -20, y: 100, width: 5000, height: 300 });
  assert.deepEqual(plan, { ok: true, crop: { x: 0, y: 100, width: 1000, height: 300 }, resize: null });
  assert.deepEqual(planDerivative(1000, 800, { x: 10, y: 10, width: 20, height: 400 }),
                   { ok: false, code: "image_too_small" });
  assert.deepEqual(planDerivative(Number.NaN, 10, null), { ok: false, code: "image_unreadable" });
});

test("a crop drawn on the fitted preview maps to working-image pixels", () => {
  assert.deepEqual(previewCropToPixels({ x: 10, y: 20, width: 100, height: 50 }, { width: 300, height: 200 },
                                       { width: 3000, height: 2000 }),
                   { x: 100, y: 200, width: 1000, height: 500 });
});
