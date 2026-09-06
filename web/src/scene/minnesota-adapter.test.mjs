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
  MINNESOTA_BBOX,
  REQUIRED_CRS,
  SYNTHETIC_TOPOLOGY_LABEL,
  adaptAggregateCoverage,
  adaptBoundPlacements,
  adaptLayerToScene,
  allowsTopologyRendering,
} = await import(pathToFileURL(join(outputDirectory, "minnesota-adapter.js")).href);

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
    scene_id: "mn:scene:coverage:v1#substation-1",
    source_artifact_id: "mn:scene:coverage:v1",
    semantic_type: "substation",
    archetype_id: "distribution_substation",
    crs: REQUIRED_CRS,
    coordinates: { longitude: -93.26, latitude: 44.98, crs: REQUIRED_CRS },
    footprint_m: [40, 40],
    connectors: ["HV_BUS"],
    lod_triangles: { lod0: 30000 },
    material: { slot: "MAT_STATUS", status_label: "source_supported" },
    ...overrides,
  };
}

function boundPayload(overrides = {}) {
  return { layer: "mn_placements", placements: [binding()], source_names: ["mn:scene:coverage:v1"], ...overrides };
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

test("a server binding is transformed verbatim and still never permits topology", () => {
  const result = adaptBoundPlacements(boundPayload());

  assert.equal(result.kind, "bound_placements");
  assert.deepEqual(result.placements, [
    {
      id: "mn:scene:coverage:v1#substation-1",
      sourceArtifactId: "mn:scene:coverage:v1",
      archetypeId: "distribution_substation",
      semanticType: "substation",
      position: [-93.26, 44.98],
      statusLabel: "source_supported",
    },
  ]);
  assert.equal(result.provenance.crs, REQUIRED_CRS);
  assert.deepEqual(result.provenance.sourceNames, ["mn:scene:coverage:v1"]);
  // Gate 0 §2: even accepted evidence never authorises lines, towers, or flows.
  assert.equal(allowsTopologyRendering(result), false);

  const screened = adaptBoundPlacements(
    boundPayload({
      placements: [binding({ material: { slot: "MAT_STATUS", status_label: "source_screened" } })],
    }),
  );
  assert.equal(screened.placements[0].statusLabel, "source_screened");
});

test("a binding the server did not place, or labelled outside the accepted set, is refused", () => {
  const preview = adaptBoundPlacements(
    boundPayload({
      placements: [
        {
          render_mode: "catalog_preview",
          archetype_id: "distribution_substation",
          material: { slot: "MAT_STATUS", status_label: "unavailable" },
          disclosure: "Illustrative catalogue preview",
        },
      ],
    }),
  );
  assert.equal(preview.reason, "not_server_bound");
  assert.equal(allowsTopologyRendering(preview), false);

  // hypothetical/synthetic/unavailable are MAT_STATUS labels but never position
  // geometry (ACCEPTED_REGULATORY_LABELS in minnesota_asset_binding.py).
  for (const label of ["hypothetical", "synthetic", "unavailable", "request_failed"]) {
    const result = adaptBoundPlacements(
      boundPayload({ placements: [binding({ material: { slot: "MAT_STATUS", status_label: label } })] }),
    );
    assert.equal(result.reason, "not_server_bound", label);
  }

  // A label the browser would have to invent is refused, not defaulted.
  for (const material of [undefined, {}, { slot: "MAT_STATUS" }, { slot: "MAT_STATUS", status_label: "source_backed" }]) {
    const result = adaptBoundPlacements(boundPayload({ placements: [binding({ material })] }));
    assert.equal(result.reason, "unlabeled_provenance", JSON.stringify(material));
  }
});

test("a binding with bad CRS, geometry, or scene identity is refused by name", () => {
  const cases = [
    [binding({ crs: undefined }), "missing_crs"],
    [binding({ crs: "EPSG:26915" }), "unsupported_crs"],
    [binding({ coordinates: { longitude: -93.26, latitude: 44.98, crs: "EPSG:26915" } }), "unsupported_crs"],
    [binding({ coordinates: undefined }), "malformed_collection"],
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
    [binding({ source_artifact_id: undefined }), "malformed_collection"],
    [binding({ archetype_id: undefined }), "malformed_collection"],
  ];
  for (const [placement, reason] of cases) {
    const result = adaptBoundPlacements(boundPayload({ placements: [placement] }));
    assert.equal(result.kind, "rejected", JSON.stringify(placement));
    assert.equal(result.reason, reason, JSON.stringify(placement));
  }

  // Sanity: the bbox constant is the documented Minnesota extent, so the
  // accepted point above is inside it and the refused ones are outside.
  const [west, south, east, north] = MINNESOTA_BBOX;
  assert.ok(west < -93.26 && -93.26 < east && south < 44.98 && 44.98 < north);
});

test("a malformed binding payload is a named refusal, never a TypeError", () => {
  for (const payload of [null, undefined, [], "placed", 7, {}, { placements: null }, { placements: "x" }]) {
    const result = adaptBoundPlacements(payload);
    assert.equal(result.kind, "rejected", JSON.stringify(payload) ?? "undefined");
    assert.equal(result.reason, "malformed_collection", JSON.stringify(payload) ?? "undefined");
  }
  assert.equal(adaptBoundPlacements({ placements: [] }).reason, "no_features");
  for (const placement of [null, "placed", 7, []]) {
    assert.equal(
      adaptBoundPlacements(boundPayload({ placements: [placement] })).reason,
      "malformed_collection",
      JSON.stringify(placement),
    );
  }
});

test("aggregate coverage carries the manifest's own allocation_status through", () => {
  // pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json says
  // allocation_status: "unavailable", so the zones say unavailable.
  const result = adaptAggregateCoverage({
    layer: "mn_service_areas",
    allocation_status: "unavailable",
    zones: [{ id: "27053", name: "Hennepin" }, { id: "27123" }],
    source_names: ["mn:aggregate:manifest:v1"],
  });

  assert.equal(result.kind, "aggregate_zones");
  assert.equal(result.renderableGeometry, false);
  assert.deepEqual(result.zones, [
    { id: "27053", name: "Hennepin", statusLabel: "unavailable" },
    { id: "27123", name: null, statusLabel: "unavailable" },
  ]);
  // No geometry is invented for a named zone: no coordinate pair anywhere in
  // the adaptation, under any key name.
  assert.deepEqual(coordinatePairsIn(result), []);
  assert.equal(result.provenance.topology, null);
  assert.ok(!allowsTopologyRendering(result));

  const perZone = adaptAggregateCoverage({
    layer: "mn_service_areas",
    allocation_status: "unavailable",
    zones: [{ id: "27053", allocation_status: "source_supported" }],
  });
  assert.equal(perZone.zones[0].statusLabel, "source_supported");
});

test("aggregate coverage without a server status label is refused, not labelled", () => {
  const base = { layer: "mn_service_areas", zones: [{ id: "27053" }] };
  assert.equal(adaptAggregateCoverage(base).reason, "unlabeled_provenance");
  assert.equal(
    adaptAggregateCoverage({ ...base, allocation_status: "source_backed" }).reason,
    "unlabeled_provenance",
  );
  assert.equal(
    adaptAggregateCoverage({ ...base, allocation_status: "allocated" }).reason,
    "unlabeled_provenance",
  );
});

test("malformed aggregate coverage is a named refusal, never a TypeError", () => {
  for (const payload of [
    null,
    undefined,
    [],
    "mn_service_areas",
    {},
    { layer: "x" },
    { layer: "x", zones: null },
    { layer: "x", zones: "27053" },
    { zones: [{ id: "27053" }], allocation_status: "unavailable" },
    { layer: "", zones: [{ id: "27053" }], allocation_status: "unavailable" },
  ]) {
    const result = adaptAggregateCoverage(payload);
    assert.equal(result.kind, "rejected", JSON.stringify(payload) ?? "undefined");
    assert.equal(result.reason, "malformed_collection", JSON.stringify(payload) ?? "undefined");
  }

  for (const zone of [null, "27053", 27053, {}, { id: "" }, { id: 27053 }, { name: "Hennepin" }]) {
    const result = adaptAggregateCoverage({
      layer: "mn_service_areas",
      allocation_status: "unavailable",
      zones: [zone],
    });
    assert.equal(result.kind, "rejected", JSON.stringify(zone) ?? "undefined");
    assert.equal(result.reason, "malformed_collection", JSON.stringify(zone) ?? "undefined");
  }

  assert.equal(adaptAggregateCoverage({ layer: "x", zones: [], allocation_status: "unavailable" }).reason, "no_features");
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
