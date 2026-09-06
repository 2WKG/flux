import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-perf-culling-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/performance/culling-instancing.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { isInView, cullToView, canInstanceTogether, groupForInstancing, cullAndGroupForInstancing } = await import(
  pathToFileURL(join(outputDirectory, "culling-instancing.js")).href
);

const VIEW = { centerXMeters: 0, centerZMeters: 0, radiusMeters: 100 };

test("a point inside the view radius is in view; one outside is not", () => {
  assert.equal(isInView({ archetypeId: "a", lod: "lod0", xMeters: 50, zMeters: 0 }, VIEW), true);
  assert.equal(isInView({ archetypeId: "a", lod: "lod0", xMeters: 100, zMeters: 0 }, VIEW), true); // on boundary
  assert.equal(isInView({ archetypeId: "a", lod: "lod0", xMeters: 101, zMeters: 0 }, VIEW), false);
  assert.equal(isInView({ archetypeId: "a", lod: "lod0", xMeters: 80, zMeters: 80 }, VIEW), false);
});

test("cullToView partitions visible vs. culled and reports the culled count", () => {
  const points = [
    { archetypeId: "a", lod: "lod0", xMeters: 0, zMeters: 0 },
    { archetypeId: "a", lod: "lod0", xMeters: 500, zMeters: 500 },
    { archetypeId: "b", lod: "lod0", xMeters: -10, zMeters: 10 },
  ];
  const { visible, culledCount } = cullToView(points, VIEW);
  assert.equal(visible.length, 2);
  assert.equal(culledCount, 1);
});

test("same archetype and same LOD can instance together; different archetype or LOD cannot", () => {
  const a0 = { archetypeId: "wind_turbine", lod: "lod0", xMeters: 0, zMeters: 0 };
  const a0b = { archetypeId: "wind_turbine", lod: "lod0", xMeters: 5, zMeters: 5 };
  const a1 = { archetypeId: "wind_turbine", lod: "lod1", xMeters: 0, zMeters: 0 };
  const b0 = { archetypeId: "hospital", lod: "lod0", xMeters: 0, zMeters: 0 };

  assert.equal(canInstanceTogether(a0, a0b), true);
  assert.equal(canInstanceTogether(a0, a1), false);
  assert.equal(canInstanceTogether(a0, b0), false);
});

test("groupForInstancing partitions by archetype+LOD and preserves first-seen order", () => {
  const points = [
    { archetypeId: "wind_turbine", lod: "lod0", xMeters: 0, zMeters: 0 },
    { archetypeId: "hospital", lod: "lod0", xMeters: 1, zMeters: 1 },
    { archetypeId: "wind_turbine", lod: "lod0", xMeters: 2, zMeters: 2 },
    { archetypeId: "wind_turbine", lod: "lod1", xMeters: 3, zMeters: 3 },
  ];
  const groups = groupForInstancing(points);
  assert.equal(groups.length, 3);
  assert.equal(groups[0].archetypeId, "wind_turbine");
  assert.equal(groups[0].lod, "lod0");
  assert.equal(groups[0].instances.length, 2);
  assert.equal(groups[1].archetypeId, "hospital");
  assert.equal(groups[2].lod, "lod1");
});

test("cullAndGroupForInstancing culls first, then groups only the survivors", () => {
  const points = [
    { archetypeId: "wind_turbine", lod: "lod0", xMeters: 0, zMeters: 0 },
    { archetypeId: "wind_turbine", lod: "lod0", xMeters: 900, zMeters: 900 }, // culled
  ];
  const { groups, culledCount } = cullAndGroupForInstancing(points, VIEW);
  assert.equal(culledCount, 1);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].instances.length, 1);
});

test("an empty placement list culls and groups to nothing", () => {
  const { groups, culledCount } = cullAndGroupForInstancing([], VIEW);
  assert.deepEqual(groups, []);
  assert.equal(culledCount, 0);
});
