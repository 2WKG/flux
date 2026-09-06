import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const systemChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH
  ?? (existsSync(systemChrome) ? systemChrome : undefined);

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  forbidOnly: Boolean(process.env.CI),
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    launchOptions: executablePath ? { executablePath } : undefined,
  },
  webServer: {
    command: "npm run build && node server.mjs",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
