import assert from "node:assert/strict";
import { createReadStream, existsSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const sources = () => Promise.all(
  ["../src/main.tsx", "../src/pages/MainPage.tsx", "../src/pages/ExplainerPage.tsx"]
    .map((name) => readFile(new URL(name, import.meta.url), "utf8")),
).then((parts) => parts.join("\n"));

test("the main-page bundle loads the server layer into the deck.gl scene", async () => {
  const [source, built] = await Promise.all([sources(), readBuiltScripts()]);

  for (const text of [source, built]) {
    assert.match(text, /\/layers\/buses/);
    assert.match(text, /ColumnLayer/);
    assert.match(text, /deck\.gl simulation scene/);
    assert.match(text, /OFFLINE FALLBACK · SYNTHETIC FIVE-BUS FIXTURE/);
  }
  assert.match(source, /fixture provenance[\s\S]*cannot be used as the primary simulation/);
  assert.match(source, /column height is a scene marker, not a measured asset value/);
});

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

test("a static host has no layer API and therefore leaves the browser to its labelled fallback", async () => {
  const server = staticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const shell = await fetch(`${base}/`);
    const shellBody = await shell.text();
    assert.equal(shell.status, 200);
    assert.match(shell.headers.get("content-type"), /^text\/html/);

    const layer = await fetch(`${base}/layers/buses`);
    const layerBody = await layer.text();
    assert.equal(layer.status, 200);
    assert.doesNotMatch(layer.headers.get("content-type"), /geo\+json|json/);
    assert.equal(layerBody, shellBody, "a static server must not fabricate a layer response");
    assert.throws(() => JSON.parse(layerBody));
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
