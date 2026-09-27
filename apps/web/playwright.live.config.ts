import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PRINCESS_CHROMIUM;
for (const name of ["PRINCESS_E2E_API", "PRINCESS_E2E_SAMPLE", "PRINCESS_E2E_WORKER_GATE"]) {
  if (!process.env[name]) throw new Error(name + " is required for the live web qualification");
}

export default defineConfig({
  testDir: "e2e",
  testMatch: ["live.spec.ts"],
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  webServer: {
    command: "pnpm exec next start --port 3100 --hostname 127.0.0.1",
    url: "http://127.0.0.1:3100/",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PRINCESS_WEB_FIXTURES: "0",
      PRINCESS_ENVIRONMENT: "test",
      PRINCESS_API_BASE: process.env.PRINCESS_E2E_API!,
      NEXT_TELEMETRY_DISABLED: "1",
    },
  },
});
