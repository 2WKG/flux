import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const output = mkdtempSync(join(tmpdir(), "flux-texas-nodes-"));
process.on("exit", () => rmSync(output, { recursive: true, force: true }));
execFileSync(process.execPath, ["./node_modules/typescript/bin/tsc", "src/labels.ts", "src/source-truth.ts", "src/navigation/scale-ladder.ts", "src/navigation/semantic-zoom.ts", "src/texas-nodes/types.ts", "src/texas-nodes/adapter.ts", "src/texas-nodes/scene.ts", "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--rootDir", "src", "--outDir", output], { cwd: new URL("../..", import.meta.url), stdio: "inherit" });
const { adaptTexasNodes } = await import(pathToFileURL(join(output, "texas-nodes", "adapter.js")).href);
const { texasNodeLabels, texasNodeStyle } = await import(pathToFileURL(join(output, "texas-nodes", "scene.js")).href);

const required = ["lon", "lat", "base_kv", "role", "draw_mw", "generation_capacity_mw", "county_name", "ba_code", "critical_loads"];
function layer(overrides = {}) {
  return { type: "FeatureCollection", layer: "buses", scenario_id: "uri_2021", hour: 3, provenance: { source_kinds: ["simulated"], topology: "synthetic (ACTIVSg2000)", topologies: ["synthetic (ACTIVSg2000)"] }, features: [{ type: "Feature", id: "101", geometry: { type: "Point", coordinates: [-97.7431, 30.2672] }, properties: { bus_id: "101", name: "Travis 500", source_name: "ACTIVSg2000", coord_source: "tamu_aux", base_kv: 500, role: "both", generation_capacity_mw: 320, draw_mw: 175.25, draw_status: "available", county_name: "Travis", ba_code: "ERCO", critical_loads: [{ cl_id: 7, name: "Central", kind: "hospital" }], field_provenance: Object.fromEntries(required.map((field) => [field, field === "draw_mw" ? "derived" : "synthetic"])) } }], ...overrides };
}

test("maps the real 428 annotated-buses GeoJSON fields verbatim, with no browser MW calculation", () => {
  const result = adaptTexasNodes(layer());
  assert.equal(result.kind, "ready");
  const node = result.nodes[0];
  assert.deepEqual([node.longitude, node.latitude, node.baseKv, node.role, node.hourDraw.mw, node.generationCapacityMw, node.county, node.ba], [-97.7431, 30.2672, 500, "both", 175.25, 320, "Travis", "ERCO"]);
  assert.deepEqual(node.criticalFacilities, [{ id: "7", name: "Central", kind: "hospital" }]);
  assert.equal(node.fieldProvenance.draw_mw, "derived");
  assert.equal(node.truth.status, "synthetic");
});

test("shows server-declared unavailable BA-hour draw and refuses absent field provenance", () => {
  const unavailable = layer();
  unavailable.features[0].properties.draw_mw = null;
  unavailable.features[0].properties.draw_status = "unavailable";
  const mapped = adaptTexasNodes(unavailable);
  assert.equal(mapped.kind, "ready");
  assert.ok(!("mw" in mapped.nodes[0].hourDraw));
  assert.match(texasNodeLabels(mapped.nodes[0], "facility").find((label) => label.key === "draw").text, /Draw unavailable/);
  const missing = layer(); delete missing.features[0].properties.field_provenance.ba_code;
  assert.deepEqual(adaptTexasNodes(missing), { kind: "failed", status: "request_failed", message: "Texas node 0: per-field provenance is missing." });
});

test("uses role glyph, voltage stroke semantics, and semantic zoom without changing a server value", () => {
  const result = adaptTexasNodes(layer()); assert.equal(result.kind, "ready");
  assert.deepEqual(texasNodeStyle(result.nodes[0]), { glyph: "diamond", voltageClass: "extra_high", strokeWidth: 4 });
  assert.deepEqual(texasNodeLabels(result.nodes[0], "statewide").map((label) => label.key), ["name", "role"]);
  assert.equal(result.nodes[0].hourDraw.mw, 175.25);
});
