import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { chromium } from "playwright-core";

const BIN = new URL("../dist/render.mjs", import.meta.url).pathname;
const GENERATED = "2026-09-27T12:00:00Z";
const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/reports/view.${name}.json`, import.meta.url), "utf8"));

function html(view: unknown, layout: "A4" | "LETTER" | "CARD_SQUARE" | "CARD_STORY", locale: "en" | "sv") {
  const out = spawnSync(process.execPath, [BIN, "--html"], {
    input: JSON.stringify({ view, layout, locale, generated_at: GENERATED }),
    maxBuffer: 64 << 20,
    env: process.env,
    timeout: 90_000,
  });
  assert.equal(out.status, 0, out.stderr.toString());
  return out.stdout.toString();
}

async function browser() {
  return chromium.launch(process.env.PRINCESS_CHROMIUM ? { executablePath: process.env.PRINCESS_CHROMIUM } : {});
}

test("v2 Dossier print markup has bounded geometry and logical reading order", { timeout: 120_000 }, async () => {
  const instance = await browser();
  try {
    for (const [layout, width, height] of [["A4", 794, 1123], ["LETTER", 816, 1056]] as const) {
      for (const locale of ["en", "sv"] as const) {
        const page = await instance.newPage({ viewport: { width, height } });
        await page.emulateMedia({ media: "print", colorScheme: "light" });
        await page.setContent(html(fixture("export-v2-no-image"), layout, locale), { waitUntil: "load" });

        const result = await page.evaluate(() => {
          const root = document.documentElement;
          const headings = Array.from(document.querySelectorAll("h1,h2,h3")).map((node) => Number(node.tagName.slice(1)));
          const blocks = Array.from(document.querySelectorAll(
            ".pr-print-cover,.pr-first-reveal,.pr-dossier-body,.pr-colophon,table"
          ));
          const clipped = blocks.filter((node) => {
            const box = node.getBoundingClientRect();
            return box.left < -1 || box.right > window.innerWidth + 1;
          }).map((node) => (node as HTMLElement).className || node.tagName);
          const order = [".pr-print-cover", ".pr-first-reveal", ".pr-dossier-body", ".pr-colophon"]
            .map((selector) => document.querySelector(selector))
            .filter((node): node is Element => node !== null);
          const ordered = order.every((node, index) => index === 0 ||
            Boolean(order[index - 1]!.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING));
          return {
            overflow: root.scrollWidth - root.clientWidth,
            h1s: headings.filter((level) => level === 1).length,
            headingJump: headings.some((level, index) => index > 0 && level - headings[index - 1]! > 1),
            clipped,
            ordered,
            firstReveal: document.querySelectorAll(".pr-first-reveal [data-section^='section.highlight.']").length,
          };
        });

        assert.ok(result.overflow <= 0, `${layout}/${locale} horizontal overflow ${result.overflow}`);
        assert.equal(result.h1s, 1, `${layout}/${locale} must have one h1`);
        assert.equal(result.headingJump, false, `${layout}/${locale} heading hierarchy skips a level`);
        assert.deepEqual(result.clipped, [], `${layout}/${locale} clipped blocks`);
        assert.equal(result.ordered, true, `${layout}/${locale} reading order`);
        assert.ok(result.firstReveal >= 1, `${layout}/${locale} missing server-owned first reveal`);
        await page.close();
      }
    }
  } finally {
    await instance.close();
  }
});

test("share cards remain inside their fixed redacted canvas in both locales", { timeout: 120_000 }, async () => {
  const instance = await browser();
  try {
    for (const [layout, width, height] of [
      ["CARD_SQUARE", 1080, 1080],
      ["CARD_STORY", 1080, 1920],
    ] as const) {
      for (const locale of ["en", "sv"] as const) {
        const page = await instance.newPage({ viewport: { width, height } });
        await page.setContent(html(fixture("share-v2"), layout, locale), { waitUntil: "load" });
        const state = await page.evaluate(() => {
          const card = document.querySelector(".pr-card")!.getBoundingClientRect();
          return {
            width: card.width,
            height: card.height,
            scrollWidth: document.documentElement.scrollWidth,
            scrollHeight: document.documentElement.scrollHeight,
            images: document.querySelectorAll("img").length,
            facts: document.querySelectorAll("[data-fact-id]").length,
          };
        });
        assert.equal(state.width, width);
        assert.equal(state.height, height);
        assert.ok(state.scrollWidth <= width && state.scrollHeight <= height, `${layout}/${locale} overflow`);
        assert.equal(state.images, 0);
        assert.ok(state.facts > 0 && state.facts <= (layout === "CARD_STORY" ? 6 : 4));
        await page.close();
      }
    }
  } finally {
    await instance.close();
  }
});
