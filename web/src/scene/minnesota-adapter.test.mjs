import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
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
  // `--rootDir src` pins the emitted layout, the way src/navigation/search.test.mjs
  // already does: the adapter now names the shared vocabulary (src/labels.ts), so
  // tsc would otherwise re-root the output on whatever the common directory is.
  ["./node_modules/typescript/bin/tsc", "src/scene/minnesota-adapter.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--rootDir", "src", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  MINNESOTA_BBOX,
  REQUIRED_CRS,
  SYNTHETIC_TOPOLOGY_LABEL,
  adaptAggregateCoverage,
  adaptBoundPlacement,
  adaptLayerToScene,
  allowsTopologyRendering,
} = await import(pathToFileURL(join(outputDirectory, "scene", "minnesota-adapter.js")).href);

/**
 * Shaped exactly like copilot/routes/layers.py builds a bare GeoJSON layer,
 * with the provenance copilot/test_layers.py:170-179 pins for a plain fixture
 * bus layer -- the real, reachable payload, not an invented one.
 */
function collection(overrides = {}) {
  return {
    type: "FeatureCollection",
    crs: { type: "name", properties: { name: REQUIRED_CRS } },
    layer: "buses",
    provenance: {
      source_kinds: ["fixture"],
      topology: null,
      topologies: [],
      source_names: ["fixture"],
      coord_sources: ["fixture:hand-placed"],
      fixture_batch_ids: ["flux-demo@2026"],
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

/**
 * Shaped exactly like `bind_asset` returns a `render_mode: "placed"` binding
 * (pipelines/minnesota_asset_binding.py, PR #174): acceptance already decided
 * from mn_artifact_manifests.availability and mn_score_results.regulatory_label.
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

function aggregateManifest(overrides = {}) {
  return {
    ...JSON.parse(readFileSync(new URL("../../../pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json", import.meta.url), "utf8")),
    ...overrides,
  };
}

test("the real plain-fixture /layers payload is refused, never drawn as topology", () => {
  // copilot/test_layers.py:170-179 pins exactly this provenance for the layer
  // the server actually builds. Gate 0 §2 keeps topology scenes disabled.
  const result = adaptLayerToScene(collection());

  assert.equal(result.kind, "rejected");
  assert.equal(result.reason, "aggregate_only_no_geometry");
  assert.equal(allowsTopologyRendering(result), false);
  assert.match(result.detail, /mn_artifact_manifests\.availability/);

  // The two-kind form the same route emits (copilot/test_layers.py:190) too.
  const mixed = adaptLayerToScene(
    collection({ provenance: { ...collection().provenance, source_kinds: ["fixture", "simulated"] } }),
  );
  assert.equal(mixed.reason, "aggregate_only_no_geometry");
  assert.equal(allowsTopologyRendering(mixed), false);
});

test("no /layers provenance can assert acceptance, including invented tokens", () => {
  // "observed" and "source_backed" appear nowhere in copilot/, pipelines/, or
  // data/: _derive_labels emits only "fixture", "simulated", or null.
  for (const kinds of [["observed"], ["source_backed"], ["observed", "fixture"]]) {
    const result = adaptLayerToScene(
      collection({ provenance: { ...collection().provenance, source_kinds: kinds } }),
    );
    assert.equal(result.kind, "rejected", JSON.stringify(kinds));
    assert.equal(result.reason, "unlabeled_provenance", JSON.stringify(kinds));
  }
  // The server can serialise source_kinds: [null] (layers.py sorts a set that
  // may hold None). That is unlabelled, not accepted.
  assert.equal(
    adaptLayerToScene(collection({ provenance: { ...collection().provenance, source_kinds: [null] } })).reason,
    "unlabeled_provenance",
  );
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

test("the actual bind_asset placement shape is transformed verbatim and never permits topology", () => {
  const result = adaptBoundPlacement(binding());

  assert.equal(result.kind, "bound_placement");
  assert.deepEqual(result.placement, {
    id: "mn:scene:coverage:v1:facility-1",
    sourceArtifactId: "mn:scene:coverage:v1",
    archetypeId: "transmission_line_segment",
    semanticType: "network",
    position: [-93.26, 44.98],
    statusLabel: "source_supported",
  });
  // Gate 0 §2: even accepted evidence never authorises lines, towers, or flows.
  assert.equal(allowsTopologyRendering(result), false);

  const screened = adaptBoundPlacement(binding({ material: { slot: "MAT_STATUS", status_label: "source_screened" } }));
  assert.equal(screened.placement.statusLabel, "source_screened");
});

test("a binding the server did not place, or labelled outside the accepted set, is refused", () => {
  const preview = adaptBoundPlacement({
    render_mode: "catalog_preview",
    archetype_id: "transmission_line_segment",
    material: { slot: "MAT_STATUS", status_label: "unavailable" },
    disclosure: "Illustrative catalogue preview",
  });
  assert.equal(preview.reason, "catalog_preview_no_geometry");
  assert.equal(allowsTopologyRendering(preview), false);

  // render_mode is load-bearing on its own: a payload that claims an accepted
  // label but was not placed by the server is still refused, and its detail
  // names render_mode rather than the label.
  const notPlaced = adaptBoundPlacement(binding({ render_mode: "not_placed" }));
  assert.equal(notPlaced.reason, "not_server_bound");
  assert.match(notPlaced.detail, /render_mode/);

  // hypothetical/synthetic/unavailable are MAT_STATUS labels but never position
  // geometry (ACCEPTED_REGULATORY_LABELS in minnesota_asset_binding.py).
  for (const label of ["hypothetical", "synthetic", "unavailable", "request_failed"]) {
    const result = adaptBoundPlacement(binding({ material: { slot: "MAT_STATUS", status_label: label } }));
    assert.equal(result.reason, "not_server_bound", label);
  }

  // A label the browser would have to invent is refused, not defaulted.
  for (const material of [undefined, {}, { slot: "OTHER", status_label: "source_supported" }, { slot: "MAT_STATUS" }, { slot: "MAT_STATUS", status_label: "source_backed" }]) {
    const result = adaptBoundPlacement(binding({ material }));
    assert.equal(result.reason, "unlabeled_provenance", JSON.stringify(material));
  }
});

test("a binding with bad CRS, geometry, or scene identity is refused by name", () => {
  const cases = [
    [binding({ crs: undefined }), "missing_crs"],
    [binding({ crs: "EPSG:26915" }), "unsupported_crs"],
    [binding({ coordinates: { longitude: -93.26, latitude: 44.98, crs: "EPSG:26915" } }), "unsupported_crs"],
    [binding({ coordinates: undefined }), "missing_crs"],
    [binding({ coordinates: { longitude: -93.26, latitude: 44.98 } }), "missing_crs"],
    [binding({ coordinates: { longitude: "-93.26", latitude: 44.98, crs: REQUIRED_CRS } }), "malformed_collection"],
    [binding({ coordinates: { longitude: Number.NaN, latitude: 44.98, crs: REQUIRED_CRS } }), "coordinates_out_of_range"],
    // #89's probe, and a lon/lat swap that stays inside +-90/+-180.
    [binding({ coordinates: { longitude: -93.26, latitude: -97, crs: REQUIRED_CRS } }), "coordinates_out_of_range"],
    [binding({ coordinates: { longitude: 44.98, latitude: -93.26, crs: REQUIRED_CRS } }), "coordinates_out_of_range"],
    // Valid WGS 84, but Texas -- accepted by a range check, refused by the bbox.
    [binding({ coordinates: { longitude: -97.5, latitude: 30.1, crs: REQUIRED_CRS } }), "coordinates_out_of_range"],
    [binding({ coordinates: { longitude: 0, latitude: 0, crs: REQUIRED_CRS } }), "coordinates_out_of_range"],
    [binding({ scene_id: "" }), "malformed_collection"],
    [binding({ scene_id: "some:other:artifact#1" }), "malformed_collection"],
    [binding({ scene_id: "mn:scene:coverage:v1not-a-child" }), "malformed_collection"],
    [binding({ source_artifact_id: undefined }), "malformed_collection"],
    [binding({ archetype_id: undefined }), "malformed_collection"],
    [binding({ semantic_type: undefined }), "malformed_collection"],
  ];
  for (const [placement, reason] of cases) {
    const result = adaptBoundPlacement(placement);
    assert.equal(result.kind, "rejected", JSON.stringify(placement));
    assert.equal(result.reason, reason, JSON.stringify(placement));
  }

  // Sanity: the bbox constant is the documented Minnesota extent, so the
  // accepted point above is inside it and the refused ones are outside.
  const [west, south, east, north] = MINNESOTA_BBOX;
  assert.ok(west < -93.26 && -93.26 < east && south < 44.98 && 44.98 < north);
});

test("a malformed binding payload is a named refusal, never a TypeError", () => {
  for (const payload of [null, undefined, [], "placed", 7, {}, { render_mode: null }]) {
    const result = adaptBoundPlacement(payload);
    assert.equal(result.kind, "rejected", JSON.stringify(payload) ?? "undefined");
    assert.equal(
      result.reason,
      payload && typeof payload === "object" && !Array.isArray(payload) ? "not_server_bound" : "malformed_collection",
      JSON.stringify(payload) ?? "undefined",
    );
  }
});

test("the real aggregate manifest is disclosed without inventing geometry or zones", () => {
  const result = adaptAggregateCoverage(aggregateManifest());

  assert.equal(result.kind, "aggregate_coverage");
  assert.equal(result.renderableGeometry, false);
  assert.equal(result.manifestFormat, "flux-minnesota-aggregate-v1");
  assert.equal(result.allocationStatus, "unavailable");
  assert.match(result.allocationLimit, /not allocated to Minnesota geography/);
  assert.deepEqual(result.sourceIds, [
    "tiger_counties_2024",
    "mngeo_service_areas_2026",
    "eia860_2024",
    "eia930_balance_2024_h1",
  ]);
  // No geometry or named zones are invented from the aggregate evidence.
  assert.deepEqual(coordinatePairsIn(result), []);
  assert.ok(!allowsTopologyRendering(result));
});

test("aggregate coverage without a server status label is refused, not labelled", () => {
  const base = aggregateManifest({ allocation_status: undefined });
  assert.equal(adaptAggregateCoverage(base).reason, "unlabeled_provenance");
  assert.equal(
    adaptAggregateCoverage(aggregateManifest({ allocation_status: "source_backed" })).reason,
    "unlabeled_provenance",
  );
  assert.equal(
    adaptAggregateCoverage(aggregateManifest({ allocation_status: "allocated" })).reason,
    "unlabeled_provenance",
  );
});

test("malformed aggregate coverage is a named refusal, never a TypeError", () => {
  for (const payload of [
    null,
    undefined,
    [],
    "flux-minnesota-aggregate-v1",
    {},
    aggregateManifest({ format: "other" }),
    aggregateManifest({ model_mode: "topology" }),
    aggregateManifest({ allocation_limit: "" }),
    aggregateManifest({ sources: null }),
    aggregateManifest({ sources: [] }),
    aggregateManifest({ sources: [{}] }),
  ]) {
    const result = adaptAggregateCoverage(payload);
    assert.equal(result.kind, "rejected", JSON.stringify(payload) ?? "undefined");
    assert.equal(result.reason, "malformed_collection", JSON.stringify(payload) ?? "undefined");
  }

});

test("no adaptation this module can return permits topology rendering", () => {
  // Gate 0 §2 keeps topology scenes disabled, and there is no topology variant
  // to construct -- so the check is over everything reachable: both accept
  // kinds and a refusal from each of the three entry points.
  const reachable = [
    adaptBoundPlacement(binding()),
    adaptBoundPlacement(binding({ render_mode: "catalog_preview" })),
    adaptAggregateCoverage(aggregateManifest()),
    adaptAggregateCoverage(null),
    adaptLayerToScene(collection()),
    adaptLayerToScene(collection({ crs: undefined })),
  ];
  // Every kind the module can currently produce is represented above, so a new
  // kind cannot quietly skip this assertion.
  assert.deepEqual(
    [...new Set(reachable.map((adaptation) => adaptation.kind))].sort(),
    ["aggregate_coverage", "bound_placement", "rejected"],
  );
  for (const adaptation of reachable) {
    assert.equal(
      allowsTopologyRendering(adaptation),
      false,
      `${adaptation.kind}/${adaptation.reason ?? ""}`,
    );
  }
});

/** Every [number, number] pair reachable in the value, under any key name. */
function coordinatePairsIn(value) {
  const found = [];
  const walk = (node) => {
    if (Array.isArray(node)) {
      if (node.length === 2 && node.every((item) => typeof item === "number")) found.push(node);
      node.forEach(walk);
      return;
    }
    if (node !== null && typeof node === "object") Object.values(node).forEach(walk);
  };
  walk(value);
  return found;
}
