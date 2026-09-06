import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-perf-scene-budget-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/performance/scene-budget.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { buildSceneBudgetReport } = await import(pathToFileURL(join(outputDirectory, "scene-budget.js")).href);

function catalog() {
  return {
    budgets: {
      perArchetypeTrianglesLod0: 40000,
      perArchetypeFileBytes: 3145728,
      textureMaxPixels: 2048,
      sceneTriangleBudget: 100000,
    },
    archetypes: [
      { id: "wind_turbine", lodTriangles: { lod0: 16000, lod1: 6000, lod2: 1800 } },
      { id: "hospital", lodTriangles: { lod0: 26000, lod1: 9500, lod2: 2800 } },
    ],
  };
}

test("a scene within budget sums declared triangles and names no over-budget archetype", () => {
  const report = buildSceneBudgetReport(catalog(), [
    { archetypeId: "wind_turbine", count: 2, lod: "lod2" }, // 3600
    { archetypeId: "hospital", count: 1, lod: "lod1" }, // 9500
  ]);

  assert.equal(report.totalTriangles, 13100);
  assert.equal(report.sceneTriangleBudget, 100000);
  assert.equal(report.withinBudget, true);
  assert.deepEqual(report.overBudgetArchetypes, []);
  assert.deepEqual(report.issues, []);
  assert.equal(report.lines.length, 2);
});

test("a scene over budget names every contributing archetype, largest first", () => {
  const report = buildSceneBudgetReport(catalog(), [
    { archetypeId: "wind_turbine", count: 3, lod: "lod0" }, // 48000
    { archetypeId: "hospital", count: 3, lod: "lod0" }, // 78000
  ]);

  assert.equal(report.totalTriangles, 126000);
  assert.equal(report.withinBudget, false);
  assert.equal(report.overBudgetArchetypes.length, 2);
  assert.equal(report.overBudgetArchetypes[0].archetypeId, "hospital");
  assert.equal(report.overBudgetArchetypes[0].totalTriangles, 78000);
  assert.equal(report.overBudgetArchetypes[1].archetypeId, "wind_turbine");
});

test("an unknown archetype id is a named issue, excluded from totals, never a silent zero", () => {
  const report = buildSceneBudgetReport(catalog(), [
    { archetypeId: "does_not_exist", count: 5, lod: "lod0" },
    { archetypeId: "hospital", count: 1, lod: "lod2" },
  ]);

  assert.equal(report.issues.length, 1);
  assert.deepEqual(report.issues[0], { kind: "unknown_archetype", archetypeId: "does_not_exist" });
  assert.equal(report.totalTriangles, 2800);
  assert.equal(report.lines.length, 1);
});

test("a non-positive or non-integer count is a named issue, not coerced", () => {
  for (const count of [0, -1, 1.5, NaN, Infinity]) {
    const report = buildSceneBudgetReport(catalog(), [{ archetypeId: "hospital", count, lod: "lod0" }]);
    assert.equal(report.issues.length, 1, String(count));
    assert.equal(report.issues[0].kind, "invalid_count", String(count));
    assert.equal(report.totalTriangles, 0, String(count));
  }
});

test("an empty placement list is exactly zero triangles and within budget", () => {
  const report = buildSceneBudgetReport(catalog(), []);
  assert.equal(report.totalTriangles, 0);
  assert.equal(report.withinBudget, true);
  assert.deepEqual(report.lines, []);
});
