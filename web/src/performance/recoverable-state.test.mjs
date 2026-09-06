import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-perf-recoverable-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/performance/recoverable-state.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  HEALTHY_STATE,
  reportWebglLost,
  recoverFromWebglLost,
  reportGeometryMissing,
  reportPartialLoad,
  deriveBudgetState,
} = await import(pathToFileURL(join(outputDirectory, "recoverable-state.js")).href);
const { buildSceneBudgetReport } = await import(pathToFileURL(join(outputDirectory, "scene-budget.js")).href);

test("a lost WebGL context is named and recoverable, never a dead end", () => {
  const lost = reportWebglLost("context lost event fired");
  assert.equal(lost.kind, "webgl_lost");
  assert.equal(lost.nextStep, "reset_context");

  const recovered = recoverFromWebglLost(lost);
  assert.deepEqual(recovered, HEALTHY_STATE);
});

test("recovering from a non-lost state is a no-op that still returns a defined state", () => {
  assert.deepEqual(recoverFromWebglLost(HEALTHY_STATE), HEALTHY_STATE);
});

test("geometry_missing names the archetype and defaults to a retry step", () => {
  const missing = reportGeometryMissing("hospital", "404 fetching hospital.glb");
  assert.equal(missing.kind, "geometry_missing");
  assert.equal(missing.archetypeId, "hospital");
  assert.equal(missing.nextStep, "retry_fetch");

  const exhausted = reportGeometryMissing("hospital", "retry limit exceeded", "report_unavailable");
  assert.equal(exhausted.nextStep, "report_unavailable");
});

test("partial_load carries loaded vs. expected bytes and a resume step", () => {
  const partial = reportPartialLoad("hospital", 1024, 4096);
  assert.equal(partial.kind, "partial_load");
  assert.equal(partial.loadedBytes, 1024);
  assert.equal(partial.expectedBytes, 4096);
  assert.equal(partial.nextStep, "resume_stream");
  assert.match(partial.detail, /1024/);
  assert.match(partial.detail, /4096/);
});

test("a budget report that fits derives the healthy state", () => {
  const catalog = {
    budgets: { perArchetypeTrianglesLod0: 40000, perArchetypeFileBytes: 1, textureMaxPixels: 1, sceneTriangleBudget: 100000 },
    archetypes: [{ id: "wind_turbine", lodTriangles: { lod0: 16000, lod1: 6000, lod2: 1800 } }],
  };
  const report = buildSceneBudgetReport(catalog, [{ archetypeId: "wind_turbine", count: 1, lod: "lod2" }]);
  assert.deepEqual(deriveBudgetState(report), HEALTHY_STATE);
});

test("a budget report that does not fit derives over_budget naming every contributor", () => {
  const catalog = {
    budgets: { perArchetypeTrianglesLod0: 40000, perArchetypeFileBytes: 1, textureMaxPixels: 1, sceneTriangleBudget: 10000 },
    archetypes: [{ id: "wind_turbine", lodTriangles: { lod0: 16000, lod1: 6000, lod2: 1800 } }],
  };
  const report = buildSceneBudgetReport(catalog, [{ archetypeId: "wind_turbine", count: 1, lod: "lod0" }]);
  const state = deriveBudgetState(report);
  assert.equal(state.kind, "over_budget");
  assert.equal(state.totalTriangles, 16000);
  assert.equal(state.sceneTriangleBudget, 10000);
  assert.equal(state.overBudgetArchetypes.length, 1);
  assert.equal(state.overBudgetArchetypes[0].archetypeId, "wind_turbine");
  assert.equal(state.nextStep, "reduce_lod_or_placements");
});
