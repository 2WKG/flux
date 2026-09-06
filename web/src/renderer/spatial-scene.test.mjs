import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const out = mkdtempSync(join(tmpdir(), "flux-spatial-scene-"));
process.on("exit", () => rmSync(out, { recursive: true, force: true }));
execFileSync(process.execPath, ["./node_modules/typescript/bin/tsc", "src/renderer/spatial-scene.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", out], { cwd: new URL("../..", import.meta.url), stdio: "inherit" });
const { geometryAccounting, pageFrom, renderableFeatures } = await import(pathToFileURL(join(out, "spatial-scene.js")).href);

function item(overrides = {}) {
  return { asset_id: "tx:line:1", asset_class: "line", asset_kind: "transmission", availability: "available", display_geometry: { type: "LineString", coordinates: [[-99, 31], [-98, 31.1]] }, display_crs: "EPSG:4326", native_geometry: { type: "LineString", coordinates: [[-99, 31], [-98, 31.1]] }, native_crs: "EPSG:4326", geometry_status: "source", geometry_accuracy_basis: "Published source geometry", geometry_precision_m: null, transform_provenance: { method: "identity", source_crs: "EPSG:4326", display_crs: "EPSG:4326" }, provenance: { source_id: "hifld", source_record_id: "line-1", authority: "HIFLD", source_ref: "https://example.test", source_version: "2024", retrieved_at: "2026-09-06" }, ...overrides };
}
function page(overrides = {}) { return { api_version: "v1", state: "tx", artifact_version: "1.1.0", artifact_id: "tx:physical-inventory:1.1.0", release_sha256: "abc", layer: "line", inventory_mode: "physical_observed", electrical_model_mode: "none", items: [item()], page: { limit: 100, cursor: null, next_cursor: null, total: 1 }, coverage: [{ status: "partial" }], ...overrides }; }

test("only server WGS84 display geometry is drawable; native geometry remains evidence", () => {
  const esri = item({ asset_id: "mn:line:1", display_geometry: { type: "LineString", coordinates: [[-93, 46], [-92.9, 46.1]] }, native_geometry: { type: "LineString", coordinates: [[500000, 500000], [500100, 500100]] }, native_crs: "ESRI:103705", geometry_status: "derived", transform_provenance: { method: "pyproj always_xy", source_crs: "ESRI:103705", display_crs: "EPSG:4326" } });
  const unavailable = item({ asset_id: "tx:generation:1", availability: "unavailable", display_geometry: null, display_crs: null, native_geometry: null, native_crs: null, geometry_status: "unavailable", geometry_accuracy_basis: null, geometry_precision_m: null, transform_provenance: null });
  assert.deepEqual(renderableFeatures([esri, unavailable]).map((feature) => feature.id), ["mn:line:1"]);
  assert.deepEqual(geometryAccounting([esri, unavailable]), { totalLoaded: 2, renderable: 1, unavailableGeometry: 1 });
  assert.deepEqual(renderableFeatures([esri])[0].geometry, esri.display_geometry);
});

test("the full 89 page preserves IDs, release, coverage, and cursor without client defaults", () => {
  const result = pageFrom(page({ page: { limit: 100, cursor: "opaque-current", next_cursor: "opaque-next", total: 11949 } }));
  assert.equal(result.artifact_id, "tx:physical-inventory:1.1.0");
  assert.equal(result.page.next_cursor, "opaque-next");
  assert.equal(result.coverage[0].status, "partial");
});

test("unavailable geometry and a non-WGS84 display field are rejected, never relabelled", () => {
  assert.equal(pageFrom(page({ items: [item({ display_crs: "ESRI:103705" })] })), null);
  assert.equal(pageFrom(page({ items: [item({ availability: "unavailable", display_geometry: { type: "Point", coordinates: [-99, 31] }, display_crs: "EPSG:4326", geometry_status: "unavailable" })] })), null);
});

test("an unavailable API envelope stays unavailable with its server message", () => {
  const result = pageFrom({ status: "unavailable", error: { code: "unavailable", message: "release_not_found" }, meta: { request_id: "request-1" } });
  assert.deepEqual(result, { status: "unavailable", error: { code: "unavailable", message: "release_not_found", request_id: "request-1" } });
});
