// The static origin under test is the real server.mjs, not a stand-in: 2WKG-300 settled the
// runtime contract as static assets only, so what has to hold is that this process serves the
// built shell and offers no demo API on any path.
import assert from "node:assert/strict";
import test, { after } from "node:test";

import { createApp } from "../server.mjs";

const servers = [];

async function origin() {
  const server = createApp().listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  const base = `http://127.0.0.1:${server.address().port}`;
  return async (path) => {
    const response = await fetch(`${base}${path}`);
    return { status: response.status, type: response.headers.get("content-type"), body: await response.text() };
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
