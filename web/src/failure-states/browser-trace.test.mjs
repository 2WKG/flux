import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createReadStream } from "node:fs";
import { createServer } from "node:http";
import { rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../..", import.meta.url));
const dist = "/tmp/flux-351-browser-assertion";
const chromePath = process.env.FLUX_CHROME_PATH;

test("browser trace keeps context and invokes supplied recovery callbacks", { skip: !chromePath && "set FLUX_CHROME_PATH to run this real-browser assertion" }, async () => {
  const { chromium } = await import("playwright-core");
  await rm(dist, { recursive: true, force: true });
  execFileSync("npm", ["run", "build"], {
    cwd: webRoot,
    env: { ...process.env, FLUX_WEB_ENTRY: "src/failure-states/browser-trace.entry.tsx", FLUX_WEB_DIST: dist },
    stdio: "inherit",
  });
  const server = createServer((request, response) => {
    const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
    const file = pathname === "/" ? path.join(dist, "index.html") : path.join(dist, pathname);
    response.setHeader("content-type", path.extname(file) === ".js" ? "text/javascript" : "text/html; charset=utf-8");
    createReadStream(file).on("error", () => { response.writeHead(404); response.end(); }).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true, executablePath: chromePath });
  let page;
  try {
    page = await browser.newPage();
    page.setDefaultTimeout(5_000);
    await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "domcontentloaded" });
    const panel = page.locator("section[aria-label='Request state']");
    await panel.locator("[aria-label='Retained context']").waitFor();
    assert.equal(await panel.getAttribute("data-request-state"), "network_failure");
    await page.getByRole("button", { name: "Retry" }).click();
    await page.locator("main[data-retries='1']").waitFor();
    await page.getByRole("button", { name: "Reset view" }).click();
    await page.locator("main[data-reset='called']").waitFor();
    for (const expected of ["malformed", "version_mismatch", "cancelled", "partial"]) {
      await page.getByRole("button", { name: "Next state" }).click();
      await page.waitForFunction((kind) => document.querySelector("section")?.getAttribute("data-request-state") === kind, expected);
      assert.match(await panel.textContent(), /Retained scene: Minnesota overview/);
    }
    assert.match(await panel.textContent(), /Only the source-provided portion is available/);
  } finally {
    await page?.close();
    await browser.close();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await rm(dist, { recursive: true, force: true });
  }
});
