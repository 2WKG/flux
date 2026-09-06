// The shipped static origin intentionally has no FastAPI layer route. The
// browser must therefore receive the application shell and use MainPage's
// named five-bus fallback, never a plausible map payload.
import assert from "node:assert/strict";
import test, { after } from "node:test";

import { createApp } from "../server.mjs";
import { builtScriptNames } from "./built-assets.mjs";

const servers = [];

async function startOrigin() {
  const server = createApp().listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

async function response(base, path, init) {
  const result = await fetch(`${base}${path}`, init);
  return { status: result.status, type: result.headers.get("content-type") ?? "", body: await result.text() };
}

after(async () => {
  await Promise.all(servers.map((server) => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  }));
});

test("the rehearsal origin serves the main route and every split script", async () => {
  const base = await startOrigin();
  const root = await response(base, "/");
  assert.equal(root.status, 200);
  assert.match(root.type, /^text\/html/);
  assert.match(root.body, /<script type="module" src="\/assets\/app\.js"><\/script>/);

  const served = [];
  for (const name of await builtScriptNames()) {
    const chunk = await response(base, `/assets/${name}`);
    assert.equal(chunk.status, 200, `${name} is not served`);
    assert.match(chunk.type, /javascript/, `${name} is not served as a script`);
    served.push(chunk.body);
  }
  const app = served.join("\n");
  assert.match(app, /\/layers\/buses/);
  assert.match(app, /OFFLINE FALLBACK · SYNTHETIC FIVE-BUS FIXTURE/);
});

test("the rehearsal origin never substitutes a map-layer or copilot response", async () => {
  const base = await startOrigin();
  const root = await response(base, "/");
  const layer = await response(base, "/layers/buses");
  const ask = await response(base, "/ask", { method: "POST", body: "{}" });

  assert.equal(layer.status, 200);
  assert.doesNotMatch(layer.type, /geo\+json|json/);
  assert.equal(layer.body, root.body);
  assert.throws(() => JSON.parse(layer.body));
  assert.equal(ask.status, 404);
  assert.doesNotMatch(ask.type, /text\/event-stream|json/);
});
