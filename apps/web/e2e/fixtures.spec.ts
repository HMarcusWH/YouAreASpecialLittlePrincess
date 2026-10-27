// Browser journeys over the shared synthetic view fixtures: the same facts
// every client renders, honest missing states, accessibility basics.
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const fixture = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../../fixtures/reports/view.${name}.json`, import.meta.url), "utf8"));

const designTokens = JSON.parse(
  readFileSync(new URL("../../../packages/design-tokens/tokens.json", import.meta.url), "utf8"),
);

const cssRgb = (hex: string) => {
  const value = hex.replace("#", "");
  const channels = [0, 2, 4].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16));
  return `rgb(${channels.join(", ")})`;
};

test("public web chrome uses the Inktrospect brand", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Inktrospect — handwriting measured");
  await expect(page.locator(".site-header .brand")).toHaveText("Inktrospect");
  await expect(page.locator(".site-header")).not.toContainText("Princess");
});

test("the free view renders every projected fact and no Premium section", async ({ page }) => {
  const view = fixture("free");
  await page.goto("/fixtures/free");
  await expect(page.getByRole("heading", { level: 1, name: "Free report" })).toBeVisible();
  await expect(page.locator("tr[data-fact-id]")).toHaveCount(
    new Set(view.sections.flatMap((s: { fact_ids: string[] }) => s.fact_ids)).size);
  await expect(page.locator(".pr-premium")).toHaveCount(0);
  await expect(page.locator("[data-evidence=AI_SYNTHESIS]")).toHaveCount(0);
});

test("the v2 fixture renders the real server-owned first reveal", async ({ page }) => {
  const view = fixture("free-v2");
  const primary = view.sections.find((section: { template: string }) => section.template === "HIGHLIGHT_PRIMARY");
  expect(primary?.content_ids).toEqual(["content.highlight.v1.slant.right.almost_all"]);
  expect(primary?.fact_ids).toEqual(["fact.SLANT_RIGHT_FRACTION"]);

  await page.goto("/fixtures/free-v2");
  const reveal = page.getByRole("region", { name: "What stands out" });
  await expect(reveal).toBeVisible();
  await expect(reveal.getByText("Almost every accepted slant observation leans right.")).toBeVisible();
  await expect(reveal.getByRole("rowheader", { name: "Fraction of right-slanted strokes" })).toBeVisible();
  await expect(page.getByText("content.highlight.v1.slant.right.almost_all")).toHaveCount(0);
});

test("v4 Free story copy resolves in EN/SV on the web without changing saved measurements", async ({ page }) => {
  await page.goto("/fixtures/story-v4-copy");
  const slant = page.locator('[data-section="section.slant"]');
  await expect(slant.getByRole("heading", { name: "Slant and direction" })).toBeVisible();
  await expect(slant).toContainText("The diagram shows the directions of the measured strokes.");
  await expect(page.locator('[data-section="section.ink"]')).toContainText(
    "Explore visible ink darkness and thickness, not physical pen pressure.");
  await expect(page.getByText("content.chapter.v2.slant.neutral")).toHaveCount(0);
  await page.goto("/fixtures/story-v4-copy?locale=sv");
  const swedish = page.locator('[data-section="section.slant"]');
  await expect(swedish.getByRole("heading", { name: "Lutning och riktning" })).toBeVisible();
  await expect(swedish).toContainText("Diagrammet visar riktningarna hos de uppmätta strecken.");
  await expect(page.locator("[data-evidence=AI_SYNTHESIS]")).toHaveCount(0);
});

test("v4 unknown copy fails visibly instead of substituting a historical claim", async ({ page }) => {
  await page.goto("/fixtures/story-v4-unknown");
  await expect(page.locator('[data-section="section.slant"]')).toContainText(
    "The reviewed description for this saved section is not installed in this app version.");
  await expect(page.getByText("content.chapter.v2.slant.unreviewed")).toHaveCount(0);
});

test("legacy v1 reports remain readable without a first reveal", async ({ page }) => {
  await page.goto("/fixtures/free");
  await expect(page.locator(".pr-first-reveal")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Free report" })).toBeVisible();
  await expect(page.getByText("Mechanical dossier")).toBeVisible();
});

test("the no-eligible first reveal renders only the reviewed fallback", async ({ page }) => {
  await page.goto("/fixtures/free-v2-no-highlight");
  const reveal = page.locator(".pr-first-reveal");
  await expect(reveal).toBeVisible();
  await expect(reveal.getByRole("heading", { name: "What stands out" })).toBeVisible();
  await expect(reveal.getByText("No single mechanical pattern met the first-reveal rules for this sample.")).toBeVisible();
  await expect(reveal.locator("tr[data-fact-id]")).toHaveCount(0);
  await expect(page.getByText("content.highlight.v1.none")).toHaveCount(0);
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

test("disabled actions explain why with localized product copy", async ({ page }) => {
  await page.goto("/fixtures/free");

  for (const [name, reason] of [
    ["Compare", "Comparison is not available yet."],
    ["Share", "Share links are not available yet."],
    ["Save", "Reports are saved to your account automatically."],
    ["Delete", "Delete the sample in Settings to remove this report."],
  ] as const) {
    const action = page.getByRole("button", { name });
    await expect(action).toBeDisabled();
    const reasonId = await action.getAttribute("aria-describedby");
    expect(reasonId).toBeTruthy();
    await expect(page.locator(`[id="${reasonId}"]`)).toHaveText(reason);
  }
  await expect(page.getByRole("button", { name: "Export PDF" })).toBeEnabled();

  let purchase = page.getByRole("button", { name: "Get Premium" });
  await expect(purchase).toBeDisabled();
  let describedBy = await purchase.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`)).toHaveText("Premium is not available yet.");

  await page.goto("/fixtures/owner-premium");
  purchase = page.getByRole("button", { name: "Get Premium" });
  await expect(purchase).toBeDisabled();
  describedBy = await purchase.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`))
    .toHaveText("Premium is already unlocked for this report.");

  await page.goto("/fixtures/free?locale=sv");
  purchase = page.getByRole("button", { name: "Skaffa Premium" });
  describedBy = await purchase.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`)).toHaveText("Premium är inte tillgängligt ännu.");

  await page.goto("/fixtures/owner-premium?locale=sv");
  purchase = page.getByRole("button", { name: "Skaffa Premium" });
  describedBy = await purchase.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`[id="${describedBy}"]`))
    .toHaveText("Premium är redan upplåst för den här rapporten.");
});

test("keyboard users reach the content first and focus is visible", async ({ page }) => {
  await page.goto("/fixtures/free");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  const outline = await skip.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
});

test("Swedish v2 Dossier labels fit a 320px screen without horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/free-v2?locale=sv");
  await expect(page.getByRole("heading", { level: 1, name: "Gratisrapport" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("the v2 Dossier remains usable at 200% text size", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 900 });
  await page.goto("/fixtures/free-v2?locale=sv");
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await expect(page.getByText("Personlig dossier")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("dark mode swaps the surface token", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/fixtures/free");
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe(cssRgb(designTokens.color.dark.surface));
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


test("stored evidence renders baseline geometry, spacing rows and raw slant observations accessibly", async ({ page }) => {
  await page.goto("/fixtures/free");
  await expect(page.getByRole("heading", { level: 2, name: "Evidence behind the measurements" })).toBeVisible();
  const graphics = page.getByRole("img", { name: /Line \d/ });
  expect(await graphics.count()).toBeGreaterThan(0);
  for (let i = 0; i < await graphics.count(); i += 1) {
    const graphic = graphics.nth(i);
    await expect(graphic.locator("title")).not.toBeEmpty();
    await expect(graphic.locator("desc")).not.toBeEmpty();
  }
  await expect(page.getByRole("heading", { name: "Mean interline whitespace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Slant observations" })).toBeVisible();
  await expect(page.getByText("Raw observations are shown here because a reviewed fixed histogram scale is not defined yet."))
    .toBeVisible();
  expect(await page.locator(".pr-evidence-table tbody tr").count()).toBeGreaterThan(0);
});

test("report history has populated, empty and long Swedish states without horizontal overflow", async ({ page }) => {
  await page.goto("/fixtures/history");
  await expect(page.getByRole("heading", { level: 1, name: "Your reports" })).toBeVisible();
  await expect(page.locator(".report-list-item")).toHaveCount(3);
  await expect(page.getByRole("link", { name: "Older reports" })).toBeVisible();

  await page.goto("/fixtures/history?empty=1");
  await expect(page.getByText("You do not have any saved reports yet.")).toBeVisible();

  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/history?locale=sv");
  await expect(page.getByRole("heading", { level: 1, name: "Dina rapporter" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

// The source image below is a synthetic-only Playwright mock, never a real
// user's handwriting or an image used by measurement/model production.
const sourceSvg = (width: number, height: number) => (
  `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#faf4e8"/><path d="M80,130 L220,140 M80,210 L220,205" stroke="#444" stroke-width="3"/></svg>`
);

test("the owner Free Dossier navigates only stored source regions, with keyboard controls and Swedish copy", async ({ page }) => {
  await page.route("**/api/v1/reports/*/source-image", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: sourceSvg(900, 360) });
  });
  await page.goto("/fixtures/source-v4?locale=sv");
  const plate = page.locator("#source-evidence-plate");
  await expect(plate.getByRole("heading", { name: "Din handstil" })).toBeVisible();
  await expect(plate.locator("img")).toHaveJSProperty("naturalWidth", 900);
  await expect(plate.locator(".pr-source-outline")).toHaveCount(0);
  const baseline = page.locator('[data-section="section.baseline"]');
  const inspect = baseline.getByRole("button", { name: "Granska källregion" });
  await inspect.focus();
  await page.keyboard.press("Enter");
  await expect(plate).toBeFocused();
  const region = plate.locator(".pr-source-count");
  await expect(region).toContainText("line_");
  await expect(plate.locator(".pr-source-outline polyline")).toHaveCount(1);
  const first = await region.textContent();
  const next = plate.getByRole("button", { name: "Nästa" });
  await expect(next).toBeEnabled();
  await next.click();
  await expect(region).not.toHaveText(first!);
  await plate.getByRole("button", { name: "Föregående" }).click();
  await expect(region).toHaveText(first!);
  await expect(page.locator("[data-evidence=AI_SYNTHESIS]")).toHaveCount(0);
});

test("a mismatched image frame refuses the overlay, never guessing coordinates", async ({ page }) => {
  await page.route("**/api/v1/reports/*/source-image", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: sourceSvg(200, 100) });
  });
  await page.goto("/fixtures/source-v4");
  await page.locator('[data-section="section.slant"]').getByRole("button", { name: "Inspect source region" }).click();
  await expect(page.locator("#source-evidence-plate")).toContainText(
    "The stored image does not match the measured frame");
  await expect(page.locator(".pr-source-outline")).toHaveCount(0);
});

test("revoked or denied source rights never display or retain a writing image", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/v1/reports/*/source-image", async (route) => {
    requests += 1;
    await route.fulfill({ status: 403, contentType: "application/json", body: '{"error":"not_authorized"}' });
  });
  await page.goto("/fixtures/source-v4?revoke=1");
  await expect(page.locator("#source-evidence-plate")).toContainText(
    "The source image is no longer stored");
  await expect(page.locator(".pr-inspect-source")).toHaveCount(0);
  expect(requests).toBe(0);
  await page.goto("/fixtures/source-v4");
  await expect(page.locator("#source-evidence-plate")).toContainText(
    "The source image is no longer stored");
  // SSR image fetching and hydration may legitimately cause multiple
  // requests. Each is reauthorized and every denial remains fail-closed.
  expect(requests).toBeGreaterThanOrEqual(1);
  await expect(page.locator(".pr-source-outline")).toHaveCount(0);
});

test("the inspector survives narrow Swedish and 200-percent text without horizontal overflow", async ({ page }) => {
  await page.route("**/api/v1/reports/*/source-image", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: sourceSvg(900, 360) });
  });
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/fixtures/source-v4?locale=sv");
  await page.locator('[data-section="section.baseline"]').getByRole("button", { name: "Granska källregion" }).click();
  const narrowOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(narrowOverflow).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 640, height: 900 });
  await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
  await expect(page.locator(".pr-source-count")).toBeVisible();
  const enlargedOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(enlargedOverflow).toBeLessThanOrEqual(0);
});
