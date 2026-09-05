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
const { featureProperties, toLayerPresentation } = await import(pathToFileURL(outfile).href);

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
