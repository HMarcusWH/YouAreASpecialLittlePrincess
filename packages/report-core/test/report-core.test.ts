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


test("Free technical facts retain saved method, missingness and evidence-region provenance", async () => {
  const { presentFact, buildDossier, t } = await import("../src/index.ts");
  const view = fixture<ReportViewModel>("view.free-v2.json");
  const observed = view.facts.find((f) => f.feature_id === "SLANT_ANGLE_MEAN");
  assert.ok(observed);
  const presented = presentFact(observed, "sv");
  assert.equal(presented.methodId, observed.method_id);
  assert.equal(presented.methodVersion, observed.method_version);
  assert.equal(presented.missingReason, observed.quality.missing_reason);
  assert.deepEqual(presented.sourceRegionIds, observed.source_region_ids);
  assert.notEqual(presented.sourceRegionIds, observed.source_region_ids,
                  "client model must not alias authoritative source arrays");

  const missingFact = {
    ...observed,
    availability: "MISSING" as const,
    value: null,
    quality: { ...observed.quality, missing_reason: "synthetic_missing_reason" },
    source_region_ids: [],
  };
  const missing = presentFact(missingFact, "en");
  assert.equal(missing.value, null);
  assert.equal(missing.missingReason, "synthetic_missing_reason");
  assert.deepEqual(missing.sourceRegionIds, []);
  assert.equal(t("en", "fact.reason_code"), "Unavailable reason code");
  assert.equal(t("sv", "fact.source_regions"), "Underlagsregioner");

  const dossier = buildDossier(view, "en");
  const stored = dossier.sections.flatMap((section) => section.facts)
    .find((fact) => fact.featureId === "SLANT_ANGLE_MEAN");
  assert.ok(stored);
  assert.equal(stored.methodId, observed.method_id);
  assert.equal(stored.methodVersion, observed.method_version);
});

test("R4-F1 resolves all 76 source-authored /4 Free content IDs without client selector rules", async () => {
  const { featureLabel, presentationContent, sectionTitle } = await import("../src/index.ts");
  const presentation = JSON.parse(readFileSync(
    new URL("../../../contracts/product/v1/presentation-content.v2.json", import.meta.url), "utf8"));
  const reading = JSON.parse(readFileSync(
    new URL("../../../src/princess_app/domain/content/_reading_v2.json", import.meta.url), "utf8"));
  const expected = new Map<string, { en: string; sv: string }>(Object.entries(presentation.content));
  for (const row of reading.chapters) {
    expected.set(row.neutral_content_id, row.neutral);
    expected.set(row.unavailable_content_id, row.unavailable);
    assert.equal(sectionTitle("METRIC_GRID", "en", row.section_id, [row.neutral_content_id]), row.title.en);
    assert.equal(sectionTitle("METRIC_GRID", "sv", row.section_id, [row.unavailable_content_id]), row.title.sv);
  }
  for (const [state, localized] of Object.entries(reading.states))
    expected.set("content.reading.v2.state." + state.toLowerCase(), localized as { en: string; sv: string });
  for (const row of reading.relations) expected.set(row.content_id, row.copy);
  assert.equal(expected.size, 76);
  for (const [id, localized] of expected) {
    assert.equal(presentationContent(id, "en"), localized.en, id + "/en");
    assert.equal(presentationContent(id, "sv"), localized.sv, id + "/sv");
  }
  for (const [featureId, localized] of Object.entries(presentation.feature_labels)) {
    const copy = localized as { en: string; sv: string };
    assert.equal(featureLabel(featureId, "en", "presentation/2"), copy.en);
    assert.equal(featureLabel(featureId, "sv", "presentation/2"), copy.sv);
    assert.equal(featureLabel(featureId, "en"), copy.en, "unchanged v1 labels");
  }
  assert.equal(presentationContent("content.chapter.v2.slant.unreviewed", "en"), undefined);
  assert.equal(presentationContent("content.highlight.v2.slant.new_rule", "en"), undefined);
});

test("R4-F1 titles supported /4 chapters with actual selected v2 highlights", async () => {
  const { buildDossier, sectionTitle } = await import("../src/index.ts");
  const presentation = JSON.parse(readFileSync(
    new URL("../../../contracts/product/v1/presentation-content.v2.json", import.meta.url), "utf8"));
  const reading = JSON.parse(readFileSync(
    new URL("../../../src/princess_app/domain/content/_reading_v2.json", import.meta.url), "utf8"));
  const original = fixture<ReportViewModel>("view.free-v2.json");
  for (const chapter of reading.chapters) {
    const family = chapter.section_id.slice("section.".length);
    const selected = presentation.candidates.find((row: { family: string; content_id: string }) =>
      row.family === family && row.content_id.startsWith(`content.highlight.v2.${family}.`));
    assert.ok(selected, "reviewed /4 candidate for " + family);
    const legacy = original.sections.find((section) => section.section_id === chapter.section_id)!;
    assert.ok(legacy);
    assert.equal(sectionTitle(legacy.template, "en", legacy.section_id, [selected.content_id]), chapter.title.en);
    assert.equal(sectionTitle(legacy.template, "sv", legacy.section_id, [selected.content_id]), chapter.title.sv);
    // Malformed/unknown and legacy content must not opt into new chapter titles.
    assert.equal(
      sectionTitle(legacy.template, "en", legacy.section_id, [`content.highlight.v2.${family}.invented`]),
      sectionTitle(legacy.template, "en", legacy.section_id));
    assert.equal(
      sectionTitle(legacy.template, "en", legacy.section_id,
                   [selected.content_id.replace("content.highlight.v2.", "content.highlight.v1.")]),
      sectionTitle(legacy.template, "en", legacy.section_id));
    const view: ReportViewModel = { ...original, sections: original.sections.map((section) =>
      section.section_id === chapter.section_id ? { ...section, content_ids: [selected.content_id] } : section) };
    const native = buildDossier(view, "sv").sections.find((section) => section.sectionId === chapter.section_id);
    assert.equal(native?.title, chapter.title.sv);
    assert.equal(native?.missingCopy, false);
    assert.deepEqual(native?.facts.map((fact) => fact.factId), legacy.fact_ids);
  }
});

test("R4-F1 native/shared Dossier uses reviewed /4 chapters without reselecting facts", async () => {
  const { buildDossier, highlightTitle, presentationContent } = await import("../src/index.ts");
  const reading = JSON.parse(readFileSync(
    new URL("../../../src/princess_app/domain/content/_reading_v2.json", import.meta.url), "utf8"));
  const old = fixture<ReportViewModel>("view.free-v2.json");
  const byId = new Map<string, { neutral_content_id: string; unavailable_content_id: string; title: { en: string; sv: string } }>(
    reading.chapters.map((row: any) => [row.section_id, row]));
  // Synthetic display-contract projection: existing sample, fact IDs, order and measurements untouched.
  const view: ReportViewModel = {
    ...old,
    sections: old.sections.map((section) => {
      const chapter = byId.get(section.section_id);
      if (chapter) return { ...section, content_ids: [chapter.neutral_content_id] };
      return section.template.startsWith("HIGHLIGHT_")
        ? { ...section, content_ids: section.content_ids.map((id) => id.replace("content.highlight.v1.", "content.highlight.v2.")) }
        : section;
    }),
  };
  const en = buildDossier(view, "en");
  const sv = buildDossier(view, "sv");
  assert.equal(en.highlights[0]!.title, "What stands out");
  assert.equal(en.highlights[0]!.copy[0], presentationContent("content.highlight.v2.slant.right.almost_all", "en"));
  for (const [id, chapter] of byId) {
    const enSection = en.sections.find((section) => section.sectionId === id)!;
    const svSection = sv.sections.find((section) => section.sectionId === id)!;
    assert.equal(enSection.title, chapter.title.en);
    assert.equal(svSection.title, chapter.title.sv);
    assert.equal(enSection.missingCopy, false);
    assert.equal(svSection.missingCopy, false);
    const original = old.sections.find((section) => section.section_id === id)!;
    assert.deepEqual(enSection.facts.map((f) => f.factId), original.fact_ids);
  }
  assert.deepEqual(en.sections.map((s) => s.sectionId),
                   old.sections.filter((s) => !s.template.startsWith("HIGHLIGHT_")).map((s) => s.section_id));
  const neutral = { ...old, sections: [{ ...old.sections[0]!,
    content_ids: ["content.reading.v2.state.partial"], fact_ids: [], availability: "UNCALIBRATED" as const }] };
  assert.equal(buildDossier(neutral, "en").highlights[0]!.title, "Overview");
  assert.equal(buildDossier(neutral, "sv").highlights[0]!.title, "Översikt");
  assert.equal(buildDossier(neutral, "en").highlights[0]!.copy[0], reading.states.PARTIAL.en);
  assert.equal(highlightTitle("HIGHLIGHT_PRIMARY", "en", ["content.highlight.v1.none"]), "What stands out");
  const unknown = { ...view, sections: view.sections.map((section) => section.section_id === "section.slant"
    ? { ...section, content_ids: ["content.chapter.v2.slant.unreviewed"] } : section) };
  const unavailable = buildDossier(unknown, "en").sections.find((s) => s.sectionId === "section.slant")!;
  assert.equal(unavailable.missingCopy, true);
  assert.deepEqual(unavailable.copy, []);
});
