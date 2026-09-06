/**
 * What must be true of the built demo artifact.
 *
 * **This file used to forbid the literal `fetch(` in `src/main.tsx` and in the
 * built bundle.** That rule made the offline demo and a live evidence surface
 * mutually exclusive in one entry, which is exactly the split Joshua's decision
 * of 2026-09-06 closes: the one App is server-backed
 * (`docs/specs/spec-code-reconciliation.md`, "Decisions taken on 2026-09-06",
 * and `docs/specs/05-copilot.md`'s routes section). Retiring an assertion is
 * only honest if something at least as strong replaces it, so the `fetch(`
 * denial is replaced by the two claims it was standing in for:
 *
 * 1. **Every request the artifact can make is same-origin.** No absolute URL is
 *    used as a request target anywhere in the bundle, and the shell's CSP is
 *    `connect-src 'self'`. `web/e2e/static-explorer.spec.ts` asserts the
 *    same thing in a real browser, as zero off-origin requests.
 * 2. **When the API is unreachable the shell says so by name.** Each data path
 *    is exercised here against a transport that cannot connect, and each one
 *    must produce a named `unavailable`/`request_failed` outcome carrying a
 *    reason. None of them may produce a ready/available state. This is the
 *    assertion that a "fake-fine" offline state cannot pass.
 *
 * The fixture-identity and no-false-API-claim tests below are unchanged.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { createReadStream, existsSync, statSync } from "node:fs";
import { mkdir, readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const webRoot = new URL("../", import.meta.url);

const files = () => Promise.all([
  readFile(new URL("../src/main.tsx", import.meta.url), "utf8"),
  readFile(new URL("../dist/assets/app.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/demo/bundle.json", import.meta.url), "utf8").then(JSON.parse),
]);

test("the built demo ships the current fixture and asks for nothing off-origin", async () => {
  const [, app, fixture] = await files();

  // Any spelling of a demo API route in the bundle would be a request path this
  // artifact does not have a server for.
  assert.doesNotMatch(app, /["'`]\/api\/demo["'`]/);
  assert.doesNotMatch(app, /\/api\/demo\b/);

  // No absolute URL is used as a request target. Vendor attribution strings and
  // documentation links are not requests, so the check is on the shapes a
  // request is actually made with: a fetch/XHR/EventSource/WebSocket/importScripts
  // call whose first argument is an absolute URL literal.
  const absoluteRequest = /\b(?:fetch|open|importScripts|EventSource|WebSocket)\s*\(\s*(?:"|'|`)https?:\/\//g;
  assert.deepEqual([...app.matchAll(absoluteRequest)].map((match) => match[0]), []);

  // The shell's own policy backs it: an absolute URL smuggled in at runtime is
  // blocked by the browser rather than silently fetched.
  const html = await readFile(new URL("dist/index.html", webRoot), "utf8");
  assert.match(html, /connect-src 'self'/);

  assert.ok(app.includes(fixture.fixtureHash));
  assert.ok(app.includes(fixture.execution.provenance.artifactId));
});

test("the UI does not claim an API connection it does not have", async () => {
  const [source, app] = await files();
  for (const text of [source, app]) {
    assert.ok(!text.includes("API connected"), "static build must not say it is connected to an API");
    assert.ok(!/GET \/api\/demo/.test(text), "static build must not describe consuming GET /api/demo");
  }
  // The scenario explorer is still bundled: it needs no API to paint, which is
  // what this claim is scoped to.
  assert.ok(app.includes("no API required"));
});

/**
 * Compile the shell's data paths and drive them against a transport that cannot
 * connect. This is the offline fallback, exercised rather than described.
 */
const probe = new URL("../node_modules/.cache/flux-offline-fallback.mjs", import.meta.url);
await mkdir(new URL(".", probe), { recursive: true });
await build({
  stdin: {
    contents: `
      export { createReadApiClient, createSseClient } from "./src/data/client-state";
      export { loadGridLayer } from "./src/data/grid-client";
      export { loadScenarioAsset } from "./src/data/scenario-asset";
      export { loadLayerDataStatus } from "./src/data/layer-status";
      export { runAsk } from "./src/data/ask-stream";
      export { createRunState } from "./src/ask/run-state/reducer";
      export { LAYER_REGISTRY } from "./src/layers/registry";
      export { fromClientState } from "./src/failure-states/adapters";
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "offline-fallback-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic",
  packages: "external", loader: { ".css": "empty" },
  outfile: fileURLToPath(probe),
});
const paths = await import(probe.href);

/** A transport that behaves exactly as an unreachable origin does. */
const unreachable = async () => { throw new TypeError("Failed to fetch"); };

test("with the API unreachable every data path names an unavailable state, never a ready one", async () => {
  const readClient = paths.createReadApiClient(unreachable);
  const sseClient = paths.createSseClient(unreachable);

  const grid = await paths.loadGridLayer({ state: "mn", layer: "line", maxPages: 1 }, readClient);
  assert.equal(grid.kind, "refused", "an unreachable inventory API must not produce a loaded release");
  assert.ok(["unavailable", "request_failed"].includes(grid.status));
  assert.ok(grid.message.length > 0, "the refusal must carry a reason");

  const asset = await paths.loadScenarioAsset("baseline", readClient);
  assert.ok(["unavailable", "request_failed"].includes(asset.status), "the inspector must not show an asset it did not read");
  assert.equal(asset.artifactLabel, asset.status);
  assert.ok((asset.message ?? "").length > 0);

  const layer = await paths.loadLayerDataStatus(paths.LAYER_REGISTRY[0], readClient);
  assert.ok(["unavailable", "request_failed"].includes(layer.kind), "a layer must never be available when its route did not answer");
  assert.ok(layer.reason.length > 0);

  const identity = { attemptId: "attempt-offline-000000", contextRevision: "r1" };
  const run = await paths.runAsk(
    { attempt_id: identity.attemptId, question: "anything", history: [] },
    identity,
    paths.createRunState(identity, "synthetic"),
    { client: sseClient },
  );
  assert.ok(run.connection, "an unreachable /ask must report the connection state, not a silent empty run");
  assert.notEqual(run.connection.kind, "ready");
  assert.equal(run.state.terminal, undefined, "no terminal event may be invented for a stream that never opened");

  // And the failure surface the shell renders it through keeps the distinction.
  const failure = paths.fromClientState(run.connection);
  assert.ok(failure !== null && failure.kind !== "empty" && failure.kind !== "partial");
  assert.ok((failure.message ?? "").length > 0);
});

// A plain static file server over dist/ (what any CDN or `npx serve` would do): files
// are served as-is and unknown paths fall back to the SPA shell. There is no
// application code in this server; what is under test is the built artifact.
const contentTypes = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".map": "application/json" };
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
