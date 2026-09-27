// Browser journeys over the shared synthetic view fixtures: the same facts
// every client renders, honest missing states, accessibility basics.
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/reports/view.${name}.json`, import.meta.url), "utf8"));

test("the free view renders every projected fact and no Premium section", async ({ page }) => {
  const view = fixture("free");
  await page.goto("/fixtures/free");
  await expect(page.getByRole("heading", { level: 1, name: "Free report" })).toBeVisible();
  await expect(page.locator("tr[data-fact-id]")).toHaveCount(
    new Set(view.sections.flatMap((s: { fact_ids: string[] }) => s.fact_ids)).size);
  await expect(page.locator(".pr-premium")).toHaveCount(0);
  await expect(page.locator("[data-evidence=AI_SYNTHESIS]")).toHaveCount(0);
});

test("missing measurements are explained, never shown as zero", async ({ page }) => {
  const view = fixture("free");
  const missing = view.facts.filter((f: { availability: string }) => f.availability === "MISSING");
  await page.goto("/fixtures/free");
  for (const fact of missing) {
    const cell = page.locator(`tr[data-fact-id="${fact.fact_id}"] td`).first();
    await expect(cell).toHaveText("Not measured in this sample");
  }
  expect(missing.length).toBeGreaterThan(0);
});

test("evidence classes are labelled in text, not colour alone", async ({ page }) => {
  await page.goto("/fixtures/free");
  const badges = page.locator(".pr-badge");
  expect(await badges.count()).toBeGreaterThan(0);
  for (const text of await badges.allInnerTexts()) expect(text.trim().length).toBeGreaterThan(2);
});

test("premium overlays are labelled as AI-assisted next to unchanged facts", async ({ page }) => {
  await page.goto("/fixtures/owner-premium");
  await expect(page.locator(".pr-premium [data-evidence=AI_SYNTHESIS]").first()).toContainText("AI-assisted");
});

test("share and export previews disclose that the source image is omitted", async ({ page }) => {
  for (const name of ["share", "export-no-image"]) {
    await page.goto(`/fixtures/${name}`);
    await expect(page.locator("[data-image=omitted]")).toContainText("Source image omitted");
  }
});

test("disabled actions explain why", async ({ page }) => {
  await page.goto("/fixtures/free");
  const purchase = page.getByRole("button", { name: "Get Premium" });
  await expect(purchase).toBeDisabled();
  const describedBy = await purchase.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`)).not.toBeEmpty();
});

test("keyboard users reach the content first and focus is visible", async ({ page }) => {
  await page.goto("/fixtures/free");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  const outline = await skip.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
});

test("Swedish labels fit a 320px screen without horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/free?locale=sv");
  await expect(page.getByRole("heading", { level: 1, name: "Gratisrapport" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("dark mode swaps the surface token", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/fixtures/free");
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(20, 18, 23)");
});

test("security headers are set and unknown proxy routes are refused", async ({ page, request }) => {
  const response = await page.goto("/");
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect((await request.get("/api/v1/admin/users")).status()).toBe(404);
  const crossSite = await request.post("/api/v1/uploads", { data: { media_type: "image/png" },
                                                             headers: { origin: "https://evil.example" } });
  expect(crossSite.status()).toBe(403);
});
