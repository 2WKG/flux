// This rehearsal test deliberately exercises the shipped static origin. The demo is
// an offline synthetic preview, so it must remain honest about its data while still
// serving a complete, usable bundle when no API or SSE process is running.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import { createApp } from "../server.mjs";

const fixtureUrl = new URL("../../data/demo/bundle.json", import.meta.url);
const sourceUrl = new URL("../src/main.tsx", import.meta.url);
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

test("the rehearsal artifact keeps displayed scenario numbers internally consistent", async () => {
  const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
  const source = await readFile(sourceUrl, "utf8");
  const { assumptions, provenance, limitations } = fixture.execution;

  assert.equal(fixture.schemaVersion, 2);
  assert.equal(provenance.inputHash, fixture.fixtureHash);
  assert.match(provenance.sourceId, /synthetic/i);
  assert.match(provenance.scope, /not a Minnesota, Texas, ERCOT, MISO, or actual interconnection model/i);
  assert.ok(limitations.some((item) => /not a grid-flow, outage forecast/i.test(item)));

  for (const [id, scenario] of Object.entries(fixture.scenarios)) {
    assert.equal(scenario.assumptionSetId, assumptions.id, `${id} changes the shared assumptions`);
    assert.deepEqual(scenario.provenance, provenance, `${id} loses artifact lineage`);
    assert.deepEqual(scenario.limitations, limitations, `${id} loses the visible limitations`);
    assert.equal(scenario.metrics.demandMw, assumptions.demandMw, `${id} changes demand`);
    assert.equal(scenario.metrics.shedMwh, scenario.metrics.shedMw * assumptions.durationHours, `${id} has inconsistent duration`);
    assert.equal(scenario.metrics.availableGenerationMw + scenario.metrics.shedMw, scenario.metrics.demandMw, `${id} does not balance`);
    assert.deepEqual(scenario.units, {
      shedMw: "MW", shedMwh: "MWh", availableGenerationMw: "MW", demandMw: "MW", improvementMw: "MW", lineLoading: "%",
    });
  }

  const baseline = fixture.scenarios.baseline;
  assert.equal(baseline.intervention, null);
  assert.equal(baseline.metrics.improvementMw, 0);
  for (const id of ["a", "b"]) {
    const scenario = fixture.scenarios[id];
    assert.equal(scenario.intervention.id, id);
    assert.equal(scenario.intervention.capacityMw, 300);
    assert.equal(scenario.intervention.modeledContributionMw, scenario.metrics.improvementMw);
    assert.equal(baseline.metrics.shedMw - scenario.metrics.shedMw, scenario.metrics.improvementMw);
  }

  assert.match(source, /no runtime request,\s*and no claim about a real grid/i);
  assert.match(source, /A fixture assumption, not an interconnection result/i);
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
  assert.match(app.body, /bundled synthetic fixture/);
  assert.match(app.body, /no API required/);

  const staleDemoRoute = await response(base, "/api/demo");
  assert.equal(staleDemoRoute.status, 200);
  assert.doesNotMatch(staleDemoRoute.type, /json/);
  assert.equal(staleDemoRoute.body, root.body);

  const ask = await response(base, "/ask", { method: "POST", body: "{}" });
  assert.equal(ask.status, 404);
  assert.doesNotMatch(ask.type, /text\/event-stream/);
});
