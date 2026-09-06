import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
const { parseArchetypeCatalog, findArchetype, trianglesForLod, isDeclaredLod, checkDeliveredAsset, DECLARED_LOD_LEVELS } =
  await import(pathToFileURL(join(outputDirectory, "archetype-catalog.js")).href);

const REAL_CATALOG_PATH = new URL("../../../data/3d/asset-archetypes-v1.json", import.meta.url);

function validRawCatalog() {
  return {
    budgets: {
      perArchetypeTrianglesLod0: 40000,
      perArchetypeFileBytes: 3145728,
      textureMaxPixels: 2048,
      sceneTriangleBudget: 4000000,
      lodRule: "lod1 <= 40% of lod0 triangles, lod2 <= 12%.",
    },
    archetypes: [
      { id: "wind_turbine", lod_triangles: { lod0: 16000, lod1: 6000, lod2: 1800 } },
      { id: "hospital", lod_triangles: { lod0: 26000, lod1: 9500, lod2: 2800 } },
    ],
  };
}

test("every parsed budget equals the value the committed contract file itself declares", () => {
  const raw = JSON.parse(readFileSync(REAL_CATALOG_PATH, "utf8"));
  const result = parseArchetypeCatalog(raw);
  assert.equal(result.kind, "parsed");

  // Compared against the file's OWN values, never against a literal that a
  // hardcoding parser would also return.
  for (const field of ["perArchetypeTrianglesLod0", "perArchetypeFileBytes", "textureMaxPixels", "sceneTriangleBudget"]) {
    assert.equal(result.catalog.budgets[field], raw.budgets[field], field);
  }
  assert.equal(result.catalog.budgets.lodRule.source, raw.budgets.lodRule);

  assert.equal(result.catalog.archetypes.length, raw.archetypes.length);
  for (const rawArchetype of raw.archetypes) {
    const parsed = findArchetype(result.catalog, rawArchetype.id);
    assert.ok(parsed, rawArchetype.id);
    for (const level of DECLARED_LOD_LEVELS) {
      assert.equal(trianglesForLod(parsed, level), rawArchetype.lod_triangles[level], `${rawArchetype.id}.${level}`);
    }
  }
});

test("the parser tracks a perturbed copy of the contract, so it cannot be hardcoding", () => {
  const raw = JSON.parse(readFileSync(REAL_CATALOG_PATH, "utf8"));
  const perturbed = JSON.parse(JSON.stringify(raw));
  perturbed.budgets.perArchetypeTrianglesLod0 = 90001;
  perturbed.budgets.perArchetypeFileBytes = 90002;
  perturbed.budgets.textureMaxPixels = 90003;
  perturbed.budgets.sceneTriangleBudget = 9000004;
  perturbed.budgets.lodRule = "lod1 <= 90% of lod0 triangles, lod2 <= 80%.";
  perturbed.archetypes[0].lod_triangles = { lod0: 12345, lod1: 6001, lod2: 4002 };

  // The perturbed copy is written to disk and re-read, so this exercises the
  // same "read a file, parse it" path as the real contract above.
  const copyPath = join(outputDirectory, "perturbed-catalog.json");
  writeFileSync(copyPath, JSON.stringify(perturbed), "utf8");
  const result = parseArchetypeCatalog(JSON.parse(readFileSync(copyPath, "utf8")));

  assert.equal(result.kind, "parsed", JSON.stringify(result));
  assert.equal(result.catalog.budgets.perArchetypeTrianglesLod0, 90001);
  assert.equal(result.catalog.budgets.perArchetypeFileBytes, 90002);
  assert.equal(result.catalog.budgets.textureMaxPixels, 90003);
  assert.equal(result.catalog.budgets.sceneTriangleBudget, 9000004);
  assert.equal(result.catalog.budgets.lodRule.lod1MaxShareOfLod0, 0.9);
  assert.equal(result.catalog.budgets.lodRule.lod2MaxShareOfLod0, 0.8);
  assert.deepEqual(findArchetype(result.catalog, perturbed.archetypes[0].id).lodTriangles, {
    lod0: 12345,
    lod1: 6001,
    lod2: 4002,
  });
  // ...and the real file's own values are NOT what came back.
  assert.notEqual(result.catalog.budgets.sceneTriangleBudget, raw.budgets.sceneTriangleBudget);
});

test("contract-drift alarm: the committed contract still declares the values this module was written against", () => {
  // Deliberate literals. This is the ONLY test allowed to pin them, and it
  // exists to fire when the contract changes -- not to prove the parser reads
  // it (the two tests above do that).
  const raw = JSON.parse(readFileSync(REAL_CATALOG_PATH, "utf8"));
  assert.equal(raw.budgets.sceneTriangleBudget, 4000000);
  assert.equal(raw.budgets.perArchetypeTrianglesLod0, 40000);
  assert.equal(raw.budgets.perArchetypeFileBytes, 3145728);
  assert.equal(raw.budgets.textureMaxPixels, 2048);
  assert.ok(raw.archetypes.length >= 18);
});

test("the LOD reduction rule is read out of budgets.lodRule, not typed here", () => {
  const raw = JSON.parse(readFileSync(REAL_CATALOG_PATH, "utf8"));
  const result = parseArchetypeCatalog(raw);
  const { lodRule } = result.catalog.budgets;

  // The shares must come from the sentence, so re-derive them from it.
  const lod1Percent = Number(/lod1\s*<=\s*([0-9.]+)\s*%/i.exec(raw.budgets.lodRule)[1]);
  const lod2Percent = Number(/lod2\s*<=\s*([0-9.]+)\s*%/i.exec(raw.budgets.lodRule)[1]);
  assert.equal(lodRule.lod1MaxShareOfLod0, lod1Percent / 100);
  assert.equal(lodRule.lod2MaxShareOfLod0, lod2Percent / 100);

  for (const bad of [undefined, "", 40, "lod1 must be smaller than lod0"]) {
    const broken = validRawCatalog();
    broken.budgets.lodRule = bad;
    const rejection = parseArchetypeCatalog(broken);
    assert.equal(rejection.kind, "rejected", JSON.stringify(bad));
    assert.equal(rejection.reason, "invalid_lod_rule", JSON.stringify(bad));
  }
});

test("a LOD chain that does not reduce is refused by the catalog's own percentages", () => {
  const flat = validRawCatalog();
  flat.archetypes = [{ id: "x", lod_triangles: { lod0: 1000, lod1: 1000, lod2: 1000 } }];
  const flatResult = parseArchetypeCatalog(flat);
  assert.equal(flatResult.kind, "rejected");
  assert.equal(flatResult.reason, "lod_chain_does_not_reduce");
  assert.match(flatResult.detail, /lod1/);

  const lod2TooBig = validRawCatalog();
  lod2TooBig.archetypes = [{ id: "x", lod_triangles: { lod0: 1000, lod1: 400, lod2: 121 } }];
  assert.equal(parseArchetypeCatalog(lod2TooBig).reason, "lod_chain_does_not_reduce");

  // Exactly at the ceilings is accepted.
  const atCeiling = validRawCatalog();
  atCeiling.archetypes = [{ id: "x", lod_triangles: { lod0: 1000, lod1: 400, lod2: 120 } }];
  assert.equal(parseArchetypeCatalog(atCeiling).kind, "parsed");

  // A looser rule in the catalog loosens the check: the rule is data, not code.
  const looser = validRawCatalog();
  looser.budgets.lodRule = "lod1 <= 100% of lod0 triangles, lod2 <= 100%.";
  looser.archetypes = [{ id: "x", lod_triangles: { lod0: 1000, lod1: 1000, lod2: 1000 } }];
  assert.equal(parseArchetypeCatalog(looser).kind, "parsed");
});

test("an archetype above perArchetypeTrianglesLod0 is refused, so the budget is not inert", () => {
  const overCap = validRawCatalog();
  overCap.archetypes = [{ id: "x", lod_triangles: { lod0: 40001, lod1: 100, lod2: 100 } }];
  const result = parseArchetypeCatalog(overCap);
  assert.equal(result.kind, "rejected");
  assert.equal(result.reason, "lod0_over_budget");
  assert.match(result.detail, /40001/);

  // Raising the catalog's own ceiling accepts the same archetype.
  const raised = validRawCatalog();
  raised.budgets.perArchetypeTrianglesLod0 = 50000;
  raised.archetypes = [{ id: "x", lod_triangles: { lod0: 40001, lod1: 100, lod2: 100 } }];
  assert.equal(parseArchetypeCatalog(raised).kind, "parsed");
});

test("perArchetypeFileBytes and textureMaxPixels are checked against a delivered asset", () => {
  const { catalog } = parseArchetypeCatalog(validRawCatalog());

  assert.deepEqual(
    checkDeliveredAsset(catalog, { archetypeId: "wind_turbine", fileBytes: 3145728, textureMaxPixels: 2048 }),
    [],
  );

  const violations = checkDeliveredAsset(catalog, {
    archetypeId: "wind_turbine",
    fileBytes: 3145729,
    textureMaxPixels: 4096,
  });
  assert.deepEqual(
    violations.map((violation) => violation.kind),
    ["file_too_large", "texture_too_large"],
  );
  assert.equal(violations[0].ceiling, catalog.budgets.perArchetypeFileBytes);
  assert.equal(violations[1].ceiling, catalog.budgets.textureMaxPixels);

  // The ceilings come from the catalog, not from constants in the module.
  const generous = validRawCatalog();
  generous.budgets.perArchetypeFileBytes = 10485760;
  generous.budgets.textureMaxPixels = 8192;
  const generousCatalog = parseArchetypeCatalog(generous).catalog;
  assert.deepEqual(
    checkDeliveredAsset(generousCatalog, { archetypeId: "wind_turbine", fileBytes: 3145729, textureMaxPixels: 4096 }),
    [],
  );
});

test("isDeclaredLod answers from the archetype's own declared counts", () => {
  const { catalog } = parseArchetypeCatalog(validRawCatalog());
  const turbine = findArchetype(catalog, "wind_turbine");
  for (const level of DECLARED_LOD_LEVELS) {
    assert.equal(isDeclaredLod(turbine, level), true, level);
  }
  for (const bad of ["lod3", "LOD0", "", "toString", undefined, null, 0]) {
    assert.equal(isDeclaredLod(turbine, bad), false, JSON.stringify(bad));
  }
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
