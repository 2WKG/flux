import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-search-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Run tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
// `--rootDir src` pins the emitted layout, because search.ts now imports the shared
// vocabulary (src/labels.ts) and the real scene adapter (src/scene/minnesota-adapter.ts).
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/navigation/search.ts",
    "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext",
    "--rootDir", "src", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { candidateFromScene, search } = await import(
  pathToFileURL(join(outputDirectory, "navigation", "search.js")).href
);
const { ASSET_STATUS_TOKENS } = await import(pathToFileURL(join(outputDirectory, "labels.js")).href);
const { adaptAggregateCoverage, adaptBoundPlacement, adaptLayerToScene, REQUIRED_CRS } = await import(
  pathToFileURL(join(outputDirectory, "scene", "minnesota-adapter.js")).href
);

/**
 * Shaped exactly like `bind_asset` returns a `render_mode: "placed"` binding
 * (pipelines/minnesota_asset_binding.py), copied from the fixture
 * src/scene/minnesota-adapter.test.mjs already pins. Candidates in this file
 * are produced by running that payload through the real adapter, never typed
 * out by hand -- the shape under test is the one a producer actually emits.
 */
function binding(overrides = {}) {
  return {
    render_mode: "placed",
    scene_id: "mn:scene:coverage:v1:facility-1",
    source_artifact_id: "mn:scene:coverage:v1",
    semantic_type: "network",
    archetype_id: "transmission_line_segment",
    crs: REQUIRED_CRS,
    coordinates: { longitude: -93.26, latitude: 44.98, crs: REQUIRED_CRS },
    footprint_m: [40, 40],
    connectors: ["HV_BUS"],
    lod_triangles: { lod0: 30000 },
    material: { slot: "MAT_STATUS", status_label: "source_supported" },
    ...overrides,
  };
}

/** The only supported way to obtain a candidate: project a real adapter output. */
function candidateFromBinding(overrides = {}) {
  const adaptation = adaptBoundPlacement(binding(overrides));
  assert.equal(adaptation.kind, "bound_placement", JSON.stringify(adaptation));
  const projection = candidateFromScene(adaptation);
  assert.equal(projection.kind, "candidate", JSON.stringify(projection));
  return projection.candidate;
}

test("a candidate is a verbatim projection of a real adapter placement -- no invented field", () => {
  const adaptation = adaptBoundPlacement(binding());
  const projection = candidateFromScene(adaptation);
  assert.equal(projection.kind, "candidate");
  // Every field, and only these fields, come straight off the placement.
  assert.deepEqual(projection.candidate, {
    id: adaptation.placement.id,
    sourceArtifactId: adaptation.placement.sourceArtifactId,
    archetypeId: adaptation.placement.archetypeId,
    semanticType: adaptation.placement.semanticType,
    position: adaptation.placement.position,
    statusLabel: adaptation.placement.statusLabel,
  });
  assert.deepEqual(Object.keys(projection.candidate).sort(), [
    "archetypeId",
    "id",
    "position",
    "semanticType",
    "sourceArtifactId",
    "statusLabel",
  ]);
  // The server's own values, unaltered.
  assert.equal(projection.candidate.id, "mn:scene:coverage:v1:facility-1");
  assert.deepEqual(projection.candidate.position, [-93.26, 44.98]);
  assert.equal(projection.candidate.statusLabel, "source_supported");
});

test("a real adapter placement searches end to end and is returned verbatim", () => {
  const candidate = candidateFromBinding();
  const outcome = search([candidate], { text: "transmission" });
  assert.deepEqual(outcome.results, [candidate]);
  assert.deepEqual(outcome.excluded, []);
});

test("the adapter's non-placement outputs are named as not searchable, never coerced", () => {
  const aggregate = adaptAggregateCoverage({
    format: "flux-minnesota-aggregate-v1",
    model_mode: "aggregate",
    allocation_status: "source_screened",
    allocation_limit: "county",
    sources: [{ id: "mn:aggregate:v1" }],
  });
  assert.equal(aggregate.kind, "aggregate_coverage");
  const fromAggregate = candidateFromScene(aggregate);
  assert.equal(fromAggregate.kind, "not_searchable");
  assert.equal(fromAggregate.reason, "aggregate_only_no_geometry");

  const refused = adaptLayerToScene({ type: "NotACollection" });
  assert.equal(refused.kind, "rejected");
  const fromRefusal = candidateFromScene(refused);
  assert.equal(fromRefusal.kind, "not_searchable");
  assert.equal(fromRefusal.reason, "no_scene_binding");
  assert.match(fromRefusal.detail, /malformed_collection/);
});

test("search matches case-insensitively against the ids and type the server sent", () => {
  const candidate = candidateFromBinding();
  assert.equal(search([candidate], { text: "TRANSMISSION" }).results.length, 1);
  assert.equal(search([candidate], { text: "facility-1" }).results.length, 1);
  assert.equal(search([candidate], { text: "network" }).results.length, 1);
  assert.equal(search([candidate], { text: "no-such-term" }).results.length, 0);
});

test("empty query text matches every candidate", () => {
  const candidates = [
    candidateFromBinding(),
    candidateFromBinding({ scene_id: "mn:scene:coverage:v1:facility-2" }),
  ];
  assert.equal(search(candidates, { text: "   " }).results.length, 2);
});

test("semanticType and archetypeId filters are exact-match", () => {
  const network = candidateFromBinding();
  const substation = candidateFromBinding({
    scene_id: "mn:scene:coverage:v1:facility-2",
    semantic_type: "substation",
    archetype_id: "substation_yard",
  });
  const candidates = [network, substation];
  assert.deepEqual(
    search(candidates, { text: "", semanticType: "substation" }).results.map((r) => r.id),
    ["mn:scene:coverage:v1:facility-2"],
  );
  assert.deepEqual(
    search(candidates, { text: "", archetypeId: "transmission_line_segment" }).results.map((r) => r.id),
    ["mn:scene:coverage:v1:facility-1"],
  );
});

test("results are emitted in input order, with no re-ranking", () => {
  const first = candidateFromBinding({ scene_id: "mn:scene:coverage:v1:facility-1" });
  const second = candidateFromBinding({ scene_id: "mn:scene:coverage:v1:facility-2" });
  assert.deepEqual(
    search([second, first], { text: "" }).results.map((r) => r.id),
    ["mn:scene:coverage:v1:facility-2", "mn:scene:coverage:v1:facility-1"],
  );
  assert.deepEqual(
    search([first, second], { text: "" }).results.map((r) => r.id),
    ["mn:scene:coverage:v1:facility-1", "mn:scene:coverage:v1:facility-2"],
  );
});

test("a matching candidate with no provenance is never returned as a result -- it is named and excluded", () => {
  const outcome = search([{ ...candidateFromBinding(), sourceArtifactId: "" }], { text: "transmission" });
  assert.deepEqual(outcome.results, []);
  assert.equal(outcome.excluded.length, 1);
  assert.equal(outcome.excluded[0].id, "mn:scene:coverage:v1:facility-1");
  assert.equal(outcome.excluded[0].reason, "missing_provenance");
});

test("the accepted status vocabulary is exactly src/labels.ts -- a non-frozen token is never emitted", () => {
  // Every frozen token is accepted...
  for (const token of ASSET_STATUS_TOKENS) {
    const outcome = search([{ ...candidateFromBinding(), statusLabel: token }], { text: "" });
    assert.deepEqual(
      outcome.results.map((r) => r.statusLabel),
      [token],
      `frozen token ${token} must be searchable`,
    );
  }
  // ...and nothing else is. `source_backed` is the retired three-token
  // vocabulary this module used to restate; src/labels.ts states there is no
  // such token in the browser vocabulary, so it must be refused like any other
  // invented string.
  for (const token of ["source_backed", "illustrative", "", "SYNTHETIC", null, undefined, 1]) {
    const outcome = search([{ ...candidateFromBinding(), statusLabel: token }], { text: "" });
    assert.deepEqual(outcome.results, [], `non-frozen token ${JSON.stringify(token)} must not be emitted`);
    assert.equal(outcome.excluded[0].reason, "missing_provenance", JSON.stringify(token));
  }
});

test("no result ever carries a status token outside the frozen six", () => {
  const candidates = [...ASSET_STATUS_TOKENS, "source_backed", "illustrative"].map((token) => ({
    ...candidateFromBinding(),
    statusLabel: token,
  }));
  const outcome = search(candidates, { text: "" });
  assert.equal(outcome.results.length, ASSET_STATUS_TOKENS.length);
  for (const result of outcome.results) {
    assert.ok(
      ASSET_STATUS_TOKENS.includes(result.statusLabel),
      `search emitted ${JSON.stringify(result.statusLabel)}, which is not in the frozen vocabulary`,
    );
  }
});

test("a non-matching candidate is neither returned nor excluded -- it simply did not match", () => {
  const outcome = search([{ ...candidateFromBinding(), sourceArtifactId: "" }], { text: "no-such-term" });
  assert.deepEqual(outcome.results, []);
  assert.deepEqual(outcome.excluded, []);
});
