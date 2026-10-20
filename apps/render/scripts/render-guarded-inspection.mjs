// Render real individual-report/3 projections emitted by the guarded Python
// engine (not a hand-edited copy of a v2 report). Synthetic and rights-safe.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const OUT = new URL("../artifacts/t06-evidence-support-v3/", import.meta.url);
const STAMP = "2026-10-20T00:00:00Z";
const views = {
  export: JSON.parse(readFileSync(new URL("view.export-v3.synthetic.json", OUT), "utf8")),
  share: JSON.parse(readFileSync(new URL("view.share-v3.synthetic.json", OUT), "utf8")),
};
const report = JSON.parse(readFileSync(new URL("report-document-v3.synthetic.json", OUT), "utf8"));
if (report.analysis.versions.template !== "individual-report/3") {
  throw Error("inspection source must be genuine guarded v3");
}
const cases = [
  ["guarded-a4-en.pdf", "export", "A4", "en"],
  ["guarded-a4-sv.pdf", "export", "A4", "sv"],
  ["guarded-letter-en.pdf", "export", "LETTER", "en"],
  ["guarded-letter-sv.pdf", "export", "LETTER", "sv"],
  ["guarded-square-en.png", "share", "CARD_SQUARE", "en"],
  ["guarded-square-sv.png", "share", "CARD_SQUARE", "sv"],
  ["guarded-story-en.png", "share", "CARD_STORY", "en"],
  ["guarded-story-sv.png", "share", "CARD_STORY", "sv"],
];
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
function run(input, args = []) {
  const result = spawnSync(process.execPath, [BIN, ...args], {
    input: JSON.stringify(input), maxBuffer: 64 << 20, env: process.env, timeout: 120_000,
  });
  if (result.status !== 0) {
    throw Error("guarded renderer failed: " + result.stderr.toString().slice(0, 1000));
  }
  return result.stdout;
}
const artifacts = [];
for (const [file, source, layout, locale] of cases) {
  const view = views[source];
  const input = { view, layout, locale, generated_at: STAMP };
  const markup = run(input, ["--html"]).toString();
  const expected = locale === "en" ? "No supported handwriting measurements shown"
                                   : "Inga styrkta handskriftsmätvärden visas";
  if (source === "share") {
    if (!markup.includes(expected) || !markup.includes("pr-card-unqualified")
        || markup.includes("fact.SLANT_ANGLE_MEAN")) {
      throw Error(file + ": missing neutral share fallback or leaked slant");
    }
  } else {
    if (!markup.includes(locale === "en"
        ? "Handwriting structure could not be verified"
        : "Handskriftens struktur kunde inte verifieras")) {
      throw Error(file + ": missing suitability explanation");
    }
    if (!markup.includes(locale === "en"
        ? "Image properties remain available"
        : "Bildens egenskaper kan fortfarande mätas")) {
      throw Error(file + ": wrong image-only notice");
    }
    if (!markup.includes(locale === "en"
        ? "Premium is unavailable for this sample"
        : "Premium är inte tillgängligt för detta prov")) {
      throw Error(file + ": Premium wrongly appears available");
    }
    if (markup.includes(locale === "en" ? "Available with Premium" : "Ingår i Premium")) {
      throw Error(file + ": misleading Premium lock status");
    }
    const collapsed = (markup.match(/data-withheld-count=/g) ?? []).length;
    if (collapsed < 7) throw Error(file + ": unavailable families and sample facts were not compacted");
    const sample = markup.split('data-section="section.sample"')[1]?.split('data-section="section.size"')[0];
    if (!sample?.includes('data-withheld-count="6"')) {
      throw Error(file + ": six missing sample descriptors must be grouped, not printed as rows");
    }
    if (locale === "sv" && (!markup.includes("Provets lämplighet")
        || !markup.includes("Bläckegenskaper") || markup.includes(">Metric grid<"))) {
      throw Error(file + ": Swedish section heading localization failed");
    }
  }
  const bytes = run(input);
  writeFileSync(new URL(file, OUT), bytes);
  const pdf = file.endsWith(".pdf");
  const info = pdf ? { pages: (bytes.toString("latin1").match(/\/Type \/Page\b/g) ?? []).length }
    : { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  if (pdf && (info.pages < 1 || info.pages > 3)) {
    throw Error(file + ": unqualified PDF should fit within three pages");
  }
  if (!pdf && (info.width !== 1080 || info.height !== (layout === "CARD_STORY" ? 1920 : 1080))) {
    throw Error(file + ": invalid card dimensions");
  }
  artifacts.push({
    file, source_projection: view.projection, report_template: report.analysis.versions.template,
    locale, layout, bytes: bytes.length, sha256: sha256(bytes), ...info,
  });
}
writeFileSync(new URL("manifest.json", OUT), JSON.stringify({
  synthetic_only: true, source: "GraphologyEngine(evidence_guard_enabled=True) actual assembly/projection",
  report_template: report.analysis.versions.template,
  report_digest: report.document_digest, analysis_config: report.analysis.versions.analysis_config,
  commit: process.env.GITHUB_SHA ?? null,
  artifacts,
}, null, 2) + "\n");
console.log("PASS: guarded v3 render and text gates for " + artifacts.length + " EN/SV PDF/PNG artifacts");
