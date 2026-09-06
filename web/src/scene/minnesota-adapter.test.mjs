import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-mn-adapter-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Run tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/scene/minnesota-adapter.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  REQUIRED_CRS,
  SYNTHETIC_TOPOLOGY_LABEL,
  adaptAggregateCoverage,
  adaptLayerToScene,
  allowsTopologyRendering,
} = await import(pathToFileURL(join(outputDirectory, "minnesota-adapter.js")).href);

/** Shaped exactly like copilot/routes/layers.py builds a bare GeoJSON layer. */
function collection(overrides = {}) {
  return {
    type: "FeatureCollection",
    crs: { type: "name", properties: { name: REQUIRED_CRS } },
    layer: "buses",
    provenance: {
      source_kinds: ["observed"],
      topology: null,
      topologies: [],
      source_names: ["mn_accepted"],
      coord_sources: ["source"],
      fixture_batch_ids: ["batch-1"],
    },
    features: [feature()],
    ...overrides,
  };
}

function feature(overrides = {}) {
  return {
    type: "Feature",
    id: "mn-1",
    geometry: { type: "Point", coordinates: [-93.26, 44.98] },
    properties: { name: "Accepted Node", bus_id: "mn-1" },
    ...overrides,
  };
}

test("an accepted labelled layer becomes a scene preserving ids, coordinates, and labels", () => {
  const result = adaptLayerToScene(collection());

  assert.equal(result.kind, "topology_scene");
  assert.deepEqual(result.nodes, [
    { id: "mn-1", name: "Accepted Node", position: [-93.26, 44.98], truthLabel: "source_backed" },
  ]);
  assert.equal(result.provenance.crs, REQUIRED_CRS);
  assert.equal(result.provenance.layer, "buses");
  assert.deepEqual(result.provenance.sourceNames, ["mn_accepted"]);
  assert.deepEqual(result.provenance.fixtureBatchIds, ["batch-1"]);
  assert.ok(allowsTopologyRendering(result));
});

test("synthetic ACTIVSg2000 topology is refused, not relabelled as Minnesota", () => {
  // This is what the server actually serves today for `buses`.
  for (const provenanceOverride of [
    { topology: SYNTHETIC_TOPOLOGY_LABEL, topologies: [SYNTHETIC_TOPOLOGY_LABEL] },
    { topology: null, topologies: [SYNTHETIC_TOPOLOGY_LABEL] },
  ]) {
    const result = adaptLayerToScene(
      collection({
        provenance: { ...collection().provenance, source_kinds: ["simulated"], ...provenanceOverride },
      }),
    );

    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "synthetic_topology_not_minnesota");
    assert.ok(!allowsTopologyRendering(result));
  }
});

test("an unlabelled collection is refused rather than given a browser-invented label", () => {
  const missingBlock = adaptLayerToScene(collection({ provenance: undefined }));
  assert.equal(missingBlock.reason, "unlabeled_provenance");

  const emptyKinds = adaptLayerToScene(
    collection({ provenance: { ...collection().provenance, source_kinds: [] } }),
  );
  assert.equal(emptyKinds.reason, "unlabeled_provenance");

  const unknownKind = adaptLayerToScene(
    collection({ provenance: { ...collection().provenance, source_kinds: ["guessed"] } }),
  );
  assert.equal(unknownKind.reason, "unlabeled_provenance");
});

test("CRS must be declared and supported; coordinates are never reprojected", () => {
  const missing = adaptLayerToScene(collection({ crs: undefined }));
  assert.equal(missing.reason, "missing_crs");

  const other = adaptLayerToScene(
    collection({ crs: { type: "name", properties: { name: "EPSG:26915" } } }),
  );
  assert.equal(other.reason, "unsupported_crs");
  assert.match(other.detail, /EPSG:26915/);
});

test("out-of-range and malformed geometry are named, not clamped", () => {
  const outOfRange = adaptLayerToScene(
    collection({ features: [feature({ geometry: { type: "Point", coordinates: [-181, 44.98] } })] }),
  );
  assert.equal(outOfRange.reason, "coordinates_out_of_range");

  for (const broken of [
    { geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
    { geometry: { type: "Point", coordinates: ["-93.26", 44.98] } },
    { geometry: { type: "Point", coordinates: [-93.26] } },
    { id: 7 },
  ]) {
    const result = adaptLayerToScene(collection({ features: [feature(broken)] }));
    assert.equal(result.kind, "rejected", JSON.stringify(broken));
    assert.equal(result.reason, "malformed_collection", JSON.stringify(broken));
  }
});

test("an empty or non-collection payload is never an empty success", () => {
  assert.equal(adaptLayerToScene(collection({ features: [] })).reason, "no_features");
  for (const payload of [null, undefined, [], "FeatureCollection", { type: "Feature" }]) {
    const result = adaptLayerToScene(payload);
    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "malformed_collection");
  }
});

test("aggregate coverage yields named zones and never permits topology rendering", () => {
  const result = adaptAggregateCoverage({
    layer: "mn_service_areas",
    zones: [{ id: "27053", name: "Hennepin" }, { id: "27123" }],
    sourceNames: ["mn:aggregate:manifest:v1"],
  });

  assert.equal(result.kind, "aggregate_zones");
  assert.equal(result.renderableGeometry, false);
  assert.deepEqual(result.zones, [
    { id: "27053", name: "Hennepin", truthLabel: "source_backed" },
    { id: "27123", name: null, truthLabel: "source_backed" },
  ]);
  // No geometry is invented for a named zone: no coordinates anywhere.
  assert.ok(!JSON.stringify(result.zones).includes("position"));
  assert.equal(result.provenance.topology, null);
  assert.ok(!allowsTopologyRendering(result));

  assert.equal(adaptAggregateCoverage({ layer: "x", zones: [] }).reason, "no_features");
});
