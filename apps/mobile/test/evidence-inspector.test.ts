import assert from "node:assert/strict";
import test from "node:test";

import { evidencePosition, stepEvidenceIndex } from "../src/ui/evidence-inspector.ts";

test("evidence inspector steps through stored items without wrapping", () => {
  assert.equal(stepEvidenceIndex(0, "PREVIOUS", 3), 0);
  assert.equal(stepEvidenceIndex(0, "NEXT", 3), 1);
  assert.equal(stepEvidenceIndex(1, "NEXT", 3), 2);
  assert.equal(stepEvidenceIndex(2, "NEXT", 3), 2);
  assert.equal(stepEvidenceIndex(99, "PREVIOUS", 3), 1);
  assert.equal(stepEvidenceIndex(-4, "NEXT", 3), 1);
});

test("evidence inspector handles empty/invalid counts and reports position", () => {
  assert.equal(stepEvidenceIndex(1, "NEXT", 0), 0);
  assert.equal(stepEvidenceIndex(1, "NEXT", -1), 0);
  assert.equal(evidencePosition(0, 0), "0 / 0");
  assert.equal(evidencePosition(1, 3), "2 / 3");
  assert.equal(evidencePosition(99, 3), "3 / 3");
});
