// This rehearsal test deliberately exercises the shipped static origin. The demo is
// an offline synthetic preview, so it must remain honest about its data while still
// serving a complete, usable bundle when no API or SSE process is running.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import { createApp } from "../server.mjs";

const fixtureUrl = new URL("../../data/demo/bundle.json", import.meta.url);
const servers = [];

async function startOrigin() {
  const server = createApp().listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

async function response(base, path, init) {
  const result = await fetch(`${base}${path}`, init);
  return {
    status: result.status,
    type: result.headers.get("content-type") ?? "",
    body: await result.text(),
  };
}

after(async () => {
  await Promise.all(servers.map((server) => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  }));
});

test("the rehearsal artifact keeps displayed scenario balances internally consistent", async () => {
  const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));

  for (const [id, scenario] of Object.entries(fixture.scenarios)) {
    assert.equal(scenario.metrics.availableGenerationMw + scenario.metrics.shedMw, scenario.metrics.demandMw, `${id} does not balance`);
  }
});

test("the rehearsal static origin serves the demo but never substitutes an API or SSE", async () => {
  const base = await startOrigin();
  const root = await response(base, "/");
  assert.equal(root.status, 200);
  assert.match(root.type, /^text\/html/);
  const asset = root.body.match(/<script type="module" src="(\/assets\/app\.js)"><\/script>/)?.[1];
  assert.ok(asset, "the rehearsal shell must reference the bundled application");

  const app = await response(base, asset);
  assert.equal(app.status, 200);
  assert.match(app.type, /javascript/);
  const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
  assert.ok(app.body.includes(fixture.fixtureHash), "the served bundle must identify its checked-in fixture");

  const staleDemoRoute = await response(base, "/api/demo");
  assert.equal(staleDemoRoute.status, 200);
  assert.doesNotMatch(staleDemoRoute.type, /json/);
  assert.equal(staleDemoRoute.body, root.body);

  const ask = await response(base, "/ask", { method: "POST", body: "{}" });
  assert.equal(ask.status, 404);
  assert.doesNotMatch(ask.type, /text\/event-stream/);
  assert.doesNotMatch(ask.type, /json/);
  assert.equal(ask.body.includes("answer"), false);
});
