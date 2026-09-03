import { defineConfig } from "@playwright/test";

const WEB_PORT = Number(process.env.E2E_WEB_PORT || 3003);
const API_PORT = Number(process.env.E2E_API_PORT || 8001);
const STUB_PORT = Number(process.env.STUB_PORT || 9797);

/**
 * Full-stack E2E: stub Anthropic → API + worker (dedicated DB, redis db 1)
 * → Vite dev server proxying to the E2E API. Requires local/CI Postgres,
 * Redis, and MinIO/R2-compatible storage (same services the dev stack uses).
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  // The specs drive one shared backend; parallel workers would race the
  // singleton session store in localStorage anyway.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Run against a browser build already on the machine when the pinned
    // revision is not installed (e.g. E2E_CHROMIUM_PATH=~/Library/Caches/ms-playwright/…/chrome-headless-shell).
    ...(process.env.E2E_CHROMIUM_PATH
      ? { launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH } }
      : {}),
  },
  webServer: [
    {
      command: "node stub-anthropic.mjs",
      port: STUB_PORT,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: "bash start-stack.sh",
      url: `http://localhost:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `pnpm --filter @datapilot/web exec vite --port ${WEB_PORT} --strictPort`,
      port: WEB_PORT,
      reuseExistingServer: false,
      env: {
        VITE_PROXY_TARGET: `http://localhost:${API_PORT}`,
      },
    },
  ],
});
