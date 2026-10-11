import assert from "node:assert/strict";
import test from "node:test";

import { evidenceOutlines, evidencePage, evidencePosition, stepEvidenceIndex } from "../src/ui/evidence-inspector.ts";
import type { EvidenceBundle } from "@princess/contracts";

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


test("line and word outlines retain separate caps and close the mapped polygon", () => {
  const frames = [
    { frame_id: "original", parent_frame_id: null, unit: "px", width: 400, height: 200,
      transform_to_parent: null },
    { frame_id: "analysis", parent_frame_id: "original", unit: "px", width: 200, height: 100,
      transform_to_parent: [2, 0, 0, 0, 2, 0, 0, 0, 1] },
  ];
  const regions = [
    ...Array.from({ length: 60 }, (_, i) => ({
      region_id: "line_" + i, scope: "LINE", frame_id: "analysis",
      x: 10, y: 10 + i, width: 40, height: 8,
    })),
    ...Array.from({ length: 80 }, (_, i) => ({
      region_id: "word_" + i, scope: "WORD", frame_id: "analysis",
      x: 12, y: 11 + i, width: 15, height: 5,
    })),
  ];
  const bundle = { frames, regions } as unknown as EvidenceBundle;
  const mapped = evidenceOutlines(bundle, "original", 0.5);
  assert.equal(mapped.length, 72);
  assert.equal(mapped.filter((o) => o.scope === "LINE").length, 24);
  assert.equal(mapped.filter((o) => o.scope === "WORD").length, 48);
  assert.equal(mapped[0]?.regionId, "line_0");
  assert.deepEqual(mapped[0]?.points[0], [10, 10]);
  assert.deepEqual(mapped[0]?.points[2], [50, 18]);
  assert.deepEqual(mapped[0]?.points[0], mapped[0]?.points[4]);
  assert.equal(evidenceOutlines(bundle, "original", 0).length, 0);
  assert.throws(() => evidenceOutlines(bundle, "original", 1, -1, 2), RangeError);
});

test("lineage mismatches refuse overlays rather than fabricate geometry", () => {
  const bundle = {
    frames: [{ frame_id: "original", parent_frame_id: null, unit: "px",
               width: 400, height: 200, transform_to_parent: null }],
    regions: [{ region_id: "orphan", frame_id: "unknown", scope: "WORD",
                x: 10, y: 20, width: 20, height: 8 }],
  } as unknown as EvidenceBundle;
  assert.deepEqual(evidenceOutlines(bundle, "original", 1), []);
});
