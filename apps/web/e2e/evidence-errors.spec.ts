import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const view = JSON.parse(readFileSync(
  new URL("../../../fixtures/reports/view.free.json", import.meta.url), "utf8"));

for (const error of ["stored_evidence_invalid", "evidence_lineage_invalid"]) {
  test(`${error} renders the report and a warning, never rejected evidence`, async ({ page }) => {
    const response = await page.goto(`/fixtures/evidence-errors?error=${error}`);
    expect(response!.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: "Free report" })).toBeVisible();
    await expect(page.locator("tr[data-fact-id]")).toHaveCount(
      new Set(view.sections.flatMap((section: { fact_ids: string[] }) => section.fact_ids)).size);
    const warning = page.getByRole("alert").filter({ hasText: "The saved evidence could not be read safely" });
    await expect(warning).toBeVisible();
    await expect(warning).toHaveText(
      "The saved evidence could not be read safely, so it is not shown.");
    await expect(page.locator(".pr-evidence-table")).toHaveCount(0);
    await expect(page.getByRole("img", { name: /Line \d/ })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Slant observations" })).toHaveCount(0);
  });
}
