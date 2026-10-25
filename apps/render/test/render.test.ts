import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { formatFact } from "@princess/report-core";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/reports/view.${name}.json`, import.meta.url), "utf8"));
const GENERATED = "2026-09-27T12:00:00Z";

function run(input: unknown, ...args: string[]) {
  const result = spawnSync(process.execPath, [BIN, ...args], { input: JSON.stringify(input), maxBuffer: 64 << 20,
                                                               env: process.env, timeout: 90_000 });
  return { status: result.status, stdout: result.stdout, stderr: result.stderr.toString().trim() };
}

test("print HTML carries every projected fact exactly as the interactive report formats it", () => {
  const view = fixture("export-v2-no-image");
  const out = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html");
  assert.equal(out.status, 0, out.stderr);
  const html = out.stdout.toString();
  for (const fact of view.facts) {
    const formatted = formatFact(fact, "en");
    if (formatted.state === "VALUE" && !formatted.text.startsWith("value.")) {
      assert.ok(html.includes(formatted.text), `missing ${fact.fact_id}: ${formatted.text}`);
    }
  }
  assert.ok(html.includes("Source image omitted"));
  assert.ok(html.includes(`r${view.source_revision}`) && !html.includes("<script"));
});

test("server-owned highlight content renders from reviewed presentation IDs", () => {
  const view = structuredClone(fixture("export-v2-no-image"));
  view.sections.unshift({
    section_id: "section.highlight.primary",
    template: "HIGHLIGHT_PRIMARY",
    availability: "UNCALIBRATED",
    fact_ids: ["fact.SLANT_RIGHT_FRACTION"],
    content_ids: ["content.highlight.v1.slant.right.almost_all"],
    premium_section_id: null,
  });
  const html = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html").stdout.toString();
  assert.ok(html.includes("What stands out"));
  assert.ok(html.includes("Almost every accepted slant observation leans right."));
  assert.ok(html.includes("Fraction of right-slanted strokes"));
  assert.ok(!html.includes("content.highlight.v1."));
});

test("hostile strings are escaped and nothing can load or run", () => {
  const view = fixture("export-v2-no-image");
  const target = view.facts.find((f: { availability: string }) => f.availability === "READY");
  target.value = "<img src=https://evil.example/x onerror=alert(1)><script>alert(2)</script>";
  target.formatting_key = "text";
  const html = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html").stdout.toString();
  assert.ok(!html.includes("<script>alert") && !html.includes("<img src=https://evil"));
  assert.ok(html.includes("default-src 'none'"));
});

test("PDFs are tagged, sized per layout and contain pages", { timeout: 120_000 }, () => {
  const view = fixture("export-v2-no-image");
  const sizes: Record<string, [number, number]> = { A4: [595.92, 842.88], LETTER: [612, 792] };
  for (const [layout, [w, h]] of Object.entries(sizes)) {
    const out = run({ view, layout, locale: "sv", generated_at: GENERATED });
    assert.equal(out.status, 0, out.stderr);
    const pdf = out.stdout.toString("latin1");
    assert.ok(pdf.startsWith("%PDF-"), layout);
    assert.ok(pdf.includes("/StructTreeRoot"), `${layout} is not tagged`);
    const box = /\/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]/.exec(pdf);
    assert.ok(box, `${layout} has no MediaBox`);
    assert.ok(Math.abs(Number(box[1]) - w) < 1 && Math.abs(Number(box[2]) - h) < 1, `${layout} ${box[1]}x${box[2]}`);
    assert.ok((pdf.match(/\/Type \/Page\b/g) ?? []).length >= 1);
  }
});

test("share cards are fixed-size PNGs of the redacted SHARE projection", { timeout: 120_000 }, () => {
  const view = fixture("share-v2");
  for (const [layout, height] of [["CARD_SQUARE", 1080], ["CARD_STORY", 1920]] as const) {
    const out = run({ view, layout, locale: "en", generated_at: GENERATED });
    assert.equal(out.status, 0, out.stderr);
    const png = out.stdout;
    assert.equal(png.subarray(1, 4).toString(), "PNG");
    assert.equal(png.readUInt32BE(16), 1080);
    assert.equal(png.readUInt32BE(20), height);
  }
  const html = run({ view, layout: "CARD_SQUARE", locale: "en", generated_at: GENERATED }, "--html").stdout.toString();
  assert.ok(html.includes("<title>Inktrospect</title>"));
  assert.ok(html.includes("Inktrospect") && !html.includes("Princess"));
  assert.ok(!html.includes("<img") && (html.match(/data-fact-id/g) ?? []).length <= 4);
});

test("legacy v1 export remains renderable after renderer v2", () => {
  const view = fixture("export-no-image");
  const out = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html");
  assert.equal(out.status, 0, out.stderr);
  const html = out.stdout.toString();
  assert.ok(html.includes("Inktrospect"));
  assert.ok(!html.includes("What stands out"));
});

test("projection/layout mismatches and bad input fail with a code", () => {
  const free = fixture("free");
  const wrong = run({ view: free, layout: "A4", locale: "en", generated_at: GENERATED }, "--html");
  assert.equal(wrong.status, 1);
  assert.equal(wrong.stderr, "documents_render_export_projections_only");
  const card = run({ view: fixture("export-v2-no-image"), layout: "CARD_SQUARE", locale: "en", generated_at: GENERATED },
                   "--html");
  assert.equal(card.stderr, "cards_render_share_projections_only");
  assert.equal(run({ view: free, layout: "POSTER", locale: "en", generated_at: GENERATED }).status, 2);
  assert.equal(run({ view: free, layout: "A4", locale: "de", generated_at: GENERATED }).status, 2);
  const corrupt = structuredClone(fixture("export-v2-no-image"));
  corrupt.contract_version = "9.0.0";
  assert.equal(run({ view: corrupt, layout: "A4", locale: "en", generated_at: GENERATED }).status, 1);
});

test("ineligible research sample is explicitly shown in EN/SV exports while exact image facts remain", () => {
  const view = structuredClone(fixture("export-v2-no-image"));
  const section = view.sections.find((s: { section_id: string }) => s.section_id === "section.sample");
  assert.ok(section && section.fact_ids.length > 0);
  section.availability = "INELIGIBLE";
  for (const locale of ["en", "sv"] as const) {
    const output = run({ view, layout: "A4", locale, generated_at: GENERATED }, "--html");
    assert.equal(output.status, 0, output.stderr);
    const html = output.stdout.toString();
    assert.ok(html.includes(locale === "en" ? "Handwriting structure could not be verified"
                                           : "Handskriftens struktur kunde inte verifieras"));
    assert.ok(html.includes(locale === "en" ? "Detected geometric word groups"
                                           : "Upptäckta geometriska ordgrupper"));
  }
});


test("missing-only and ineligible share cards never impersonate a handwriting result", () => {
  const missing = structuredClone(fixture("share-v2"));
  // SHARE may omit sample suitability. When all selected facts are withheld,
  // the branded card must not imply a successful handwriting analysis.
  missing.facts = missing.facts.map((fact: { availability: string; value: unknown }) =>
    ({ ...fact, availability: "MISSING", value: null }));
  for (const locale of ["en", "sv"] as const) {
    const result = run({ view: missing, layout: "CARD_SQUARE", locale, generated_at: GENERATED }, "--html");
    assert.equal(result.status, 0, result.stderr);
    const html = result.stdout.toString();
    assert.ok(html.includes(locale === "en" ? "No supported handwriting measurements shown"
                                           : "Inga styrkta handskriftsmätvärden visas"));
    assert.equal((html.match(/data-fact-id/g) ?? []).length, 0);
  }
  const ineligible = structuredClone(fixture("export-v2-no-image"));
  const sample = ineligible.sections.find((s: { section_id: string }) => s.section_id === "section.sample");
  assert.ok(sample);
  const imageFacts = new Set(["IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO"]);
  ineligible.facts = ineligible.facts.filter((fact: { feature_id: string }) => imageFacts.has(fact.feature_id));
  ineligible.sections = [{ ...sample, availability: "INELIGIBLE",
                           fact_ids: sample.fact_ids.filter((id: string) => imageFacts.has(id.replace("fact.", ""))) }];
  ineligible.projection = "SHARE";
  ineligible.actions = [];
  ineligible.authorized_asset_ids = [];
  for (const locale of ["en", "sv"] as const) {
    const result = run({ view: ineligible, layout: "CARD_SQUARE", locale, generated_at: GENERATED }, "--html");
    assert.equal(result.status, 0, result.stderr);
    const html = result.stdout.toString();
    assert.ok(html.includes(locale === "en" ? "No supported handwriting measurements shown"
                                           : "Inga styrkta handskriftsmätvärden visas"));
    assert.ok(html.includes(locale === "en" ? "Image width" : "Bildbredd"));
    assert.ok(!html.includes('data-fact-id="fact.SLANT_ANGLE_MEAN"'));
  }
});


test("the Swedish PDF uses reviewed section headings instead of English template identifiers", () => {
  const view = fixture("export-v2-no-image");
  const out = run({ view, layout: "A4", locale: "sv", generated_at: GENERATED }, "--html");
  assert.equal(out.status, 0, out.stderr);
  const markup = out.stdout.toString();
  for (const heading of ["Provets lämplighet", "Teckenstorlek", "Strecklutning",
                         "Baslinjeförlopp", "Sidlayout", "Bläckegenskaper"]) {
    assert.ok(markup.includes(heading), heading);
  }
  assert.ok(!markup.includes(">Sample suitability<"));
  assert.ok(!markup.includes(">Metric grid<"));
});


test("future Free chapters and connections retain full print detail without inventing copy", () => {
  const view = structuredClone(fixture("export-v2-no-image"));
  const chapter = view.sections.find((s: { section_id: string }) => s.section_id === "section.slant");
  assert.ok(chapter);
  chapter.content_ids = ["content.highlight.v1.slant.right.almost_all"];
  view.sections.push({
    section_id: "section.connection.1",
    template: "PATTERN_CONNECTION",
    availability: "UNCALIBRATED",
    fact_ids: ["fact.SLANT_RIGHT_FRACTION", "fact.BASELINE_ANGLE_STD"],
    content_ids: ["content.highlight.v1.slant.right.almost_all"],
    premium_section_id: null,
  });
  for (const locale of ["en", "sv"] as const) {
    const result = run({ view, layout: "A4", locale, generated_at: GENERATED }, "--html");
    assert.equal(result.status, 0, result.stderr);
    const html = result.stdout.toString();
    assert.ok(html.includes('data-section="section.connection.1"'));
    assert.ok(html.includes('data-section="section.slant"'));
    assert.ok(html.includes('class="pr-chapter-copy"'));
    assert.ok(html.includes(locale === "en" ? "Connections in this sample" : "Samband i detta prov"));
    assert.ok(html.includes(locale === "en" ? "do not establish causes" : "fastställer inte orsaker"));
    // Print is entirely static and every supported fact is visible without an
    // interactive disclosure. PDF must never silently omit the 64-fact drawer.
    assert.ok(!html.includes("<details class=\"pr-measurement-details\""));
    assert.ok(html.includes('data-fact-id="fact.SLANT_RIGHT_FRACTION"'));
    const saved = view.facts.find((fact: { fact_id: string }) => fact.fact_id === "fact.SLANT_RIGHT_FRACTION");
    assert.ok(saved);
    assert.ok(html.includes('class="pr-fact-provenance"'));
    assert.ok(html.includes(saved.method_id), "technical export must retain the actual method ID");
    assert.ok(html.includes(locale === "en" ? "Evidence regions" : "Underlagsregioner"));
  }

  // Unknown editorial IDs do not turn into synthetic prose or raw identifiers.
  chapter.content_ids = ["content.pending.review"];
  const result = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html");
  assert.equal(result.status, 0, result.stderr);
  const html = result.stdout.toString();
  assert.ok(html.includes("reviewed description for this saved section is not installed"));
  assert.ok(!html.includes("content.pending.review"));
});
