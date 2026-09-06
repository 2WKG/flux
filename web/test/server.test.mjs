// The static origin under test is the real server.mjs, not a stand-in: 2WKG-300 settled the
// runtime contract as static assets only, so what has to hold is that this process serves the
// built shell and offers no demo API on any path.
import assert from "node:assert/strict";
import test, { after } from "node:test";

import { CONTENT_SECURITY_POLICY, createApp } from "../server.mjs";

const servers = [];

async function origin() {
  const server = createApp().listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  return async (path) => {
    const response = await fetch(`${base}${path}`);
    return {
      status: response.status,
      type: response.headers.get("content-type"),
      csp: response.headers.get("content-security-policy"),
      body: await response.text(),
    };
  };
}

after(async () => {
  await Promise.all(servers.map((server) => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  }));
});

test("the origin serves the built SPA shell", async () => {
  const get = await origin();
  const shell = await get("/");
  assert.equal(shell.status, 200);
  assert.match(shell.type, /^text\/html/);
  assert.match(shell.body, /<div id="root">/);
  assert.match(shell.body, /\/assets\/app\.js/);
});

test("no demo API is served: every unknown path falls back to the shell", async () => {
  const get = await origin();
  const shell = await get("/");
  for (const path of ["/api/demo", "/api/demo?scenario=a", "/api/demo/", "/api/anything"]) {
    const response = await get(path);
    assert.doesNotMatch(response.type, /json/, `${path} answered with JSON`);
    assert.equal(response.body, shell.body, `${path} must fall back to the SPA shell`);
    assert.throws(() => JSON.parse(response.body), `${path} returned parseable JSON`);
  }
});

test("every response carries a CSP that names no off-origin source", async () => {
  const get = await origin();
  for (const path of ["/", "/assets/app.js", "/api/demo", "/anything"]) {
    const response = await get(path);
    assert.equal(response.csp, CONTENT_SECURITY_POLICY, `${path} served without the policy`);
  }
  for (const directive of CONTENT_SECURITY_POLICY.split("; ")) {
    const [name, ...values] = directive.split(" ");
    for (const value of values) {
      assert.ok(
        ["'self'", "'none'", "data:", "blob:", "'unsafe-inline'"].includes(value),
        `${name} allows ${value}, which can reach an off-origin server`,
      );
    }
  }
});

/**
 * The optional same-origin read proxy (`FLUX_API_ORIGIN`).
 *
 * PR #245's review found the version of this that shipped there had no
 * allowlist beyond a prefix, no timeout, no documentation, and a `/map` route
 * that silently served the synthetic offline demo when its bundle was absent.
 * All four are answered here: a fixed path+method table, a deadline, the env
 * var documented in STACK-LOCK.md, and no second entry to serve at all.
 */
async function upstream(handler) {
  const { createServer } = await import("node:http");
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

async function proxyOrigin(apiOrigin) {
  const server = createApp({ apiOrigin }).listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

test("with no API origin configured, every API path is the SPA shell", async () => {
  const get = await origin();
  const shell = await get("/");
  for (const path of ["/health", "/scenarios/baseline", "/api/v1/grid/layers/line", "/layers/buses"]) {
    const response = await get(path);
    assert.equal(response.body, shell.body, `${path} must fall back to the shell when no API origin is set`);
  }
});

test("a configured API origin forwards only the allowlisted read paths", async () => {
  const seen = [];
  const api = await upstream((req, res) => {
    seen.push(`${req.method} ${req.url}`);
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, url: req.url }));
  });
  const base = await proxyOrigin(api);

  const forwarded = await fetch(`${base}/api/v1/grid/layers/line?state=mn&limit=100`);
  assert.equal(forwarded.status, 200);
  assert.deepEqual(await forwarded.json(), { ok: true, url: "/api/v1/grid/layers/line?state=mn&limit=100" });

  const forecast = await fetch(`${base}/demo/forecast?county_fips=48201`);
  assert.equal(forecast.status, 200);
  assert.deepEqual(await forecast.json(), { ok: true, url: "/demo/forecast?county_fips=48201" });

  // Not on the table: a path outside it, and a method outside it.
  const shell = await (await fetch(`${base}/`)).text();
  for (const path of ["/api/v1/grid/releases", "/site-score", "/api/demo"]) {
    const response = await fetch(`${base}${path}`);
    assert.equal(await response.text(), shell, `${path} must not be forwarded`);
  }
  // `/health` is forwarded for GET only. A POST is not forwarded at all: the
  // static origin has no POST route, so it 404s here rather than reaching the API.
  const wrongMethod = await fetch(`${base}/health`, { method: "POST" });
  assert.equal(wrongMethod.status, 404, "POST /health must not be forwarded");
  assert.deepEqual(seen, [
    "GET /api/v1/grid/layers/line?state=mn&limit=100",
    "GET /demo/forecast?county_fips=48201",
  ]);
});

test("an unreachable upstream answers in the failure-envelope shape, not an HTML error page", async () => {
  // 127.0.0.1:1 is closed; the browser's validator must still get a named,
  // parseable unavailable envelope rather than an Express stack page.
  const base = await proxyOrigin("http://127.0.0.1:1");
  const response = await fetch(`${base}/health`);
  assert.equal(response.status, 503);
  assert.match(response.headers.get("content-type"), /json/);
  const body = await response.json();
  assert.equal(body.status, "unavailable");
  assert.equal(body.error.code, "unavailable");
  assert.equal(body.error.details.reason, "upstream_unreachable");
  assert.ok(body.error.message.length > 0);
  assert.equal(body.meta.api_version, "v1");
});

test("there is no second application entry to serve", async () => {
  // #245 added `/map` over a gitignored `dist-map/` that `npm run build` never
  // built, so a fresh clone served the synthetic offline demo under the
  // source-backed map's URL with HTTP 200. There is one App and one entry.
  const get = await origin();
  const shell = await get("/");
  const map = await get("/map");
  assert.equal(map.body, shell.body, "/map is the one App, not a second bundle");
  const scripts = await import("node:fs/promises").then((fs) => fs.readFile(new URL("../package.json", import.meta.url), "utf8"));
  assert.ok(!scripts.includes("dist-map"), "a second application dist is configured again");
  assert.ok(!scripts.includes("build:map"), "a second application build entry is configured again");
});
