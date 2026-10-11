import assert from "node:assert/strict";
import test from "node:test";

import { evidencePage, evidencePosition, stepEvidenceIndex } from "../src/ui/evidence-inspector.ts";

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


test("two thousand observations remain navigable in bounded, non-overlapping pages", () => {
  const original = Array.from({ length: 1940 }, (_, i) => "obs:slant:component_" + i);
  const first = evidencePage(original, 0);
  const second = evidencePage(original, 1);
  const last = evidencePage(original, 10000);
  assert.equal(first.rows.length, 20);
  assert.equal(first.pageCount, 97);
  assert.equal(first.start, 0);
  assert.equal(first.end, 20);
  assert.deepEqual(second.rows, original.slice(20, 40));
  assert.equal(last.page, 96);
  assert.equal(last.start, 1920);
  assert.equal(last.end, 1940);
  assert.deepEqual(last.rows, original.slice(1920));
  assert.deepEqual(Array.from({ length: 97 }, (_, i) => evidencePage(original, i))
    .flatMap((p) => p.rows), original);
});

test("empty evidence and invalid page requests are safe", () => {
  assert.deepEqual(evidencePage([], 10), { page: 0, pageCount: 0, start: 0, end: 0, rows: [] });
  assert.deepEqual(evidencePage([1, 2, 3], Number.NaN).rows, [1, 2, 3]);
  assert.equal(evidencePage([1, 2, 3], -500).page, 0);
  assert.throws(() => evidencePage([1], 0, 0), RangeError);
});
