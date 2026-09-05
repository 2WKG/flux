import assert from "node:assert/strict";
import { buildSync } from "esbuild";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const testDirectory = mkdtempSync(join(tmpdir(), "flux-layer-contract-"));
const outfile = join(testDirectory, "layerContract.mjs");
buildSync({
  entryPoints: [new URL("./layerContract.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  outfile,
  platform: "node",
});
const { featureProperties, toLayerDisplayState, toLayerPresentation } = await import(pathToFileURL(outfile).href);
const visibilityOutfile = join(testDirectory, "layerVisibility.mjs");
buildSync({
  entryPoints: [new URL("./layerVisibility.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  outfile: visibilityOutfile,
  platform: "node",
});
const { toggleLayerVisibility } = await import(pathToFileURL(visibilityOutfile).href);

test.after(() => rmSync(testDirectory, { force: true, recursive: true }));

const payload = {
  status: "ok",
  data: {
    layer: "buses",
    crs: "EPSG:4326",
    attributes: { kv: { unit: "kV", source: "buses.base_kv" } },
    feature_collection: {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-93.2, 44.9] }, properties: { bus_id: "10", kv: 115, scenario_id: "uri_2021" } }],
    },
  },
  meta: { artifacts: [{ artifact_id: "buses", artifact_version: "v1", source_kind: "fixture" }] },
};

test("keeps server geometry, source class, units, and scenario intact", () => {
  const layer = toLayerPresentation(payload);
  assert.ok(layer);
  assert.equal(layer.crs, "EPSG:4326");
  assert.equal(layer.scenario, "uri_2021");
  assert.deepEqual(layer.sourceClasses, ["fixture"]);
  assert.deepEqual(layer.attributes.kv, { unit: "kV", source: "buses.base_kv" });
  assert.deepEqual(layer.featureCollection.features[0].geometry.coordinates, [-93.2, 44.9]);
  assert.deepEqual(featureProperties(layer.featureCollection.features[0]), [["bus_id", "10"], ["kv", "115"], ["scenario_id", "uri_2021"]]);
});

test("rejects missing metadata instead of inventing a layer interpretation", () => {
  assert.equal(toLayerPresentation({ status: "ok", data: {} }), null);
  assert.equal(toLayerPresentation({ status: "unavailable", data: null }), null);
});

test("renders unavailable and empty layers without retaining or inventing geometry", () => {
  assert.deepEqual(toLayerDisplayState({
    status: "unavailable",
    error: { message: "The buses artifact is unavailable." },
  }), { kind: "unavailable", message: "The buses artifact is unavailable." });

  const emptyPayload = structuredClone(payload);
  emptyPayload.data.feature_collection.features = [];
  assert.deepEqual(toLayerDisplayState(emptyPayload), {
    kind: "empty",
    layer: "buses",
    crs: "EPSG:4326",
    message: "The server returned this layer with no features.",
  });
});

test("toggles only declared layer visibility without altering analytical payloads", () => {
  const layers = [
    { id: "outage-risk", label: "Outage risk", visible: true },
    { id: "storm", label: "Storm", visible: false },
  ];
  assert.deepEqual(toggleLayerVisibility(layers, "storm"), [
    { id: "outage-risk", label: "Outage risk", visible: true },
    { id: "storm", label: "Storm", visible: true },
  ]);
  assert.strictEqual(toggleLayerVisibility(layers, "not-a-server-layer"), layers);
  assert.deepEqual(payload.data.feature_collection.features[0].properties, {
    bus_id: "10",
    kv: 115,
    scenario_id: "uri_2021",
  });
});
