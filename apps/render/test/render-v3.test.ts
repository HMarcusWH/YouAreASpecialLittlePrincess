import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { deflateSync } from "node:zlib";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const GENERATED = "2026-09-27T12:00:00Z";
const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL("../../../fixtures/reports/" + name, import.meta.url), "utf8"));

function crc(bytes: Buffer): number {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) {
      value = (value & 1) ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
    }
  }
  return (value ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const name = Buffer.from(type, "ascii");
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  name.copy(out, 4);
  data.copy(out, 8);
  out.writeUInt32BE(crc(Buffer.concat([name, data])), 8 + data.length);
  return out;
}

// Programmatically generated image: no real handwriting, real person, or PII.
function syntheticPng(width = 900, height = 360): Buffer {
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    const begin = y * (width * 3 + 1);
    raw[begin] = 0;
    for (let x = 0; x < width; x++) {
      const p = begin + 1 + 3 * x;
      const ink = y >= 150 && y < 160 && x >= 100 && x < 600;
      raw[p] = ink ? 24 : 246;
      raw[p + 1] = ink ? 24 : 246;
      raw[p + 2] = ink ? 24 : 246;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function envelope(options: { withImage?: boolean; detail?: "SUMMARY" | "FULL";
                             layout?: "A4" | "LETTER" | "CARD_SQUARE" | "CARD_STORY"; locale?: "en" | "sv" } = {}) {
  const layout = options.layout ?? "A4";
  const card = layout === "CARD_SQUARE" || layout === "CARD_STORY";
  const view = fixture(card ? "view.share-v2.json" : "view.export-v2-no-image.json");
  // Both languages exercise rendering over synthetic saved fixtures; the
  // production application keeps an actual immutable report locale.
  view.locale = options.locale === "en" ? "en" : "sv-SE";
  const evidence = card ? null : fixture("evidence-bundle.v2.json");
  if (options.withImage) {
    assert.ok(evidence !== null);
    view.authorized_asset_ids = [evidence.analysis.input_asset_id];
    view.notices = view.notices.filter((n: { localization_key: string }) =>
      n.localization_key !== "notice.source_image_omitted");
  }
  const bytes = options.withImage ? syntheticPng() : null;
  const source_image = bytes === null ? null : {
    media_type: "image/png", sha256: createHash("sha256").update(bytes).digest("hex"),
    width: 900, height: 360, data_base64_chunks: [bytes.toString("base64")],
  };
  return {
    contract_version: "1.0.0", renderer_version: "render-template/3",
    view, premium: null, evidence, source_image,
    layout, detail: options.detail ?? "SUMMARY", locale: options.locale ?? "sv",
    generated_at: GENERATED, presentation_version: "presentation/1",
    render_policy_version: "render-policy/3",
  };
}

function run(input: unknown, ...args: string[]) {
  const result = spawnSync(process.execPath, [BIN, ...args], {
    input: typeof input === "string" ? input : JSON.stringify(input),
    maxBuffer: 64 << 20, env: process.env, timeout: 120_000,
  });
  return { status: result.status, out: result.stdout, error: result.stderr.toString().trim() };
}

test("v3 must be explicitly selected; v2 renderer contract remains unchanged", () => {
  const v3 = envelope();
  const wrong = run(v3, "--html");
  assert.equal(wrong.status, 2);
  assert.equal(wrong.error, "render_v3_requires_explicit_mode");
  const legacy = run({
    view: fixture("view.export-v2-no-image.json"), layout: "A4", locale: "en", generated_at: GENERATED,
  }, "--html");
  assert.equal(legacy.status, 0, legacy.error);
  assert.ok(legacy.out.toString().includes("Inktrospect"));
  assert.ok(!legacy.out.toString().includes('data-render-template="render-template/3"'));
});

test("v3 SUMMARY and FULL preserve saved source facts with a distinct editorial density", () => {
  for (const locale of ["en", "sv"] as const) {
    const summary = run(envelope({ detail: "SUMMARY", locale }), "--envelope-v3", "--html");
    const full = run(envelope({ detail: "FULL", locale }), "--envelope-v3", "--html");
    assert.equal(summary.status, 0, summary.error);
    assert.equal(full.status, 0, full.error);
    const s = summary.out.toString();
    const f = full.out.toString();
    assert.ok(s.includes('data-render-template="render-template/3"'));
    assert.ok(s.includes('data-render-detail="SUMMARY"') && f.includes('data-render-detail="FULL"'));
    assert.ok(s.includes("pr-first-reveal") && s.includes("pr-dossier"));
    assert.ok((s.match(/data-fact-id=/g) ?? []).length < (f.match(/data-fact-id=/g) ?? []).length);
    assert.ok((f.match(/data-fact-id=/g) ?? []).length >= 64);
    assert.ok(f.includes("pr-fact-provenance"));
    assert.ok(f.includes("default-src &#39;none&#39;"));
    assert.ok(!s.includes("data:image/") && !f.includes("data:image/"));
    assert.ok(!f.includes("<script"));
  }
});

test("v3 source preview uses only the verified inline raster and saved regions", () => {
  const render = run(envelope({ withImage: true, detail: "FULL" }), "--envelope-v3", "--html");
  assert.equal(render.status, 0, render.error);
  const html = render.out.toString();
  assert.ok(html.includes('data-source-evidence="authorized"'));
  assert.ok(html.includes("data:image/png;base64,"));
  assert.ok(html.includes("img-src data:;"));
  assert.ok(html.includes("data-region-id="));
  assert.ok(!/<(?:img|image)\s[^>]*(?:src|href)="https?:/i.test(html));
  assert.ok(!html.includes("<script"));
});

test("v3 Free share cards cannot carry original handwriting or paid sections", () => {
  for (const layout of ["CARD_SQUARE", "CARD_STORY"] as const) {
    const candidate = envelope({ layout });
    const success = run(candidate, "--envelope-v3", "--html");
    assert.equal(success.status, 0, success.error);
    assert.ok(success.out.toString().includes("pr-card"));
    assert.ok(!success.out.toString().includes("data:image/"));
    candidate.source_image = envelope({ withImage: true }).source_image;
    const refused = run(candidate, "--envelope-v3");
    assert.equal(refused.status, 2);
    assert.equal(refused.error, "render_v3_share_source_forbidden");
  }
});

test("v3 rejects forged versions, paid scope and mixed revision timestamps", () => {
  const wrong = [
    ["contract_version", "2.0.0", "render_v3_version_invalid"],
    ["renderer_version", "render-template/2", "render_v3_version_invalid"],
    ["render_policy_version", "render-policy/2", "render_v3_version_invalid"],
    ["presentation_version", "presentation/3", "render_v3_version_invalid"],
    ["detail", "VERBOSE", "render_v3_options_invalid"],
    ["locale", "de", "render_v3_options_invalid"],
    ["layout", "POSTER", "render_v3_options_invalid"],
  ] as const;
  for (const [key, value, error] of wrong) {
    const candidate = { ...envelope(), [key]: value };
    const refused = run(candidate, "--envelope-v3");
    assert.equal(refused.status, 2, key);
    assert.equal(refused.error, error, key);
  }
  const premium: Record<string, unknown> = envelope();
  premium.premium = { fake: "paid" };
  assert.equal(run(premium, "--envelope-v3").error, "render_v3_premium_not_released");
  const same = envelope();
  same.view.generated_at = "2026-10-01T00:00:00Z";
  assert.equal(run(same, "--envelope-v3").error, "render_v3_view_source_mismatch");
  const forged = envelope();
  forged.view.sections[0].premium_section_id = "premium.synthetic";
  assert.equal(run(forged, "--envelope-v3").error, "render_v3_view_source_mismatch");
});

test("v3 raster rejects hashes, altered chunks, remote URLs, mismatched dimensions and unsupported mime", () => {
  const valid = envelope({ withImage: true });
  assert.ok(valid.source_image);
  for (const change of [
    { sha256: "0".repeat(64) }, { media_type: "image/svg+xml" },
    { width: 899 }, { height: 359 },
    { data_base64_chunks: ["data:text/html,<script>x</script>"] },
    { data_base64_chunks: ["AAAA===="] },
    { data_base64_chunks: ["a".repeat(65_537)] },
  ]) {
    const candidate = envelope({ withImage: true });
    candidate.source_image = { ...candidate.source_image!, ...change };
    const refused = run(candidate, "--envelope-v3");
    assert.equal(refused.status, 2, JSON.stringify(change).slice(0,120));
    assert.match(refused.error, /^render_v3_/);
    assert.equal(refused.out.length, 0);
  }
});

test("v3 image never bypasses evidence, current asset authority or source frame", () => {
  const without = envelope({ withImage: true });
  without.evidence = null;
  assert.equal(run(without, "--envelope-v3").error, "render_v3_source_evidence_required");
  const withoutAsset = envelope({ withImage: true });
  withoutAsset.view.authorized_asset_ids = [];
  assert.equal(run(withoutAsset, "--envelope-v3").error, "render_v3_source_not_authorized");
  const badFrame = envelope({ withImage: true });
  badFrame.evidence.frames[0].width = 100;
  assert.equal(run(badFrame, "--envelope-v3").error, "render_v3_source_frame_invalid");
  const missingRegion = envelope();
  missingRegion.view.facts[0].source_region_ids = ["region_not_from_source"];
  assert.equal(run(missingRegion, "--envelope-v3").error, "render_v3_region_lineage_invalid");
});

test("v3 cannot smuggle unknown envelope fields or oversized input into the child process", () => {
  const extra = { ...envelope(), source_url: "https://private.invalid/handwriting.png" };
  assert.equal(run(extra, "--envelope-v3").error, "render_v3_shape_invalid");
  const huge = " ".repeat(8 * 1024 * 1024 + 1);
  const overflow = run(huge, "--envelope-v3");
  assert.equal(overflow.status, 2);
  assert.equal(overflow.error, "input_too_large");
});

test("v3 produces tagged A4 and Letter PDF output in both languages", { timeout: 240_000 }, () => {
  for (const layout of ["A4", "LETTER"] as const) {
    for (const locale of ["en", "sv"] as const) {
      const result = run(envelope({ layout, locale, detail: "SUMMARY" }), "--envelope-v3");
      assert.equal(result.status, 0, result.error);
      const bytes = result.out.toString("latin1");
      assert.ok(bytes.startsWith("%PDF-"), layout);
      assert.ok(bytes.includes("/StructTreeRoot"), layout);
      assert.ok((bytes.match(/\/Type \/Page\b/g) ?? []).length > 0);
      const box = /\/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]/.exec(bytes);
      assert.ok(box, layout);
      const expected = layout === "LETTER" ? [612, 792] : [595.92, 842.88];
      assert.ok(Math.abs(Number(box[1]) - expected[0]!) < 1);
      assert.ok(Math.abs(Number(box[2]) - expected[1]!) < 1);
    }
  }
});

test("v3 embeds the verified synthetic source in an actual tagged PDF", { timeout: 120_000 }, () => {
  const result = run(envelope({ withImage: true, detail: "FULL" }), "--envelope-v3");
  assert.equal(result.status, 0, result.error);
  const pdf = result.out.toString("latin1");
  assert.ok(pdf.startsWith("%PDF-"));
  assert.ok(pdf.includes("/StructTreeRoot"));
  assert.ok(pdf.includes("/Subtype /Image"), "the source is actually embedded as PDF imagery");
  assert.ok(result.out.byteLength < 10 * 1024 * 1024);
});
