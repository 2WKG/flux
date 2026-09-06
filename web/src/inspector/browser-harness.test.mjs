import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const webRoot = new URL("../../", import.meta.url);
function run(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, options);
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", reject);
    child.on("close", (code) => code === 0 ? resolve(output) : reject(new Error(output)));
  });
}

test("browser harness bundles the inspector states without an API dependency", async () => {
  const dist = await mkdtemp(path.join(os.tmpdir(), "flux-inspector-harness-"));
  try {
    await run("node", ["scripts/build.mjs"], { cwd: new URL(".", webRoot), env: { ...process.env, FLUX_WEB_ENTRY: "src/inspector/browser-harness.tsx", FLUX_WEB_DIST: dist } });
    const server = http.createServer(async (request, response) => {
      const file = request.url === "/assets/app.js" ? path.join(dist, "assets/app.js") : path.join(dist, "index.html");
      response.writeHead(200, { "content-type": file.endsWith(".js") ? "text/javascript" : "text/html" });
      response.end(await readFile(file));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const origin = `http://127.0.0.1:${server.address().port}`;
      const app = await (await fetch(`${origin}/assets/app.js`)).text();
      assert.match(app, /Inspector browser harness/);
      assert.match(app, /Fixture: source detail is explicitly unavailable/);
      assert.match(app, /Fixture: the source request failed/);
      assert.match(app, /Asset status and artifact label do not agree/);
      assert.match(app, /Asset detail is malformed/);
      assert.doesNotMatch(app, /\bfetch\s*\(/);
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  } finally {
    await rm(dist, { recursive: true, force: true });
  }
});
