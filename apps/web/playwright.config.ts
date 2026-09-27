import { defineConfig, devices } from "@playwright/test";

// CI installs Playwright's Chromium; a sandbox with a pre-installed browser
// sets PRINCESS_CHROMIUM to its executable instead of downloading one.
const executablePath = process.env.PRINCESS_CHROMIUM;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "off",
    ...devices["Desktop Chrome"],
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  webServer: {
    command: "pnpm exec next start --port 3100 --hostname 127.0.0.1",
    url: "http://127.0.0.1:3100/",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PRINCESS_WEB_FIXTURES: "1",
      PRINCESS_ENVIRONMENT: process.env.PRINCESS_ENVIRONMENT ?? "test",
      PRINCESS_API_BASE: process.env.PRINCESS_E2E_API ?? "http://127.0.0.1:9",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  },
});
