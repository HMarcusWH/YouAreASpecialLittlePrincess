import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import type { EvidenceBundle, Fact, ReportDocument, ReportViewModel } from "@princess/contracts";

import { baselineTraces, featureLabel, formatFact, histogram, mapToAncestor, presentationContent, presentationDisplayDomain, spacingBrackets } from "../src/index.ts";

function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(new URL(`../../../fixtures/reports/${name}`, import.meta.url), "utf8")) as T;
}

const report = fixture<ReportDocument>("report-document.json");
const evidence = fixture<EvidenceBundle>("evidence-bundle.json");
const facts = new Map(report.facts.map((f) => [f.feature_id, f] as const));

function fact(featureId: string): Fact {
  const found = facts.get(featureId);
  assert.ok(found, featureId);
  return found;
}

test("presentation registry resolves reviewed EN/SV labels, content and fixed domains", () => {
  assert.equal(featureLabel("SLANT_ANGLE_MEAN", "en-US"), "Mean dominant stroke slant");
  assert.equal(featureLabel("SLANT_ANGLE_MEAN", "sv-SE"), "Genomsnittlig dominerande strecklutning");
  assert.equal(featureLabel("PAGE_WORD_COUNT", "en"), "Detected geometric word groups");
  assert.equal(featureLabel("PAGE_WORD_COUNT", "sv-SE"), "Upptäckta geometriska ordgrupper");
  assert.equal(featureLabel("NOT_A_FEATURE", "en"), undefined);
  assert.match(presentationContent("content.highlight.v1.slant.right.almost_all", "sv") ?? "", /lutningsobservationer/);
  assert.equal(presentationContent("content.unknown", "en"), undefined);
  assert.deepEqual(presentationDisplayDomain("SLANT_ANGLE_MEAN"), {
    min: -90, max: 90, unit: "degrees", kind: "GEOMETRIC_CANVAS", accepted_min: -60, accepted_max: 60,
  });
  const mutable = presentationDisplayDomain("SLANT_ANGLE_MEAN") as Record<string, string | number>;
  mutable.min = 0;
  assert.equal(presentationDisplayDomain("SLANT_ANGLE_MEAN")?.min, -90);
  assert.equal(presentationDisplayDomain("MARGIN_RIGHT_REL"), undefined);
});

test("formats saved values with unit precision and locale", () => {
  const width = fact("IMG_WIDTH_PX");
  const en = formatFact(width, "en-US");
  const sv = formatFact({ ...width, value: 1234.5, precision: 1 }, "sv-SE");
  assert.equal(en.state, "VALUE");
  assert.match(en.state === "VALUE" ? en.text : "", /^[\d,]+\.0 px$/);
  assert.equal(sv.state === "VALUE" ? sv.text : "", "1 234,5 px");
  const slant = formatFact(fact("SLANT_ANGLE_MEAN"), "en-US");
  assert.ok(slant.state === "VALUE" && slant.text.endsWith("°") && !slant.calibrated);
});

test("missing or locked facts never render as zero", () => {
  const missing = report.facts.find((f) => f.availability === "MISSING") ?? {
    ...fact("SLANT_ANGLE_MEAN"), availability: "MISSING" as const, value: null,
  };
  const out = formatFact(missing, "en-US");
  assert.equal(out.state, "UNAVAILABLE");
  const locked = formatFact({ ...fact("SLANT_ANGLE_MEAN"), availability: "LOCKED", value: 12 }, "en-US");
  assert.equal(locked.state, "UNAVAILABLE");
  const negZero = formatFact({ ...fact("SLANT_ANGLE_MEAN"), value: -0.00001, precision: 1 }, "en-US");
  assert.equal(negZero.state === "VALUE" ? negZero.text : "", "0.0°");
});

test("engineering scores are never shown as percentages", () => {
  const score = report.facts.find((f) => f.formatting_key === "measurement.score_0_1");
  assert.ok(score);
  const out = formatFact(score, "en-US");
  assert.ok(out.state !== "VALUE" || !out.text.includes("%"));
});

test("slant histogram counts exactly the accepted observations behind the saved fact", () => {
  const h = histogram(evidence, "SLANT_ANGLE_MEAN", [-60, 60], 10);
  assert.equal(h.accepted, fact("SLANT_ANGLE_MEAN").quality.n_observations);
  assert.equal(h.bins.reduce((sum, b) => sum + b.count, 0) + h.outOfDomain, h.accepted);
  assert.equal(h.bins.length, 12);
  assert.equal(h.unit, "degrees");
  assert.ok(h.rejected > 0);
  assert.throws(() => histogram(evidence, "SLANT_ANGLE_MEAN", [0, 0], 1));
});

test("baseline traces come from stored points and match accepted line fits", () => {
  const traces = baselineTraces(evidence);
  assert.equal(traces.length, fact("BASELINE_ANGLE_MEAN").quality.n_observations);
  for (const trace of traces) {
    assert.ok(trace.points.length >= 2);
    const xs = trace.points.map(([x]) => x);
    assert.deepEqual(xs, [...xs].sort((a, b) => a - b));
    assert.equal(typeof trace.angleDegrees, "number");
  }
});

test("spacing brackets link real regions and keep rejected gaps visible", () => {
  const lines = spacingBrackets(evidence, "LINE_SPACING_PX");
  const accepted = lines.filter((b) => b.accepted);
  assert.equal(accepted.length, fact("LINE_SPACING_PX").quality.n_observations);
  for (const b of lines) {
    assert.equal(b.from.scope, "LINE");
    assert.ok(b.accepted ? b.gap >= 0 && b.rejectionReason === null : b.rejectionReason !== null);
  }
});

test("frame mapping matches the Python domain implementation", () => {
  const parity = fixture<{ frames: EvidenceBundle["frames"]; cases: { from: string; to: string; point: [number, number]; expected: [number, number] }[] }>("frame-parity.json");
  assert.ok(parity.cases.length >= 6);
  for (const c of parity.cases) {
    const [x, y] = mapToAncestor(parity.frames, c.from, c.to, c.point[0], c.point[1]);
    assert.ok(Math.abs(x - c.expected[0]) < 1e-9 && Math.abs(y - c.expected[1]) < 1e-9, JSON.stringify(c));
  }
  assert.throws(() => mapToAncestor(parity.frames, "frame_upload", "frame_analysis", 0, 0));
});

test("v2 free fixture carries reviewed server-owned highlights", () => {
  const view = fixture<ReportViewModel>("view.free-v2.json");
  const highlights = view.sections.filter((section) => section.template === "HIGHLIGHT_PRIMARY"
    || section.template === "HIGHLIGHT_SECONDARY");
  assert.deepEqual(highlights.map((section) => section.content_ids[0]), [
    "content.highlight.v1.slant.right.almost_all",
    "content.highlight.v1.layout.margins_asymmetric",
    "content.highlight.v1.baseline.angle_stable",
  ]);
  assert.deepEqual(highlights.map((section) => section.fact_ids), [
    ["fact.SLANT_RIGHT_FRACTION"],
    ["fact.MARGIN_SYMMETRY"],
    ["fact.BASELINE_ANGLE_STD"],
  ]);
});

test("free view fixture carries no premium sections and only referenced facts", () => {
  const view = fixture<ReportViewModel>("view.free.json");
  assert.ok(view.sections.every((s) => s.premium_section_id === null));
  const referenced = new Set(view.sections.flatMap((s) => s.fact_ids));
  assert.deepEqual(new Set(view.facts.map((f) => f.fact_id)), referenced);
  const share = fixture<ReportViewModel>("view.share.json");
  assert.deepEqual(share.actions, []);
  assert.deepEqual(share.authorized_asset_ids, []);
});

test("dossier model keeps server order, resolves copy and never invents values", async () => {
  const { buildDossier, presentFact, displayLocale, t } = await import("../src/index.ts");
  const v2 = fixture<ReportViewModel>("view.free-v2.json");
  const model = buildDossier(v2, "en");
  assert.deepEqual(model.highlights.map((s) => s.sectionId),
                   v2.sections.filter((s) => s.template.startsWith("HIGHLIGHT_")).map((s) => s.section_id));
  assert.equal(model.highlights[0]!.kind, "HIGHLIGHT_PRIMARY");
  assert.equal(model.highlights[0]!.title, "What stands out");
  assert.ok(model.highlights[0]!.copy.length > 0, "server-selected highlight resolves reviewed copy");
  assert.deepEqual(model.sections.map((s) => s.sectionId),
                   v2.sections.filter((s) => !s.template.startsWith("HIGHLIGHT_")).map((s) => s.section_id));
  const total = model.sections.reduce((n, s) => n + s.facts.length, 0) + model.highlights.reduce((n, s) => n + s.facts.length, 0);
  assert.equal(total, v2.sections.reduce((n, s) => n + s.fact_ids.length, 0));
  assert.equal(model.actions.find((a) => a.kind === "EXPORT")!.enabled, true);
  assert.equal(model.actions.find((a) => a.kind === "COMPARE")!.reasonText, "Comparison is not available yet.");
  assert.equal(buildDossier(v2, "sv").highlights[0]!.title, "Det som sticker ut");

  const legacy = buildDossier(fixture<ReportViewModel>("view.free.json"), "en");
  assert.equal(legacy.highlights.length, 0, "legacy v1 has no First Reveal; the client must not pick one");
  const revoked = buildDossier(fixture<ReportViewModel>("view.owner-image-revoked.json"), "en");
  assert.equal(revoked.sourceImageOmitted, true);
  assert.equal(buildDossier(fixture<ReportViewModel>("view.owner-premium.json"), "en").hasPremium, true);

  const missing = presentFact({ ...fact("SLANT_ANGLE_MEAN"), availability: "MISSING", value: null }, "en");
  assert.equal(missing.value, null);
  assert.equal(missing.availabilityText, "Not measured in this sample");
  const yes = presentFact({ ...fact("SLANT_ANGLE_MEAN"), value: true, formatting_key: "boolean" }, "sv");
  assert.equal(yes.value, "Ja");

  const unknown = buildDossier({ ...v2, sections: [{ ...v2.sections[3]!, template: "FUTURE_TEMPLATE",
                                                      content_ids: ["content.not.reviewed"] }] }, "en");
  assert.equal(unknown.sections[0]!.title, "Future template");
  assert.deepEqual(unknown.sections[0]!.copy, []);
  assert.equal(displayLocale("sv-SE"), "sv");
  assert.equal(displayLocale("de-DE"), "en");
  assert.equal(t("en", "premium.answer.NOT_ASSESSABLE"), "Could not be assessed from this sample");
});

test("research suitability remains visible in the shared EN/SV dossier model even with image facts", async () => {
  const { buildDossier, t } = await import("../src/index.ts");
  const baseline = fixture<ReportViewModel>("view.free-v2.json");
  const view: ReportViewModel = {
    ...baseline,
    sections: baseline.sections.map((section) => section.section_id === "section.sample"
      ? { ...section, availability: "INELIGIBLE" as const } : section),
  };
  const sample = view.sections.find((s) => s.section_id === "section.sample");
  assert.ok(sample);
  assert.ok(sample.fact_ids.length > 0);
  const en = buildDossier(view, "en").sections.find((s) => s.sectionId === "section.sample");
  const sv = buildDossier(view, "sv").sections.find((s) => s.sectionId === "section.sample");
  assert.equal(en?.availability, "INELIGIBLE");
  assert.equal(sv?.availability, "INELIGIBLE");
  assert.ok(en!.facts.length > 0 && sv!.facts.length > 0);
  assert.match(t("en", "report.handwriting_unverified"), /could not be verified/);
  assert.match(t("sv", "report.handwriting_unverified"), /kunde inte verifieras/);
});


test("EN/SV section headings and guarded abstention copy share one reviewed registry", async () => {
  const { sectionTitle, buildDossier, t } = await import("../src/index.ts");
  assert.equal(sectionTitle("SAMPLE_SUITABILITY", "sv", "section.sample"), "Provets lämplighet");
  assert.equal(sectionTitle("METRIC_GRID", "sv", "section.size"), "Teckenstorlek");
  assert.equal(sectionTitle("METRIC_GRID", "sv", "section.ink"), "Bläckegenskaper");
  assert.equal(sectionTitle("DISTRIBUTION", "sv", "section.slant"), "Strecklutning");
  assert.equal(sectionTitle("BASELINE_TRACE", "sv", "section.baseline"), "Baslinjeförlopp");
  assert.equal(sectionTitle("PAGE_LAYOUT", "sv", "section.layout"), "Sidlayout");
  assert.equal(sectionTitle("FUTURE_TEMPLATE", "sv"), "Future template");
  const report = fixture<ReportViewModel>("view.free-v2.json");
  const model = buildDossier(report, "sv");
  assert.equal(model.sections.find((s) => s.sectionId === "section.sample")?.title, "Provets lämplighet");
  assert.equal(model.sections.find((s) => s.sectionId === "section.ink")?.title, "Bläckegenskaper");
  assert.match(t("en", "notice.image_only"), /Image properties/);
  assert.match(t("sv", "notice.image_only"), /Bildens egenskaper/);
  assert.match(t("sv", "report.premium_ineligible"), /inte tillgängligt/);
  assert.match(t("en", "report.withheld_details"), /Show all missing/);
});


test("Free connections are separate, server-ordered and bound to saved fact support", async () => {
  const { buildDossier, sectionTitle, t } = await import("../src/index.ts");
  const original = fixture<ReportViewModel>("view.free-v2.json");
  const before = JSON.stringify(original);
  const representative = original.sections.find((s) => s.section_id === "section.slant");
  assert.ok(representative);
  const relation = {
    section_id: "section.connection.1",
    template: "PATTERN_CONNECTION",
    availability: "UNCALIBRATED",
    fact_ids: ["fact.SLANT_RIGHT_FRACTION", "fact.BASELINE_ANGLE_STD"],
    // Synthetic transport fixture: only the already reviewed copy is used;
    // this is not approval of the new relationship's editorial wording.
    content_ids: ["content.highlight.v1.slant.right.almost_all"],
    premium_section_id: null,
  } as ReportViewModel["sections"][number];
  const future = {
    ...original,
    sections: [...original.sections, relation],
  } satisfies ReportViewModel;
  const en = buildDossier(future, "en");
  const sv = buildDossier(future, "sv");
  assert.equal(en.connections.length, 1);
  assert.equal(en.connections[0]!.kind, "CONNECTION");
  assert.equal(en.connections[0]!.title, "Connection 1");
  assert.equal(sv.connections[0]!.title, "Samband 1");
  assert.equal(en.connections[0]!.missingCopy, false);
  assert.deepEqual(en.connections[0]!.facts.map((f) => f.factId), relation.fact_ids);
  assert.ok(en.connections[0]!.copy[0]?.includes("slant"));
  assert.deepEqual(en.highlights.map((h) => h.sectionId),
    buildDossier(original, "en").highlights.map((h) => h.sectionId));
  assert.deepEqual(en.sections.map((h) => h.sectionId),
    buildDossier(original, "en").sections.map((h) => h.sectionId));
  assert.equal(JSON.stringify(original), before);
  assert.equal(sectionTitle("PATTERN_CONNECTION", "en", "section.connection.bad"), "Connection");
  assert.match(t("en", "report.connections_noncausal"), /do not establish causes/);
  assert.match(t("sv", "report.connections_noncausal"), /fastställer inte orsaker/);

  const uninstalled = buildDossier({ ...original,
    sections: [{ ...representative, content_ids: ["content.proposed.not.installed"] }],
  }, "en");
  assert.equal(uninstalled.sections[0]!.missingCopy, true);
  assert.deepEqual(uninstalled.sections[0]!.copy, []);
  assert.match(t("en", "report.copy_unavailable"), /not installed/);
});
