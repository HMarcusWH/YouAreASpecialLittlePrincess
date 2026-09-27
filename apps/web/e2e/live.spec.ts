import { writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { expectAccessible } from "./support/accessibility.ts";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(name + " is required for the live web qualification");
  return value;
}

const api = required("PRINCESS_E2E_API");
const sample = required("PRINCESS_E2E_SAMPLE");
const workerGate = required("PRINCESS_E2E_WORKER_GATE");

test("upload, refresh queued work, report, history and export without any AI provider", async ({ page }, testInfo) => {
  expect((await page.goto("/fixtures/free"))!.status()).toBe(404);

  await page.goto("/start");
  await expectAccessible(page, testInfo);
  await page.setInputFiles("#photo", sample);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Analyse my handwriting" }).click();
  await expect(page).toHaveURL(/\/analyses\/run_/, { timeout: 30_000 });
  const runUrl = page.url();

  await page.reload();
  await expect(page).toHaveURL(runUrl);
  await expectAccessible(page, testInfo);
  writeFileSync(workerGate, "start\n", { encoding: "utf8", flag: "wx" });

  await expect(page).toHaveURL(/\/reports\/report_/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Your report" })).toBeVisible();
  expect(await page.locator("tr[data-fact-id]").count()).toBeGreaterThan(10);
  await expect(page.getByText("No reference group is available yet")).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Evidence behind the measurements" })).toBeVisible();
  expect(await page.locator(".pr-baseline-figure").count()).toBeGreaterThan(0);
  await expectAccessible(page, testInfo);

  const reportUrl = page.url();
  await page.goto("/reports");
  await expect(page.getByRole("heading", { level: 1, name: "Your reports" })).toBeVisible();
  await expect(page.locator(".report-list-item")).toHaveCount(1);
  await expectAccessible(page, testInfo);
  await page.goto(reportUrl);

  await page.getByRole("button", { name: "Export PDF" }).click();
  const download = page.getByRole("link", { name: "Download PDF" });
  await expect(download).toBeVisible({ timeout: 60_000 });
  await expectAccessible(page, testInfo);
  const pdf = await page.request.get(new URL((await download.getAttribute("href"))!, page.url()).toString());
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();

  await page.goto(runUrl);
  await expect(page).toHaveURL(reportUrl, { timeout: 30_000 });

  const stranger = await page.context().browser()!.newContext();
  const other = await stranger.newPage();
  const origin = new URL(reportUrl).origin;
  expect((await other.request.post(origin + "/api/session/guest", { headers: { origin } })).status()).toBe(201);
  const response = await other.goto(reportUrl);
  expect(response!.status()).toBe(404);
  await expect(other.locator("tr[data-fact-id]")).toHaveCount(0);
  const reportId = reportUrl.split("/").pop();
  expect((await other.request.get(origin + "/api/v1/reports/" + reportId + "/evidence")).status()).toBe(404);
  await other.goto(origin + "/reports");
  await expect(other.locator(".report-list-item")).toHaveCount(0);
  await stranger.close();

  const anonymous = await page.context().browser()!.newContext();
  const nobody = await anonymous.newPage();
  await nobody.goto(reportUrl);
  await expect(nobody.locator("main [role=alert]")).toContainText("session has ended");
  await expect(nobody.locator("tr[data-fact-id]")).toHaveCount(0);
  await anonymous.close();

  // A guest can see the settings surface but cannot opt into account email.
  await page.goto("/settings");
  await expect(page.getByText("Email notifications are available after signing in to an account.")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Email me when a report is ready" })).toHaveCount(0);
  await expectAccessible(page, testInfo);

  // Test-only provider sign-in creates a synthetic account; no production IdP is activated.
  const settingsOrigin = new URL(page.url()).origin;
  const login = await page.request.post(settingsOrigin + "/api/session/dev-login", {
    headers: { origin: settingsOrigin },
    data: { subject: "mail-pref-account" },
  });
  expect(login.status()).toBe(201);
  await page.reload();

  const preference = page.getByRole("checkbox", { name: "Email me when a report is ready" });
  await expect(preference).toBeVisible();
  await expect(preference).not.toBeChecked();
  await expectAccessible(page, testInfo);

  await preference.check();
  await page.getByRole("button", { name: "Save email preference" }).click();
  await expect(page.getByRole("status")).toHaveText("Email preference saved.");
  await expectAccessible(page, testInfo);
  await page.reload();
  await expect(preference).toBeChecked();

  // The proxy exposes exactly GET/PUT for the preference route and retains the same-origin mutation fence.
  const crossOrigin = await page.request.put(settingsOrigin + "/api/v1/me/notification-preferences", {
    headers: { origin: "https://attacker.example" },
    data: { mail_report_ready: false, locale: "en" },
  });
  expect(crossOrigin.status()).toBe(403);
  expect((await page.request.get(settingsOrigin + "/api/v1/me/notification-preferences/extra")).status()).toBe(404);

  await preference.uncheck();
  await page.getByRole("button", { name: "Save email preference" }).click();
  await expect(page.getByRole("status")).toHaveText("Email preference saved.");
  await page.reload();
  await expect(preference).not.toBeChecked();

  expect(api).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
});
