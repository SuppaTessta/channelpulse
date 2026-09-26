import { defineConfig } from "@playwright/test";

// Runs against an already running dashboard and API (make smoke); it never starts servers itself.
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 60_000 },
  retries: 0,
  workers: 2,
  reporter: [["list"]],
  use: {
    baseURL: process.env.SMOKE_URL ?? "http://127.0.0.1:3000",
    // Locally the system Edge (signed, nothing to download); CI installs Playwright's Chromium.
    channel: process.env.CI ? undefined : "msedge",
    screenshot: "only-on-failure",
  },
});
