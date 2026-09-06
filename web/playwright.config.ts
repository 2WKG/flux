import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH
  ?? (existsSync(systemChrome) ? systemChrome : undefined);

const port = process.env.FLUX_E2E_PORT ?? "4173";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL,
    browserName: "chromium",
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    // Not `node server.mjs`: the App is server-backed, so the proof needs the
    // real FastAPI app behind the origin's read forward. `scripts/e2e-stack.mjs`
    // boots both and tears both down. The budget covers a cold `uv sync` plus
    // the ~25 s first `import copilot.app`.
    command: "npm run build && node scripts/e2e-stack.mjs",
    url: baseURL,
    env: { PORT: port },
    reuseExistingServer: false,
    timeout: 600_000,
  },
});
