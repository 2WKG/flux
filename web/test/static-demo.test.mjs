import assert from "node:assert/strict";
import { createReadStream, existsSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));

// The entry mounts the shell and the pages are their own modules (2WKG-478), so
// "the demo's source" is the entry plus every page, and "the built bundle" is
// `assets/app.js` plus the chunks the split emits beside it.
const sources = () => Promise.all(
  ["../src/main.tsx", "../src/pages/MainPage.tsx", "../src/pages/ExplainerPage.tsx"]
    .map((name) => readFile(new URL(name, import.meta.url), "utf8")),
).then((parts) => parts.join("\n"));

const files = () => Promise.all([
  sources(),
  readBuiltScripts(),
  readFile(new URL("../../data/demo/bundle.json", import.meta.url), "utf8").then(JSON.parse),
]);

test("frozen static demo bundles the current fixture without fetching", async () => {
  const [source, app, fixture] = await files();

  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(app, /\bfetch\s*\(/);
  // Any spelling of the demo route in the bundle (string, template, or URL constant) is a request path.
  assert.doesNotMatch(app, /["'`]\/api\/demo["'`]/);
  assert.doesNotMatch(app, /\/api\/demo\b/);
  assert.ok(app.includes(fixture.fixtureHash));
  assert.ok(app.includes(fixture.execution.provenance.artifactId));
});

test("the UI does not claim an API connection it does not have", async () => {
  const [source, app] = await files();
  for (const text of [source, app]) {
    assert.ok(!text.includes("API connected"), "static build must not say it is connected to an API");
    assert.ok(!/GET \/api\/demo/.test(text), "static build must not describe consuming GET /api/demo");
  }
  assert.ok(app.includes("no API required"));
});

// A plain static file server over dist/ (what any CDN or `npx serve` would do): files
// are served as-is and unknown paths fall back to the SPA shell. There is no
// application code in this server; what is under test is the built artifact.
const contentTypes = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".map": "application/json" };
function staticServer() {
  return http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    let file = path.join(dist, pathname);
    if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
    res.writeHead(200, { "content-type": contentTypes[path.extname(file)] ?? "application/octet-stream" });
    createReadStream(file).pipe(res);
  });
}

test("serving dist/ statically yields the SPA shell for /api/demo, never a demo payload", async () => {
  const server = staticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const shell = await fetch(`${base}/`);
    assert.equal(shell.status, 200);
    assert.match(shell.headers.get("content-type"), /^text\/html/);
    const shellBody = await shell.text();
    assert.match(shellBody, /<div id="root">/);
    assert.match(shellBody, /\/assets\/app\.js/);

    const script = await fetch(`${base}/assets/app.js`);
    assert.equal(script.status, 200);
    assert.match(script.headers.get("content-type"), /javascript/);

    for (const route of ["/api/demo", "/api/demo?scenario=a", "/api/demo/"]) {
      const response = await fetch(`${base}${route}`);
      const body = await response.text();
      assert.doesNotMatch(response.headers.get("content-type"), /json/, route);
      assert.equal(body, shellBody, `${route} must fall back to the SPA shell`);
      assert.throws(() => JSON.parse(body), `${route} returned parseable JSON`);
      assert.ok(!body.includes('"status":"available"'), `${route} looks like the demo API envelope`);
    }
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
