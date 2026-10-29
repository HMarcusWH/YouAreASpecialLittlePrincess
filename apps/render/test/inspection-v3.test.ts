import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { chromium } from "playwright-core";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const GENERATED = "2026-09-27T12:00:00Z";
const view = JSON.parse(readFileSync(
  new URL("../../../fixtures/reports/view.export-v2-no-image.json", import.meta.url), "utf8",
));
const evidence = JSON.parse(readFileSync(
  new URL("../../../fixtures/reports/evidence-bundle.v2.json", import.meta.url), "utf8",
));

function html(layout: "A4" | "LETTER", detail: "SUMMARY" | "FULL", locale: "en" | "sv"): string {
  const saved = structuredClone(view);
  saved.locale = locale === "en" ? "en" : "sv-SE";
  const input = {
    contract_version: "1.0.0", renderer_version: "render-template/3",
    view: saved, premium: null, evidence, source_image: null,
    layout, detail, locale, generated_at: GENERATED,
    presentation_version: "presentation/1", render_policy_version: "render-policy/3",
  };
  const result = spawnSync(process.execPath, [BIN, "--envelope-v3", "--html"], {
    input: JSON.stringify(input), maxBuffer: 64 << 20, env: process.env, timeout: 90_000,
  });
  assert.equal(result.status, 0, result.stderr.toString());
  return result.stdout.toString();
}

test("v3 summary/full PDFs retain logical EN/SV print order without clipped sections", { timeout: 180_000 }, async () => {
  const browser = await chromium.launch(
    process.env.PRINCESS_CHROMIUM ? { executablePath: process.env.PRINCESS_CHROMIUM } : {});
  try {
    for (const [layout, w, h] of [["A4", 794, 1123], ["LETTER", 816, 1056]] as const) {
      for (const locale of ["en", "sv"] as const) {
        for (const detail of ["SUMMARY", "FULL"] as const) {
          const page = await browser.newPage({ viewport: { width: w, height: h } });
          await page.emulateMedia({ media: "print", colorScheme: "light" });
          await page.setContent(html(layout, detail, locale), { waitUntil: "load" });
          const result = await page.evaluate(() => {
            const headings = Array.from(document.querySelectorAll("h1,h2,h3"))
              .map((node) => Number(node.tagName.slice(1)));
            const keys = [".pr-print-cover", ".pr-first-reveal", ".pr-dossier-body", ".pr-colophon"];
            const blocks = keys.map((key) => document.querySelector(key)).filter(
              (node): node is Element => node !== null);
            const order = blocks.every((node, index) => index === 0 ||
              Boolean(blocks[index - 1]!.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING));
            const escaped = Array.from(document.querySelectorAll("script")).length;
            const clipped = Array.from(document.querySelectorAll(
              ".pr-print-cover,.pr-first-reveal,.pr-dossier-body,.pr-colophon,table"))
              .filter((node) => {
                const box = node.getBoundingClientRect();
                return box.left < -1 || box.right > window.innerWidth + 1;
              }).length;
            return {
              h1: headings.filter((level) => level === 1).length,
              jumps: headings.some((level, index) => index > 0 &&
                level - headings[index - 1]! > 1),
              overflow: document.documentElement.scrollWidth - window.innerWidth,
              order, clipped, escaped,
              detail: document.body.getAttribute("data-render-detail"),
              factRows: document.querySelectorAll("[data-fact-id]").length,
              images: document.querySelectorAll(".pr-v3-source image").length,
            };
          });
          assert.equal(result.h1, 1, layout + "/" + locale + "/" + detail);
          assert.equal(result.jumps, false);
          assert.ok(result.overflow <= 0, "horizontal print overflow");
          assert.equal(result.clipped, 0, "clipped print elements");
          assert.equal(result.order, true);
          assert.equal(result.escaped, 0);
          assert.equal(result.images, 0);
          assert.equal(result.detail, detail);
          assert.ok(result.factRows > (detail === "SUMMARY" ? 0 : 60));
          await page.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
});
