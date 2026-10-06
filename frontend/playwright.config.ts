import { defineConfig } from "@playwright/test";

const port = process.env.EMNEKLAR_E2E_PORT ?? "8768";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  // One shared backend with state (analysis, change queue): run the specs in order.
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    locale: "nb-NO",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "node e2e/start-backend.mjs",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { EMNEKLAR_E2E_PORT: port },
  },
});
