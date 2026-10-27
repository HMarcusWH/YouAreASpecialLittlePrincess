import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { focusSourceEvidence, sourceImageEligible } from "../src/index.ts";

function fixture<T>(path: string): T {
  return JSON.parse(readFileSync(new URL("../../../fixtures/reports/" + path, import.meta.url), "utf8")) as T;
}
const view = fixture<ReportViewModel>("view.free-v2.json");
const evidence = fixture<EvidenceBundle>("evidence-bundle.v2.json");

test("source navigation uses only source-region IDs attached to supported saved facts", () => {
  assert.equal(sourceImageEligible(view), true);
  for (const sectionId of ["section.slant", "section.baseline", "section.spacing", "section.size", "section.layout"]) {
    const chosen = focusSourceEvidence(view, evidence, sectionId, 900, 360);
    assert.equal(chosen.status, "READY", sectionId);
    assert.ok(chosen.total >= chosen.regions.length);
    assert.ok(chosen.regions.length <= 32);
    const section = view.sections.find((s) => s.section_id === sectionId)!;
    const supported = new Set(view.facts.filter((fact) => section.fact_ids.includes(fact.fact_id)
      && (fact.availability === "READY" || fact.availability === "UNCALIBRATED"))
      .flatMap((fact) => fact.source_region_ids));
    for (const region of chosen.regions) {
      assert.ok(supported.has(region.regionId));
      assert.equal(region.points.length, 5);
      assert.deepEqual(region.points[0], region.points[4]);
      for (const [x, y] of region.points) {
        assert.ok(x >= -1e-6 && x <= 900 + 1e-6 && y >= -1e-6 && y <= 360 + 1e-6);
      }
    }
  }
  // page_0 is a derived analysis-frame page extent, not a guaranteed valid
  // source-frame rectangle. Its mapped corners leave this fixture raster; refuse it.
  assert.equal(focusSourceEvidence(view, evidence, "section.ink", 900, 360).status, "NO_SUPPORTED_REGIONS");
  assert.equal(focusSourceEvidence(view, evidence, "section.reference", 900, 360).status, "NO_SUPPORTED_REGIONS");
  assert.equal(focusSourceEvidence(view, evidence, "section.nonexistent", 900, 360).status, "NO_SUPPORTED_REGIONS");
});

test("source-region membership never transfers to a foreign asset, revoked image or wrong raster frame", () => {
  const revoked: ReportViewModel = { ...view, authorized_asset_ids: [] };
  assert.equal(sourceImageEligible(revoked), false);
  assert.equal(focusSourceEvidence(revoked, evidence, "section.baseline", 900, 360).status, "IMAGE_UNAVAILABLE");
  assert.equal(focusSourceEvidence(view, null, "section.baseline", 900, 360).status, "EVIDENCE_UNAVAILABLE");
  const foreign = { ...evidence, analysis: { ...evidence.analysis, input_asset_id: "foreign-source" } };
  assert.equal(focusSourceEvidence(view, foreign, "section.baseline", 900, 360).status, "EVIDENCE_UNAVAILABLE");
  assert.equal(focusSourceEvidence(view, evidence, "section.baseline", 713, 316).status, "FRAME_MISMATCH");
  const shared: ReportViewModel = { ...view, projection: "SHARE" };
  assert.equal(sourceImageEligible(shared), false);
  assert.equal(focusSourceEvidence(shared, evidence, "section.baseline", 900, 360).regions.length, 0);
});

test("source focus refuses missing, malformed, out-of-frame or unfounded region references", () => {
  const selected = view.sections.find((s) => s.section_id === "section.baseline")!;
  const facts = view.facts.map((f) => selected.fact_ids.includes(f.fact_id)
    ? { ...f, availability: "MISSING" as const, value: null } : f);
  assert.equal(focusSourceEvidence({ ...view, facts }, evidence, "section.baseline", 900, 360).status,
               "NO_SUPPORTED_REGIONS");
  const original = evidence.regions.find((region) => region.region_id === "line_0")!;
  const malformed = { ...evidence, regions: evidence.regions.map((region) =>
    region.region_id === "line_0" ? { ...region, width: -1 } : region) };
  const result = focusSourceEvidence(view, malformed, "section.baseline", 900, 360);
  assert.equal(result.regions.some((region) => region.regionId === "line_0"), false);
  const relocated = { ...evidence, regions: evidence.regions.map((region) =>
    region.region_id === "line_0" ? { ...region, x: 1e6, y: -9 } : region) };
  assert.equal(focusSourceEvidence(view, relocated, "section.baseline", 900, 360)
               .regions.some((region) => region.regionId === "line_0"), false);
  assert.ok(original.width > 0);
  assert.throws(() => focusSourceEvidence(view, evidence, "section.baseline", 900, 360, 65), RangeError);
});

test("bounded stepping remains honest about truncation while keeping full supported count", () => {
  const a = focusSourceEvidence(view, evidence, "section.size", 900, 360, 5);
  const b = focusSourceEvidence(view, evidence, "section.size", 900, 360, 32);
  assert.equal(a.status, "READY");
  assert.equal(a.regions.length, 5);
  assert.equal(a.total, b.total);
  assert.deepEqual(a.regions, b.regions.slice(0, 5));
});
