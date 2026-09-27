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

async function mockAccountNotificationPreferences(
  page: import("@playwright/test").Page,
  options: { loadFails?: boolean; saveFails?: boolean } = {},
) {
  await page.route("**/api/v1/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ principal_id: "prn_accessibility", kind: "ACCOUNT" }) });
  });
  await page.route("**/api/v1/me/notification-preferences", async (route) => {
    if (route.request().method() === "GET") {
      if (options.loadFails) {
        await route.fulfill({ status: 503, contentType: "application/json",
          body: JSON.stringify({ error: "temporarily_unavailable" }) });
      } else {
        await route.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify({ mail_report_ready: false, locale: "en" }) });
      }
      return;
    }
    if (options.saveFails) {
      await route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ error: "temporarily_unavailable" }) });
      return;
    }
    const body = route.request().postDataJSON() as { mail_report_ready: boolean; locale: string };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test("mail preference is keyboard-operable and fits a 320px viewport", async ({ page }, testInfo) => {
  await mockAccountNotificationPreferences(page);
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/settings");

  const preference = page.getByRole("checkbox", { name: "Email me when a report is ready" });
  await expect(preference).toBeVisible();
  await preference.focus();
  await page.keyboard.press("Space");
  await expect(preference).toBeChecked();
  await page.keyboard.press("Tab");

  const save = page.getByRole("button", { name: "Save email preference" });
  await expect(save).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toHaveText("Email preference saved.");

  const noHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(noHorizontalOverflow).toBe(true);
  await expectAccessible(page, testInfo);
});

test("mail preference load failure is announced and remains accessible", async ({ page }, testInfo) => {
  await mockAccountNotificationPreferences(page, { loadFails: true });
  await page.goto("/settings");
  await expect(page.getByRole("alert")).toHaveText("Email preferences could not be loaded. Please try again.");
  await expect(page.getByRole("checkbox", { name: "Email me when a report is ready" })).toHaveCount(0);
  await expectAccessible(page, testInfo);
});

test("mail preference save failure restores the confirmed value and remains accessible", async ({ page }, testInfo) => {
  await mockAccountNotificationPreferences(page, { saveFails: true });
  await page.goto("/settings");

  const preference = page.getByRole("checkbox", { name: "Email me when a report is ready" });
  await expect(preference).not.toBeChecked();
  await preference.check();
  await page.getByRole("button", { name: "Save email preference" }).click();

  await expect(page.getByRole("alert")).toHaveText(
    "Email preference could not be saved. Your previous setting is unchanged.",
  );
  await expect(preference).not.toBeChecked();
  await expectAccessible(page, testInfo);
});

test("the accessibility gate detects a deliberately unlabelled control", async ({ page }) => {
  await page.setContent("<!doctype html><html lang=\"en\"><head><title>axe negative control</title></head><body><main><input type=\"text\"></main></body></html>");
  const results = await analyzeAccessibility(page);
  expect(results.violations.map((v) => v.id)).toContain("label");
});
