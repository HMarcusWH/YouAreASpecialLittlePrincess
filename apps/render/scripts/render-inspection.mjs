import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename } from "node:path";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const OUT = new URL("../artifacts/t21-render-inspection/", import.meta.url);
const GENERATED = "2026-09-27T12:00:00Z";
const RENDER_TEMPLATE = "render-template/2";
const report = JSON.parse(readFileSync(new URL("../../../fixtures/reports/report-document.v2.json", import.meta.url), "utf8"));
const fixtures = {
  export: JSON.parse(readFileSync(new URL("../../../fixtures/reports/view.export-v2-no-image.json", import.meta.url), "utf8")),
  share: JSON.parse(readFileSync(new URL("../../../fixtures/reports/view.share-v2.json", import.meta.url), "utf8")),
};

const cases = [
  ["dossier-a4-en.pdf", "export", "A4", "en"],
  ["dossier-a4-sv.pdf", "export", "A4", "sv"],
  ["dossier-letter-en.pdf", "export", "LETTER", "en"],
  ["dossier-letter-sv.pdf", "export", "LETTER", "sv"],
  ["share-square-en.png", "share", "CARD_SQUARE", "en"],
  ["share-square-sv.png", "share", "CARD_SQUARE", "sv"],
  ["share-story-en.png", "share", "CARD_STORY", "en"],
  ["share-story-sv.png", "share", "CARD_STORY", "sv"],
];

function render(view, layout, locale) {
  const out = spawnSync(process.execPath, [BIN], {
    input: JSON.stringify({ view, layout, locale, generated_at: GENERATED }),
    maxBuffer: 64 << 20,
    env: process.env,
    timeout: 120_000,
  });
  if (out.status !== 0) throw new Error(`render failed ${layout}/${locale}: ${out.stderr.toString()}`);
  return out.stdout;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function pdfPages(bytes) {
  return (bytes.toString("latin1").match(/\/Type \/Page\b/g) ?? []).length;
}

function pngSize(bytes) {
  if (bytes.subarray(1, 4).toString() !== "PNG") throw new Error("invalid PNG");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
const artifacts = [];
for (const [file, source, layout, locale] of cases) {
  const view = fixtures[source];
  const bytes = render(view, layout, locale);
  writeFileSync(new URL(file, OUT), bytes);
  artifacts.push({
    file,
    source_fixture: source === "export" ? "view.export-v2-no-image.json" : "view.share-v2.json",
    source_report_id: view.source_report_id,
    source_revision: view.source_revision,
    projection: view.projection,
    layout,
    locale,
    bytes: bytes.byteLength,
    sha256: sha256(bytes),
    ...(file.endsWith(".pdf") ? { pages: pdfPages(bytes) } : pngSize(bytes)),
  });
}
const manifest = {
  generated_at: GENERATED,
  commit: process.env.GITHUB_SHA ?? null,
  report_template: report.analysis.versions.template,
  render_template: RENDER_TEMPLATE,
  synthetic_only: true,
  artifacts,
};
writeFileSync(new URL("manifest.json", OUT), JSON.stringify(manifest, null, 2) + "\n");
process.stdout.write(`wrote ${artifacts.length} T21 inspection artifacts to ${basename(OUT.pathname)}\n`);
