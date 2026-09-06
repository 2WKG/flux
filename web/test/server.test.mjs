// The static origin under test is the real server.mjs, not a stand-in: 2WKG-300 settled the
// runtime contract as static assets only, so what has to hold is that this process serves the
// built shell and offers no demo API on any path.
import assert from "node:assert/strict";
import test, { after } from "node:test";

import {
  BODY_TOO_LARGE_REASON,
  CONTENT_SECURITY_POLICY,
  createApp,
  CROSS_ORIGIN_REASON,
  MAX_FORWARDED_BODY_BYTES,
  METHOD_NOT_ALLOWED_REASON,
  NO_API_ORIGIN_REASON,
} from "../server.mjs";

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
  for (const [path, init] of [
    ["/health"],
    ["/scenarios"],
    ["/scenarios/baseline"],
    ["/api/v1/grid/layers/line"],
    ["/layers/buses"],
    ["/cascade?scenario_id=uri_2021"],
    ["/scenario/edit", { method: "POST" }],
    ["/cascade", { method: "POST" }],
    ["/balance?scope=base"],
    ["/redundancy?bus_id=7"],
    ["/siting/search", { method: "POST" }],
    ["/site-score", { method: "POST" }],
    ["/minnesota/smr/validate", { method: "POST" }],
    ["/mn/comparisons", { method: "POST" }],
  ]) {
    const response = await get(path, init);
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
  // And the method half of the table: POST /health is not forwarded. It is not
  // the *no upstream* refusal either -- the path is allowlisted, the method is
  // not, so it is the caller's own named 405 and never the shell.
  const posted = await get("/health", { method: "POST" });
  assert.equal(posted.status, 405, "POST /health must be refused by name");
  assert.match(posted.type, /json/, "POST /health must be refused in the envelope's media type");
  assert.notEqual(posted.body, shell.body, "POST /health must not be answered with the SPA shell");
  const refusal = JSON.parse(posted.body);
  assert.equal(refusal.status, "error");
  assert.equal(refusal.error.code, "invalid_input");
  assert.equal(refusal.error.details.reason, METHOD_NOT_ALLOWED_REASON);
  assert.equal(refusal.error.retryable, false);
  assert.equal(refusal.data, null);
});

test("a configured API origin forwards only the fixed same-origin allowlist", async () => {
  const seen = [];
  const api = await upstream(async (req, res) => {
    const body = await new Promise((resolve, reject) => {
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => resolve(Buffer.concat(chunks).toString()));
      req.on("error", reject);
    });
    seen.push({ method: req.method, url: req.url, body, contentType: req.headers["content-type"] });
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, url: req.url, body }));
  });
  const base = await proxyOrigin(api);

  for (const [path, init, expected] of [
    ["/api/v1/grid/layers/line?state=mn&limit=100", undefined, { method: "GET", url: "/api/v1/grid/layers/line?state=mn&limit=100", body: "" }],
    ["/cascade?scenario_id=uri_2021", undefined, { method: "GET", url: "/cascade?scenario_id=uri_2021", body: "" }],
    ["/balance?scope=edit&edit_hash=abc", undefined, { method: "GET", url: "/balance?scope=edit&edit_hash=abc", body: "" }],
    ["/redundancy?bus_id=7&scenario_id=interactive", undefined, { method: "GET", url: "/redundancy?bus_id=7&scenario_id=interactive", body: "" }],
    ["/scenario/edit", { method: "POST", headers: { "content-type": "application/json" }, body: '{"ops":[]}' }, { method: "POST", url: "/scenario/edit", body: '{"ops":[]}' }],
    ["/cascade", { method: "POST", headers: { "content-type": "application/json" }, body: '{"element_ids":[]}' }, { method: "POST", url: "/cascade", body: '{"element_ids":[]}' }],
    ["/siting/search", { method: "POST", headers: { "content-type": "application/json" }, body: '{"kind":"producer"}' }, { method: "POST", url: "/siting/search", body: '{"kind":"producer"}' }],
    ["/site-score?trace=1", { method: "POST", headers: { "content-type": "application/json" }, body: '{"site_id":"s1","unit_mw":300,"scenario_id":"mn"}' }, { method: "POST", url: "/site-score?trace=1", body: '{"site_id":"s1","unit_mw":300,"scenario_id":"mn"}' }],
    ["/minnesota/smr/validate", { method: "POST", headers: { "content-type": "application/json" }, body: '{"scene_id":"mn"}' }, { method: "POST", url: "/minnesota/smr/validate", body: '{"scene_id":"mn"}' }],
    ["/mn/comparisons", { method: "POST", headers: { "content-type": "application/json" }, body: '{"baseline_context_id":"a","candidate_context_id":"b"}' }, { method: "POST", url: "/mn/comparisons", body: '{"baseline_context_id":"a","candidate_context_id":"b"}' }],
  ]) {
    const forwarded = await fetch(`${base}${path}`, init);
    assert.equal(forwarded.status, 200, `${expected.method} ${path} did not proxy`);
    assert.deepEqual(await forwarded.json(), { ok: true, url: expected.url, body: expected.body });
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
  // A path *not* on the table is the static origin's business: an unlisted path
  // under an allowlisted prefix is the SPA shell or an Express 404, and neither
  // reaches the upstream.
  for (const [path, init, expectedStatus] of [
    ["/minnesota/aggregate", undefined, 200],
    ["/mn/comparisons/extra", { method: "POST" }, 404],
    ["/siting/searchx", { method: "POST" }, 404],
    ["/cascade/extra", undefined, 200],
    ["/sql", { method: "POST" }, 404],
  ]) {
    const response = await fetch(`${base}${path}`, init);
    assert.equal(response.status, expectedStatus, `${path} must be handled by the static origin`);
    if (expectedStatus === 200) assert.equal(await response.text(), shell, `${path} must not be forwarded`);
  }
  // A path that *is* on the table with a method that is not gets the shared
  // envelope, 405, and a named reason -- never an HTML page and never a 200
  // shell. Status alone cannot tell those apart, so the media type and the
  // reason are pinned too: before this, `GET /scenario/edit` answered 200 with
  // `index.html` and `POST /balance` answered Express's HTML `Cannot POST`
  // page, which the browser's validator can only call *malformed*.
  for (const [path, init] of [
    ["/scenario/edit", undefined],
    ["/siting/search", undefined],
    ["/mn/comparisons", undefined],
    ["/minnesota/smr/validate", undefined],
    ["/site-score", undefined],
    ["/ask", undefined],
    ["/cascade", { method: "PUT" }],
    ["/cascade", { method: "DELETE" }],
    ["/balance", { method: "POST" }],
    ["/redundancy", { method: "POST" }],
    ["/health", { method: "POST" }],
  ]) {
    const label = `${init?.method ?? "GET"} ${path}`;
    const response = await fetch(`${base}${path}`, init);
    assert.equal(response.status, 405, `${label} must be refused by name, not fall through`);
    assert.match(
      response.headers.get("content-type"),
      /application\/json/,
      `${label} must be refused in the envelope's own media type, not an HTML page`,
    );
    const body = await response.text();
    assert.notEqual(body, shell, `${label} must not be answered with the SPA shell`);
    const envelope = JSON.parse(body);
    assert.equal(envelope.status, "error", `${label} refused without the shared envelope`);
    assert.equal(envelope.error.code, "invalid_input", `${label} refused without the shared code`);
    assert.equal(
      envelope.error.details.reason,
      METHOD_NOT_ALLOWED_REASON,
      `${label} refused without a named reason`,
    );
    assert.equal(envelope.error.retryable, false, `${label} is the caller's fault and is not retryable`);
    assert.equal(envelope.data, null, `${label} must not invent a payload`);
    assert.equal(envelope.meta.api_version, "v1");
  }
  assert.deepEqual(seen.map(({ method, url, body }) => ({ method, url, body })), [
    { method: "GET", url: "/api/v1/grid/layers/line?state=mn&limit=100", body: "" },
    { method: "GET", url: "/cascade?scenario_id=uri_2021", body: "" },
    { method: "GET", url: "/balance?scope=edit&edit_hash=abc", body: "" },
    { method: "GET", url: "/redundancy?bus_id=7&scenario_id=interactive", body: "" },
    { method: "POST", url: "/scenario/edit", body: '{"ops":[]}' },
    { method: "POST", url: "/cascade", body: '{"element_ids":[]}' },
    { method: "POST", url: "/siting/search", body: '{"kind":"producer"}' },
    { method: "POST", url: "/site-score?trace=1", body: '{"site_id":"s1","unit_mw":300,"scenario_id":"mn"}' },
    { method: "POST", url: "/minnesota/smr/validate", body: '{"scene_id":"mn"}' },
    { method: "POST", url: "/mn/comparisons", body: '{"baseline_context_id":"a","candidate_context_id":"b"}' },
  ]);
  for (const request of seen.filter(({ method }) => method === "POST")) {
    assert.equal(request.contentType, "application/json", `${request.url} lost its content type`);
  }
});

test("a forward naming a foreign origin is refused and never reaches the upstream", async () => {
  // Only the path and query cross, so the upstream's own CORSMiddleware never
  // sees the real caller: without this check any page on the internet could
  // drive the writes on this table as CORS-simple requests. A same-origin
  // `Origin` (what the browser sends for a same-origin POST) still forwards.
  const seen = [];
  const api = await upstream((req, res) => {
    seen.push({ method: req.method, url: req.url });
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
  });
  const base = await proxyOrigin(api);
  const shell = await (await fetch(`${base}/`)).text();
  const host = new URL(base).host;

  for (const origin of ["https://evil.example", "http://localhost:9999", "null"]) {
    const response = await fetch(`${base}/scenario/edit`, {
      method: "POST",
      headers: { "content-type": "application/json", origin },
      body: '{"ops":[]}',
    });
    assert.equal(response.status, 403, `${origin} was not refused`);
    assert.match(response.headers.get("content-type"), /application\/json/, `${origin} was refused as an HTML page`);
    const body = await response.text();
    assert.notEqual(body, shell, `${origin} was answered with the SPA shell`);
    const envelope = JSON.parse(body);
    assert.equal(envelope.status, "error");
    assert.equal(envelope.error.code, "invalid_input");
    assert.equal(envelope.error.details.reason, CROSS_ORIGIN_REASON, `${origin} was refused without a named reason`);
    assert.equal(envelope.error.retryable, false);
    assert.equal(envelope.data, null);
  }
  assert.deepEqual(seen, [], "a cross-origin forward reached the upstream");

  // The control: this origin's own `Origin` header is not a foreign one.
  const sameOrigin = await fetch(`${base}/scenario/edit`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: `http://${host}` },
    body: '{"ops":[]}',
  });
  assert.equal(sameOrigin.status, 200, "a same-origin write must still forward");
  assert.deepEqual(seen, [{ method: "POST", url: "/scenario/edit" }]);
});

test("a request body over the cap is refused by name and never reaches the upstream", async () => {
  const seen = [];
  const api = await upstream(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    seen.push({ url: req.url, bytes: Buffer.concat(chunks).length });
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
  });
  const base = await proxyOrigin(api);

  const oversized = `{"ops":"${"x".repeat(MAX_FORWARDED_BODY_BYTES + 4096)}"}`;
  const response = await fetch(`${base}/scenario/edit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: oversized,
  });
  assert.equal(response.status, 413, "an oversized body was not refused");
  assert.match(response.headers.get("content-type"), /application\/json/);
  const envelope = await response.json();
  assert.equal(envelope.status, "error");
  assert.equal(envelope.error.code, "invalid_input");
  assert.equal(envelope.error.details.reason, BODY_TOO_LARGE_REASON);
  assert.equal(envelope.error.retryable, false);
  assert.equal(envelope.data, null);
  assert.deepEqual(seen, [], "an oversized body reached the upstream");

  // The control: a body just under the cap still forwards, byte for byte.
  const filler = "y".repeat(MAX_FORWARDED_BODY_BYTES - 64);
  const allowed = `{"ops":"${filler}"}`;
  const okResponse = await fetch(`${base}/scenario/edit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: allowed,
  });
  assert.equal(okResponse.status, 200, "a body under the cap must still forward");
  assert.deepEqual(seen, [{ url: "/scenario/edit", bytes: Buffer.byteLength(allowed) }]);
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
