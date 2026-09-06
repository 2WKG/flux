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
