// This rehearsal test deliberately exercises the shipped static origin. The demo is
// an offline synthetic preview, so it must remain honest about its data while still
// serving a complete, usable bundle when no API or SSE process is running.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import { createApp } from "../server.mjs";
import { builtScriptNames } from "./built-assets.mjs";

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

  // The entry is split per page (2WKG-478), so the fixture rides in the scenario
  // page's chunk. Every emitted script must be served, and the fixture must be in
  // one of them.
  const served = [];
  for (const name of await builtScriptNames()) {
    const chunk = await response(base, `/assets/${name}`);
    assert.equal(chunk.status, 200, `${name} is not served`);
    assert.match(chunk.type, /javascript/, `${name} is not served as a script`);
    served.push(chunk.body);
  }
  const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
  assert.ok(served.join("\n").includes(fixture.fixtureHash), "the served bundle must identify its checked-in fixture");

  const staleDemoRoute = await response(base, "/api/demo");
  assert.equal(staleDemoRoute.status, 503);
  assert.doesNotMatch(staleDemoRoute.type, /json/);
  assert.match(staleDemoRoute.body, /does not serve API routes/i);

  // `/ask` is on `server.mjs`'s allowlist, so with no upstream configured it
  // now refuses by name instead of 404ing off the end of the router. That is a
  // stronger refusal, not a weaker one, and this test's actual subject is
  // unchanged: the origin must never *substitute* an API. So: no SSE, no
  // invented answer, no payload -- just the named unavailable envelope.
  const ask = await response(base, "/ask", { method: "POST", body: "{}" });
  assert.equal(ask.status, 503);
  assert.doesNotMatch(ask.type, /text\/event-stream/);
  const refusal = JSON.parse(ask.body);
  assert.equal(refusal.status, "unavailable");
  assert.equal(refusal.data, null, "a refusal must carry no payload");
  assert.equal(refusal.error.details.reason, "no_api_origin_configured");
  assert.ok(refusal.error.message.trim().length > 0);
  assert.equal(ask.body.includes("answer"), false, "the refusal must not contain an answer");
});
