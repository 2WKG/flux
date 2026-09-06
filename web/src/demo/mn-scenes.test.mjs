import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-scenes.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: { contents: 'export * from "./demo/mn-scenes";', resolveDir: fileURLToPath(root), loader: "ts" },
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const presenter = await import(compiled.href);

const aggregateContext = Object.freeze({
  version: "v1",
  geographyId: "mn",
  mode: "aggregate",
  sceneId: "mn:coverage:aggregate:v1",
  artifactId: "mn:aggregate:manifest:v1",
  sceneContext: Object.freeze({
    scenario_id: null, hour: null, selected_site_id: null, compare_site_id: null, selected_element_id: null, unit_mw: null,
  }),
});
const identity = Object.freeze({ attemptId: "mn-baseline-test", contextRevision: "mn:baseline" });

test("Minnesota presenter scenes are explicitly aggregate, synthetic-unavailable, and artifact-unavailable", () => {
  const scenes = presenter.listMinnesotaPresenterScenes();
  assert.deepEqual(scenes.map((scene) => scene.frame), ["aggregate", "synthetic", "unavailable"]);
  assert.match(scenes[0].presenterCue, /coverage metadata only/i);
  assert.match(scenes[1].presenterCue, /no synthetic model, topology, or camera target/i);
  assert.match(scenes[2].presenterCue, /no Minnesota feature artifact, geometry, allocation, or scenario result/i);
  for (const scene of scenes) {
    assert.doesNotMatch(JSON.stringify(scene), /longitude|latitude|zoom|bearing|coordinates/i);
  }
});

test("named presenter actions preserve the Minnesota aggregate context and run identity", () => {
  const calls = [];
  const actions = presenter.createMinnesotaPresenterSceneActions(aggregateContext, identity, (...args) => calls.push(args));
  assert.equal(actions.length, 3);
  assert.deepEqual(actions.map((action) => action.scene.actionLabel), [
    "Present aggregate evidence baseline",
    "Present synthetic-view disclosure",
    "Present unavailable-artifact disclosure",
  ]);
  actions[1].activate();
  assert.deepEqual(calls, [[aggregateContext, identity]]);
  assert.equal(actions[1].context, aggregateContext);
  assert.equal(actions[1].identity, identity);
});
