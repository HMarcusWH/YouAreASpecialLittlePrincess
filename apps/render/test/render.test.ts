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
  const view = fixture("export-no-image");
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
  const view = structuredClone(fixture("export-no-image"));
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
  const view = fixture("export-no-image");
  const target = view.facts.find((f: { availability: string }) => f.availability === "READY");
  target.value = "<img src=https://evil.example/x onerror=alert(1)><script>alert(2)</script>";
  target.formatting_key = "text";
  const html = run({ view, layout: "A4", locale: "en", generated_at: GENERATED }, "--html").stdout.toString();
  assert.ok(!html.includes("<script>alert") && !html.includes("<img src=https://evil"));
  assert.ok(html.includes("default-src 'none'"));
});

test("PDFs are tagged, sized per layout and contain pages", { timeout: 120_000 }, () => {
  const view = fixture("export-no-image");
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
  const view = fixture("share");
  for (const [layout, height] of [["CARD_SQUARE", 1080], ["CARD_STORY", 1920]] as const) {
    const out = run({ view, layout, locale: "en", generated_at: GENERATED });
    assert.equal(out.status, 0, out.stderr);
    const png = out.stdout;
    assert.equal(png.subarray(1, 4).toString(), "PNG");
    assert.equal(png.readUInt32BE(16), 1080);
    assert.equal(png.readUInt32BE(20), height);
  }
  const html = run({ view, layout: "CARD_SQUARE", locale: "en", generated_at: GENERATED }, "--html").stdout.toString();
  assert.ok(!html.includes("<img") && (html.match(/data-fact-id/g) ?? []).length <= 4);
});

test("projection/layout mismatches and bad input fail with a code", () => {
  const free = fixture("free");
  const wrong = run({ view: free, layout: "A4", locale: "en", generated_at: GENERATED }, "--html");
  assert.equal(wrong.status, 1);
  assert.equal(wrong.stderr, "documents_render_export_projections_only");
  const card = run({ view: fixture("export-no-image"), layout: "CARD_SQUARE", locale: "en", generated_at: GENERATED },
                   "--html");
  assert.equal(card.stderr, "cards_render_share_projections_only");
  assert.equal(run({ view: free, layout: "POSTER", locale: "en", generated_at: GENERATED }).status, 2);
  assert.equal(run({ view: free, layout: "A4", locale: "de", generated_at: GENERATED }).status, 2);
  const corrupt = structuredClone(fixture("export-no-image"));
  corrupt.contract_version = "9.0.0";
  assert.equal(run({ view: corrupt, layout: "A4", locale: "en", generated_at: GENERATED }).status, 1);
});
