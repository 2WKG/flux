import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const output = mkdtempSync(join(tmpdir(), "flux-texas-nodes-"));
process.on("exit", () => rmSync(output, { recursive: true, force: true }));
execFileSync(process.execPath, ["./node_modules/typescript/bin/tsc", "src/labels.ts", "src/source-truth.ts", "src/navigation/scale-ladder.ts", "src/navigation/semantic-zoom.ts", "src/texas-nodes/types.ts", "src/texas-nodes/adapter.ts", "src/texas-nodes/scene.ts", "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--resolveJsonModule", "--esModuleInterop", "--rootDir", "src", "--outDir", output], { cwd: new URL("../..", import.meta.url), stdio: "inherit" });
const { adaptTexasNodes } = await import(pathToFileURL(join(output, "texas-nodes", "adapter.js")).href);
const { texasNodeLabels, texasNodeStyle } = await import(pathToFileURL(join(output, "texas-nodes", "scene.js")).href);

const required = ["lon", "lat", "base_kv", "role", "draw_mw", "generation_capacity_mw", "county_name", "ba_code", "critical_loads"];
function layer(overrides = {}) {
  return { type: "FeatureCollection", layer: "buses", scenario_id: "uri_2021", hour: 3, provenance: { source_kinds: ["simulated"], topology: "synthetic (ACTIVSg2000)", topologies: ["synthetic (ACTIVSg2000)"] }, features: [{ type: "Feature", id: "101", geometry: { type: "Point", coordinates: [-97.7431, 30.2672] }, properties: { bus_id: "101", name: "Travis 500", source_name: "ACTIVSg2000", coord_source: "tamu_aux", topology: "synthetic (ACTIVSg2000)", base_kv: 500, role: "both", generation_capacity_mw: 320, draw_mw: 175.25, draw_status: "available", county_name: "Travis", ba_code: "ERCO", critical_loads: [{ id: 7, name: "Central", kind: "hospital", bus_id: 101, binding_method: "same_county", binding_distance_km: 3.5 }], field_provenance: Object.fromEntries(required.map((field) => [field, field === "draw_mw" ? "derived" : "synthetic"])) } }], ...overrides };
}

test("maps the real 428 annotated-buses GeoJSON fields verbatim, with no browser MW calculation", () => {
  const result = adaptTexasNodes(layer());
  assert.equal(result.kind, "ready");
  const node = result.nodes[0];
  assert.deepEqual([node.longitude, node.latitude, node.baseKv, node.role, node.hourDraw.mw, node.generationCapacityMw, node.county, node.ba], [-97.7431, 30.2672, 500, "both", 175.25, 320, "Travis", "ERCO"]);
  assert.deepEqual(node.criticalFacilities, [{ id: 7, name: "Central", kind: "hospital", bindingMethod: "same_county", bindingDistanceKm: 3.5 }]);
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

test("the #334 wire record is accepted: the facility key is a numeric `id`", () => {
  // `pipelines/node_annotations.py` emits `id := c.cl_id` and `cl_id` is a
  // DuckDB BIGINT, so the facility key arrives as a JSON number
  // (`docs/specs/05-copilot.md`, "Each entry of `critical_loads` is ...").
  // The earlier guard demanded a string `id` or a numeric `cl_id`, which sent
  // the whole Texas node layer to `request_failed` on the real payload.
  const wire = layer();
  assert.equal(typeof wire.features[0].properties.critical_loads[0].id, "number");
  const result = adaptTexasNodes(wire);
  assert.equal(result.kind, "ready", JSON.stringify(result));
  assert.equal(result.nodes[0].criticalFacilities[0].id, 7);

  // The pre-#334 spelling is drift, and is refused rather than silently mapped.
  const stale = layer();
  stale.features[0].properties.critical_loads = [{ cl_id: 7, name: "Central", kind: "hospital" }];
  assert.equal(adaptTexasNodes(stale).kind, "failed");
});

test("an unrecognised per-field provenance token is refused, not displayed", () => {
  const invented = layer();
  invented.features[0].properties.field_provenance.role = "looks_fine";
  assert.deepEqual(adaptTexasNodes(invented), {
    kind: "failed", status: "request_failed", message: "Texas node 0: per-field provenance is missing.",
  });
});

test("a topology string the repository cannot assert is dropped, never rendered", () => {
  const foreign = layer();
  foreign.features[0].properties.topology = "synthetic (SomeOtherCase)";
  foreign.provenance.topology = "synthetic (SomeOtherCase)";
  const result = adaptTexasNodes(foreign);
  assert.equal(result.kind, "ready");
  assert.equal(result.nodes[0].truth.topology, null);
});

test("the role vocabulary is the generated contract's, not a hand-written list", async () => {
  const { TEXAS_NODE_ROLES } = await import(pathToFileURL(join(output, "texas-nodes", "types.js")).href);
  const contract = JSON.parse(
    await import("node:fs").then((fs) => fs.readFileSync(new URL("../contracts/node-annotations.json", import.meta.url), "utf8")),
  );
  assert.deepEqual([...TEXAS_NODE_ROLES], contract.node_roles);
  const unknownRole = layer();
  unknownRole.features[0].properties.role = "battery";
  assert.equal(adaptTexasNodes(unknownRole).kind, "failed");
});
