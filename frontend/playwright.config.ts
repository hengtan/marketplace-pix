import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: process.env.SCREENSHOTS ? /app\.spec/ : /screenshots\.spec/,
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://localhost:5174", trace: "retain-on-failure" },
  webServer: {
    command: "pnpm exec vite --port 5174 --strictPort",
    env: { VITE_USE_MOCKS: "true", VITE_ENABLE_DEV_TOOLS: "true" },
    url: "http://localhost:5174",
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
