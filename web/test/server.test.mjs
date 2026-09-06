// The static origin under test is the real server.mjs, not a stand-in: 2WKG-300 settled the
// runtime contract as static assets only, so what has to hold is that this process serves the
// built shell and offers no demo API on any path.
import assert from "node:assert/strict";
import test, { after } from "node:test";

import { CONTENT_SECURITY_POLICY, createApp, NO_API_ORIGIN_REASON } from "../server.mjs";

const servers = [];

async function origin() {
  const server = createApp().listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  return async (path, init) => {
    const response = await fetch(`${base}${path}`, init);
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

test("the origin serves the SPA shell for the explainer deep link", async () => {
  const get = await origin();
  const shell = await get("/");
  for (const path of ["/explainer", "/explainer/"]) {
    const response = await get(path);
    assert.equal(response.status, 200, `${path} did not resolve`);
    assert.match(response.type, /^text\/html/, `${path} did not return the app shell`);
    assert.equal(response.body, shell.body, `${path} did not return the SPA shell`);
  }
});

test("API-shaped paths state that this static origin is unavailable", async () => {
  const get = await origin();
  for (const path of ["/api", "/api/demo", "/api/demo?scenario=a", "/api/demo/", "/api/anything"]) {
    const response = await get(path);
    assert.equal(response.status, 503, `${path} did not report unavailable`);
    assert.match(response.type, /^text\/plain/, `${path} did not return an explicit text response`);
    assert.match(response.body, /does not serve API routes/i, `${path} did not explain the unavailable API`);
  }
});

test("every response carries a CSP that names no off-origin source and permits only WebAssembly evaluation", async () => {
  const get = await origin();
  for (const path of ["/", "/assets/app.js", "/api/demo", "/anything"]) {
    const response = await get(path);
    assert.equal(response.csp, CONTENT_SECURITY_POLICY, `${path} served without the policy`);
  }
  assert.match(CONTENT_SECURITY_POLICY, /script-src 'self' 'wasm-unsafe-eval'/);
  assert.doesNotMatch(CONTENT_SECURITY_POLICY, /'unsafe-eval'/);
  for (const directive of CONTENT_SECURITY_POLICY.split("; ")) {
    const [name, ...values] = directive.split(" ");
    for (const value of values) {
      assert.ok(
        ["'self'", "'none'", "data:", "blob:", "'unsafe-inline'", "'wasm-unsafe-eval'"].includes(value),
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

test("with no API origin configured, every allowlisted path refuses by name", async () => {
  // This assertion replaces "every API path is the SPA shell", which pinned a
  // real defect: `GET /health` answered 200 with `index.html`, and the browser's
  // validator could only report that as a *malformed* response. "Malformed" and
  // "this deployment has no API" are different claims, and only the second is
  // true, so the shell fall-through was a quieter, weaker refusal than the one
  // the offline story promises. The replacement is strictly stronger -- it pins
  // the status, the content type, the frozen token, the named reason, and that
  // the answer is never the shell.
  const get = await origin();
  const shell = await get("/");
  for (const path of ["/demo/model", "/health", "/scenarios", "/scenarios/baseline", "/api/v1/grid/layers/line", "/layers/buses"]) {
    const response = await get(path);
    assert.equal(response.status, 503, `${path} must refuse, not answer`);
    assert.match(response.type, /json/, `${path} must refuse in the envelope's own media type`);
    assert.notEqual(response.body, shell.body, `${path} must not be answered with the SPA shell`);
    const body = JSON.parse(response.body);
    assert.equal(body.status, "unavailable");
    assert.equal(body.error.code, "unavailable");
    assert.equal(body.error.details.reason, NO_API_ORIGIN_REASON);
    assert.equal(body.error.retryable, true);
    assert.ok(body.error.message.trim().length > 0, `${path} refused with an empty reason`);
    assert.equal(body.data, null, `${path} must not invent a payload`);
    assert.equal(body.meta.api_version, "v1");
  }
});

test("POST /mn/comparisons is on the table, so it refuses by name instead of 404ing to the shell", async () => {
  // The Minnesota comparison button posts here (`src/minnesota/comparison-client.ts`).
  // Before the path was on the table it fell through to `app.get("/{*path}")`,
  // which does not match POST, so Express answered its own 404 HTML; the
  // browser's `validateJsonResponse` could only call that *malformed*, i.e. a
  // broken server contract, rather than "this deployment has no API".
  const get = await origin();
  const shell = await get("/");
  const posted = await get("/mn/comparisons", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ baseline_context_id: "mn:baseline:v1", candidate_context_id: "mn:candidate:v1" }),
  });
  assert.equal(posted.status, 503, "the comparison POST must refuse by name");
  assert.match(posted.type, /json/, "the comparison POST must refuse in the envelope's media type");
  assert.notEqual(posted.body, shell.body, "the comparison POST must not be answered with the SPA shell");
  const body = JSON.parse(posted.body);
  assert.equal(body.status, "unavailable");
  assert.equal(body.error.details.reason, NO_API_ORIGIN_REASON);
  assert.equal(body.data, null);
  // The method half of the table: GET is not the comparison contract.
  const got = await get("/mn/comparisons");
  assert.equal(got.body, shell.body, "GET /mn/comparisons is outside the table and stays a client route");
});

test("with no API origin configured, a path outside the allowlist is not given the envelope", async () => {
  // The control: the named-envelope refusal above is registered for the
  // allowlist, not for everything. A blanket 503 envelope would pass the test
  // above while claiming that every SPA route is a broken API.
  const get = await origin();
  const shell = await get("/");
  // An API-shaped path outside the table gets master's own plain-text 503
  // (`app.get("/api/{*path}", unavailableApi)`), which is a refusal too -- but
  // not this deployment's named envelope, because it names no read route.
  for (const path of ["/api/v1/grid/releases", "/api/demo"]) {
    const response = await get(path);
    assert.equal(response.status, 503, `${path} must refuse`);
    assert.match(response.type, /text\/plain/, `${path} must not be given the envelope`);
    assert.doesNotMatch(response.body, /no_api_origin_configured/);
  }
  // Everything that is not API-shaped is still the SPA's own client route.
  for (const path of ["/admin", "/health/../admin", "/explainer"]) {
    const response = await get(path);
    assert.equal(response.body, shell.body, `${path} must still fall back to the shell`);
  }
  // And the method half of the table: POST /health is not forwarded, so it is
  // not refused as an API path either.
  const posted = await get("/health", { method: "POST" });
  assert.notEqual(posted.status, 503, "POST /health is outside the table and must not be refused as one");
});

test("a configured API origin forwards only the allowlisted read paths", async () => {
  const seen = [];
  const api = await upstream((req, res) => {
    seen.push(`${req.method} ${req.url}`);
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, url: req.url }));
  });
  const base = await proxyOrigin(api);

  for (const path of ["/api/v1/grid/layers/line?state=mn&limit=100", "/demo/model?element_id=bus%3A1"]) {
    const forwarded = await fetch(`${base}${path}`);
    assert.equal(forwarded.status, 200);
    assert.deepEqual(await forwarded.json(), { ok: true, url: path });
  }

  // Not on the table: a path outside it, and a method outside it. Neither may
  // reach the upstream -- which the `seen` assertion at the end proves. What
  // they get instead depends only on shape: an API-shaped path gets the static
  // origin's own plain-text 503, anything else gets the SPA shell.
  const shell = await (await fetch(`${base}/`)).text();
  for (const path of ["/api/v1/grid/releases", "/api/demo"]) {
    const response = await fetch(`${base}${path}`);
    assert.equal(response.status, 503, `${path} must not be forwarded`);
    assert.notEqual(await response.text(), shell, `${path} must not be forwarded`);
  }
  for (const path of ["/site-score"]) {
    const response = await fetch(`${base}${path}`);
    assert.equal(await response.text(), shell, `${path} must not be forwarded`);
  }
  // `/health` is forwarded for GET only. A POST is not forwarded at all: the
  // static origin has no POST route, so it 404s here rather than reaching the API.
  const wrongMethod = await fetch(`${base}/health`, { method: "POST" });
  assert.equal(wrongMethod.status, 404, "POST /health must not be forwarded");
  assert.deepEqual(seen, ["GET /api/v1/grid/layers/line?state=mn&limit=100", "GET /demo/model?element_id=bus%3A1"]);
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


test("a partially streamed upstream timeout closes that response without taking down the proxy", async () => {
  const api = await upstream((_req, res) => {
    res.writeHead(200, { "content-type": "model/gltf-binary" });
    res.write(Buffer.from([0x67, 0x6c, 0x54, 0x46]));
    // Deliberately never end: the proxy timeout must contain the stream error.
  });
  const server = createApp({ apiOrigin: api, proxyTimeoutMs: 25 }).listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  const response = await fetch(`${base}/assets/flux-grid/manifest.json`);
  await assert.rejects(response.arrayBuffer(), /abort|terminated|fetch/i);
  const health = await fetch(`${base}/health`);
  assert.equal(health.status, 200, "the proxy remains alive after the truncated stream");
});
