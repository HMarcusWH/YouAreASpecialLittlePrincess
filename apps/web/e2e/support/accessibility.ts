import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type TestInfo } from "@playwright/test";

export const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] as const;

export async function analyzeAccessibility(page: Page) {
  return new AxeBuilder({ page }).withTags([...WCAG_TAGS]).analyze();
}

export async function expectAccessible(page: Page, testInfo: TestInfo) {
  const results = await analyzeAccessibility(page);
  if (results.violations.length) {
    await testInfo.attach("axe-violations.json", {
      body: JSON.stringify(results.violations, null, 2),
      contentType: "application/json",
    });
  }
  const summary = results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    nodes: violation.nodes.map((node) => node.target.join(" > ")),
  }));
  expect(summary, "axe found WCAG A/AA violations in the rendered state").toEqual([]);
  return results;
}
