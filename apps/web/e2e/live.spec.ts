// Live Free journey through the real stack (API, PostgreSQL, analysis and
// export workers, offline renderer, local object store). Runs only when PRINCESS_E2E_API and PRINCESS_E2E_SAMPLE are
// set, e.g. by tools/run_web_e2e.sh; CI runs the fixture journeys.
import { expect, test } from "@playwright/test";

const api = process.env.PRINCESS_E2E_API;
const sample = process.env.PRINCESS_E2E_SAMPLE;

test.skip(!api || !sample, "live stack not configured");

test("upload, consent, job and report without any AI provider", async ({ page }) => {
  await page.goto("/start");
  await page.setInputFiles("#photo", sample!);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Analyse my handwriting" }).click();
  await expect(page).toHaveURL(/\/analyses\/run_/, { timeout: 30_000 });
  const runUrl = page.url();
  await expect(page).toHaveURL(/\/reports\/report_/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Your report" })).toBeVisible();
  expect(await page.locator("tr[data-fact-id]").count()).toBeGreaterThan(10);
  await expect(page.getByText("No reference group is available yet")).toBeVisible();

  // Export: the saved projection is rendered to a PDF by the sandboxed renderer.
  await page.getByRole("button", { name: "Export PDF" }).click();
  const download = page.getByRole("link", { name: "Download PDF" });
  await expect(download).toBeVisible({ timeout: 60_000 });
  const pdf = await page.request.get(new URL((await download.getAttribute("href"))!, page.url()).toString());
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();  // no flow, says why

  // Refresh on the job URL resumes the known run: it redirects to the same report.
  const reportUrl = page.url();
  await page.goto(runUrl);
  await expect(page).toHaveURL(reportUrl, { timeout: 30_000 });

  // A different guest cannot open this report, and nothing of it is rendered.
  const stranger = await page.context().browser()!.newContext();
  const other = await stranger.newPage();
  const origin = new URL(reportUrl).origin;
  expect((await other.request.post(`${origin}/api/session/guest`, { headers: { origin } })).status()).toBe(201);
  const response = await other.goto(reportUrl);
  expect(response!.status()).toBe(404);
  await expect(other.locator("tr[data-fact-id]")).toHaveCount(0);
  await stranger.close();

  // Without any session the report is not rendered either.
  const anonymous = await page.context().browser()!.newContext();
  const nobody = await anonymous.newPage();
  await nobody.goto(reportUrl);
  await expect(nobody.locator("main [role=alert]")).toContainText("session has ended");
  await expect(nobody.locator("tr[data-fact-id]")).toHaveCount(0);
  await anonymous.close();
});
