import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-perf-catalog-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/performance/archetype-catalog.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { parseArchetypeCatalog, findArchetype, trianglesForLod } = await import(
  pathToFileURL(join(outputDirectory, "archetype-catalog.js")).href
);

const REAL_CATALOG_PATH = new URL("../../../data/3d/asset-archetypes-v1.json", import.meta.url);

function validRawCatalog() {
  return {
    budgets: {
      perArchetypeTrianglesLod0: 40000,
      perArchetypeFileBytes: 3145728,
      textureMaxPixels: 2048,
      sceneTriangleBudget: 4000000,
    },
    archetypes: [
      { id: "wind_turbine", lod_triangles: { lod0: 16000, lod1: 6000, lod2: 1800 } },
      { id: "hospital", lod_triangles: { lod0: 26000, lod1: 9500, lod2: 2800 } },
    ],
  };
}

test("parses the real committed asset-archetypes-v1.json contract", () => {
  const raw = JSON.parse(readFileSync(REAL_CATALOG_PATH, "utf8"));
  const result = parseArchetypeCatalog(raw);

  assert.equal(result.kind, "parsed");
  assert.equal(result.catalog.budgets.sceneTriangleBudget, 4000000);
  assert.equal(result.catalog.budgets.perArchetypeTrianglesLod0, 40000);
  assert.ok(result.catalog.archetypes.length >= 18);

  const transmissionLine = findArchetype(result.catalog, "transmission_line_segment");
  assert.ok(transmissionLine);
  assert.equal(trianglesForLod(transmissionLine, "lod0"), 18000);
  assert.equal(trianglesForLod(transmissionLine, "lod2"), 2000);
});

test("a valid minimal catalog parses with the declared fields intact", () => {
  const result = parseArchetypeCatalog(validRawCatalog());
  assert.equal(result.kind, "parsed");
  assert.equal(result.catalog.archetypes.length, 2);
  const turbine = findArchetype(result.catalog, "wind_turbine");
  assert.deepEqual(turbine.lodTriangles, { lod0: 16000, lod1: 6000, lod2: 1800 });
  assert.equal(findArchetype(result.catalog, "does_not_exist"), undefined);
});

test("a non-object document is refused, never treated as an empty catalog", () => {
  for (const payload of [null, undefined, [], "catalog", 42]) {
    const result = parseArchetypeCatalog(payload);
    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "not_an_object");
  }
});

test("a missing or invalid budget field is a named rejection, not a default", () => {
  const missingBudgets = parseArchetypeCatalog({ ...validRawCatalog(), budgets: undefined });
  assert.equal(missingBudgets.reason, "missing_budgets");

  for (const field of ["perArchetypeTrianglesLod0", "perArchetypeFileBytes", "textureMaxPixels", "sceneTriangleBudget"]) {
    const raw = validRawCatalog();
    raw.budgets[field] = 0;
    const result = parseArchetypeCatalog(raw);
    assert.equal(result.kind, "rejected", field);
    assert.equal(result.reason, "invalid_budget_field", field);
    assert.match(result.detail, new RegExp(field));
  }
});

test("missing, empty, or malformed archetypes are refused", () => {
  assert.equal(parseArchetypeCatalog({ ...validRawCatalog(), archetypes: undefined }).reason, "missing_archetypes");
  assert.equal(parseArchetypeCatalog({ ...validRawCatalog(), archetypes: [] }).reason, "empty_archetypes");

  const noId = parseArchetypeCatalog({
    ...validRawCatalog(),
    archetypes: [{ lod_triangles: { lod0: 1, lod1: 1, lod2: 1 } }],
  });
  assert.equal(noId.reason, "invalid_archetype");

  const badLod = parseArchetypeCatalog({
    ...validRawCatalog(),
    archetypes: [{ id: "x", lod_triangles: { lod0: 1, lod1: 1 } }],
  });
  assert.equal(badLod.reason, "invalid_archetype");

  const zeroLod = parseArchetypeCatalog({
    ...validRawCatalog(),
    archetypes: [{ id: "x", lod_triangles: { lod0: 0, lod1: 1, lod2: 1 } }],
  });
  assert.equal(zeroLod.reason, "invalid_archetype");
});
