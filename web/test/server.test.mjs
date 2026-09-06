import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, copyFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after, before } from "node:test";

import { createApp } from "../server.mjs";

const realBundle = new URL("../../data/demo/bundle.json", import.meta.url);
let tmp;
const servers = [];

async function serve(bundlePath) {
  const server = createApp({ bundle: pathToFileURL(bundlePath) }).listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  servers.push(server);
  return async (query) => {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/demo${query}`);
    return { status: response.status, body: await response.json() };
  };
}

before(async () => {
  tmp = await mkdtemp(path.join(os.tmpdir(), "flux-server-"));
  await copyFile(realBundle, path.join(tmp, "bundle.json"));
  await writeFile(path.join(tmp, "no-scenarios.json"), JSON.stringify({ schemaVersion: 2 }));
  await writeFile(path.join(tmp, "array-scenarios.json"), JSON.stringify({ scenarios: [{ id: "baseline" }] }));
  await writeFile(path.join(tmp, "corrupt.json"), "{not json");
});

after(async () => {
  await Promise.all(servers.map((server) => { server.closeAllConnections(); return new Promise((resolve) => server.close(resolve)); }));
  await rm(tmp, { recursive: true, force: true });
});

test("listed scenarios are available and echo the selected id", async () => {
  const get = await serve(path.join(tmp, "bundle.json"));
  for (const [query, id] of [["", "baseline"], ["?scenario=baseline", "baseline"], ["?scenario=a", "a"], ["?scenario=b", "b"]]) {
    const { status, body } = await get(query);
    assert.equal(status, 200, query);
    assert.equal(body.status, "available");
    assert.equal(body.selectedScenarioId, id);
    assert.ok(Object.hasOwn(body.data.scenarios, id));
  }
});

test("prototype-chain and unknown ids get the SCENARIO_NOT_FOUND envelope", async () => {
  const get = await serve(path.join(tmp, "bundle.json"));
  for (const id of ["constructor", "__proto__", "toString", "hasOwnProperty", "valueOf", "zzz", ""]) {
    const { status, body } = await get(`?scenario=${encodeURIComponent(id)}`);
    assert.equal(status, 404, id);
    assert.deepEqual(
      { status: body.status, code: body.code, hasMessage: typeof body.message === "string", hasNextStep: typeof body.nextStep === "string" },
      { status: "unavailable", code: "SCENARIO_NOT_FOUND", hasMessage: true, hasNextStep: true },
      id,
    );
    assert.equal(body.data, undefined, `${id} must not leak the bundle`);
  }
});

test("repeated or bracketed scenario params are rejected instead of defaulting to baseline", async () => {
  const get = await serve(path.join(tmp, "bundle.json"));
  for (const query of ["?scenario=a&scenario=b", "?scenario[]=a", "?scenario[0]=a", "?scenario=a&scenario[]=b"]) {
    const { status, body } = await get(query);
    assert.equal(status, 400, query);
    assert.equal(body.status, "unavailable", query);
    assert.equal(body.code, "SCENARIO_ID_INVALID", query);
    assert.equal(body.selectedScenarioId, undefined, `${query} silently picked a scenario`);
    assert.equal(body.data, undefined);
  }
});

test("a bundle without a scenario table is DEMO_BUNDLE_INVALID, not SCENARIO_NOT_FOUND", async () => {
  for (const file of ["no-scenarios.json", "array-scenarios.json"]) {
    const get = await serve(path.join(tmp, file));
    const { status, body } = await get("");
    assert.equal(status, 500, file);
    assert.equal(body.status, "failed");
    assert.equal(body.code, "DEMO_BUNDLE_INVALID");
  }
});

test("missing and corrupt bundles keep their 503/500 split", async () => {
  const missing = await serve(path.join(tmp, "does-not-exist.json"));
  const gone = await missing("");
  assert.equal(gone.status, 503);
  assert.equal(gone.body.code, "DEMO_INPUT_UNAVAILABLE");

  const corrupt = await serve(path.join(tmp, "corrupt.json"));
  const bad = await corrupt("");
  assert.equal(bad.status, 500);
  assert.equal(bad.body.code, "DEMO_BUNDLE_INVALID");
});
