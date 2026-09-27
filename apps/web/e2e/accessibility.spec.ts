import { expect, test } from "@playwright/test";

import { analyzeAccessibility, expectAccessible } from "./support/accessibility.ts";

for (const [name, url] of [
  ["start", "/start"],
  ["free report", "/fixtures/free"],
  ["report history", "/fixtures/history"],
  ["empty report history", "/fixtures/history?empty=1"],
  ["stored evidence integrity warning", "/fixtures/evidence-errors?error=stored_evidence_invalid"],
  ["evidence lineage warning", "/fixtures/evidence-errors?error=evidence_lineage_invalid"],
  ["settings", "/settings"],
] as const) {
  test(name + " has no automated WCAG A/AA violations", async ({ page }, testInfo) => {
    await page.goto(url);
    await expectAccessible(page, testInfo);
  });
}

test("representative Swedish narrow report remains accessible", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/free?locale=sv");
  await expect(page.getByRole("heading", { level: 1, name: "Gratisrapport" })).toBeVisible();
  await expectAccessible(page, testInfo);
});

test("representative Swedish narrow history remains accessible", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/history?locale=sv");
  await expect(page.getByRole("heading", { level: 1, name: "Dina rapporter" })).toBeVisible();
  await expectAccessible(page, testInfo);
});

test("dark report remains accessible", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/fixtures/free");
  await expectAccessible(page, testInfo);
});

test("reduced-motion report remains accessible", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/fixtures/free");
  await expectAccessible(page, testInfo);
});

test("destructive settings action can be cancelled from the keyboard", async ({ page }, testInfo) => {
  await page.goto("/settings");
  page.once("dialog", async (dialog) => dialog.dismiss());
  const remove = page.getByRole("button", { name: "Delete my account" });
  await remove.focus();
  await page.keyboard.press("Enter");
  await expect(remove).toBeFocused();
  await expectAccessible(page, testInfo);
});

test("the accessibility gate detects a deliberately unnamed control", async ({ page }) => {
  await page.goto("/fixtures/a11y-negative");
  const results = await analyzeAccessibility(page);
  expect(results.violations.map((v) => v.id)).toContain("button-name");
});
