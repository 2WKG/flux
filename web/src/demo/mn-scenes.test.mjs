import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-scenes.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
/**
 * The module's two imports from `../minnesota/run-context` are `import type`,
 * so esbuild erases them and this bundle would compile against a run-context
 * module that had been deleted or reshaped. Re-exporting the sibling as a
 * *value* import makes the dependency real at bundle time: remove the file and
 * this build throws before a single assertion runs. `npm run typecheck` still
 * carries the type binding; this carries the existence of the module the
 * presenter script says it belongs to.
 */
await build({
  stdin: {
    contents: 'export * from "./demo/mn-scenes";\nexport * as runContext from "./minnesota/run-context";',
    resolveDir: fileURLToPath(root),
    loader: "ts",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const presenter = await import(compiled.href);

// The shell's own frozen baseline, not a second hand-written copy of it: a
// literal here could not drift-detect against the context the shell publishes.
const aggregateContext = presenter.runContext.MINNESOTA_BASELINE_RUN_CONTEXT;
const identity = presenter.runContext.createMinnesotaRunIdentity(aggregateContext, 100);

test("the presenter script binds to the Minnesota shell's own run context", () => {
  assert.equal(aggregateContext.geographyId, "mn");
  assert.equal(aggregateContext.mode, "aggregate");
  assert.equal(Object.isFrozen(aggregateContext), true);
  assert.equal(aggregateContext, presenter.runContext.resetMinnesotaRunContext());
  // Both RunIdentity fields, so a consumer can preserve stale-result protection.
  assert.equal(identity.contextRevision, presenter.runContext.minnesotaContextRevision(aggregateContext));
  assert.match(identity.attemptId, /^mn-baseline-/);
});

test("Minnesota presenter scenes are explicitly aggregate, synthetic-unavailable, and artifact-unavailable", () => {
  const scenes = presenter.listMinnesotaPresenterScenes();
  assert.deepEqual(scenes.map((scene) => scene.frame), ["aggregate", "synthetic", "unavailable"]);
  assert.match(scenes[0].presenterCue, /coverage metadata only/i);
  assert.match(scenes[1].presenterCue, /no synthetic model, topology, or camera target/i);
  assert.match(scenes[2].presenterCue, /no Minnesota feature artifact, geometry, allocation, or scenario result/i);

  // Gate 0 as an allowlist, not a five-word denylist. The previous check --
  // `doesNotMatch(/longitude|latitude|zoom|bearing|coordinates/i)` -- passed a
  // scene carrying `bbox`, `center` and `pitch`. Pinning the key set refuses
  // any new field by construction, whatever it is named.
  const allowed = ["actionLabel", "frame", "id", "presenterCue", "title"];
  for (const scene of scenes) {
    assert.deepEqual(Object.keys(scene).sort(), allowed, `scene ${scene.id} carries a field outside the allowlist`);
    for (const value of Object.values(scene)) assert.equal(typeof value, "string");
    // A secondary net over the *values*. It deliberately does not ban the words
    // "geometry" or "topology": every cue's job is to say those are absent.
    // What it bans is a value shaped like a camera or a measurement.
    const values = Object.values(scene).join(" ");
    assert.doesNotMatch(
      values,
      /-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+/,
      `scene ${scene.id} names a coordinate pair`,
    );
    assert.doesNotMatch(
      values,
      /\b\d+(?:\.\d+)?\s*(?:°|deg|km|mi|kV|MW|MVA|MWh|px|z)\b/i,
      `scene ${scene.id} names a camera or measurement value`,
    );
  }
});

test("the script is a frozen ordered list, not a mutable one a host can reorder", () => {
  const scenes = presenter.listMinnesotaPresenterScenes();
  assert.equal(Object.isFrozen(scenes), true, "the scene list is not frozen");
  assert.equal(scenes.every(Object.isFrozen), true, "a scene object is not frozen");
  assert.equal(presenter.listMinnesotaPresenterScenes(), scenes, "the list is rebuilt per call");
  assert.deepEqual(scenes.map((scene) => scene.id), [...presenter.MINNESOTA_PRESENTER_SCENE_IDS]);
});

test("an unknown scene id is a named error, never a plausible default", () => {
  assert.throws(
    () => presenter.getMinnesotaPresenterScene("mn-presenter-nope"),
    /Unknown Minnesota presenter scene: mn-presenter-nope/,
  );
  assert.throws(
    () => presenter.createMinnesotaPresenterSceneAction("mn-presenter-nope", aggregateContext, identity),
    /Unknown Minnesota presenter scene: mn-presenter-nope/,
  );
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
  // Republished by reference: the doc comment at mn-scenes.ts:83-85 claims the
  // *exact* objects a host supplied, and a structural copy would satisfy
  // deepEqual above while breaking that claim.
  assert.equal(calls[0][0], aggregateContext);
  assert.equal(calls[0][1], identity);
  assert.equal(actions[1].context, aggregateContext);
  assert.equal(actions[1].identity, identity);
});
