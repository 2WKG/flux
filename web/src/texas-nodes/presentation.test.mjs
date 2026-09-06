/**
 * `presentation.tsx` had no test importing it at all: stamping a fabricated
 * `source_supported` on every node inspector left the suite green, and
 * `TexasNodeMarker` rendered no truth label, so the `synthetic (ACTIVSg2000)`
 * token could vanish from the whole surface without a single red assertion.
 * Everything here is asserted on rendered markup.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
const output = mkdtempSync(join(webRoot, ".tmp-texas-presentation-"));
process.on("exit", () => rmSync(output, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/texas-nodes/presentation.tsx", "src/texas-nodes/adapter.ts",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node",
  "--jsx", "react-jsx", "--resolveJsonModule", "--esModuleInterop", "--rootDir", "src", "--outDir", output,
], { cwd: webRoot, stdio: "inherit" });
writeFileSync(join(output, "package.json"), '{"type":"commonjs"}');
const { TexasNodeInspector, TexasNodeMarker, texasNodeInspectorAsset } =
  await import(pathToFileURL(join(output, "texas-nodes", "presentation.js")).href);
const { adaptTexasNodes } = await import(pathToFileURL(join(output, "texas-nodes", "adapter.js")).href);
const { STATUS_COPY } = await import(pathToFileURL(join(output, "source-truth.js")).href);
const { SYNTHETIC_TOPOLOGY_LABEL } = await import(pathToFileURL(join(output, "scene", "minnesota-adapter.js")).href);

const required = ["lon", "lat", "base_kv", "role", "draw_mw", "generation_capacity_mw", "county_name", "ba_code", "critical_loads"];

/** A record shaped exactly like the one `GET /layers/buses` emits after #334. */
function layer(overrides = {}) {
  return {
    type: "FeatureCollection", layer: "buses", scenario_id: "uri_2021", hour: 3,
    provenance: { source_kinds: ["simulated"], topology: SYNTHETIC_TOPOLOGY_LABEL, topologies: [SYNTHETIC_TOPOLOGY_LABEL] },
    features: [{
      type: "Feature", id: "101",
      geometry: { type: "Point", coordinates: [-97.7431, 30.2672] },
      properties: {
        bus_id: "101", name: "Travis 500", source_name: "ACTIVSg2000", coord_source: "tamu_aux",
        topology: SYNTHETIC_TOPOLOGY_LABEL,
        base_kv: 500, role: "both", generation_capacity_mw: 320, draw_mw: 175.25, draw_status: "available",
        county_name: "Travis", ba_code: "ERCO",
        critical_loads: [{ id: 7, name: "Central", kind: "hospital", bus_id: 101, binding_method: "same_county", binding_distance_km: 3.5 }],
        field_provenance: Object.fromEntries(required.map((field) => [field, field === "draw_mw" ? "derived" : "synthetic"])),
      },
    }],
    ...overrides,
  };
}

function node() {
  const adapted = adaptTexasNodes(layer());
  assert.equal(adapted.kind, "ready", JSON.stringify(adapted));
  return adapted.nodes[0];
}

const textOf = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("the marker renders the node's own truth label and the asserted topology token", () => {
  const markup = renderToStaticMarkup(createElement(TexasNodeMarker, { node: node(), scale: "facility" }));
  const text = textOf(markup);
  assert.match(text, new RegExp(escape(STATUS_COPY.synthetic)));
  // The token must reach the user, not just an attribute.
  assert.match(text, new RegExp(escape(SYNTHETIC_TOPOLOGY_LABEL)));
  assert.match(markup, /data-truth-status="synthetic"/);
  assert.doesNotMatch(text, /Source-supported|Source-screened/);
});

test("a node whose provenance asserts no topology gets no topology token", () => {
  const withoutTopology = layer();
  delete withoutTopology.features[0].properties.topology;
  withoutTopology.provenance.topology = "some other topology";
  const adapted = adaptTexasNodes(withoutTopology);
  assert.equal(adapted.kind, "ready");
  const markup = renderToStaticMarkup(createElement(TexasNodeMarker, { node: adapted.nodes[0], scale: "facility" }));
  assert.doesNotMatch(textOf(markup), new RegExp(escape(SYNTHETIC_TOPOLOGY_LABEL)));
  assert.match(markup, /data-topology=""/);
});

test("the inspector's status is the node's server-derived truth, never a fabricated one", () => {
  const inspected = node();
  const asset = texasNodeInspectorAsset(inspected);
  assert.equal(asset.status, inspected.truth.status);
  assert.equal(asset.artifactLabel, inspected.truth.status);
  assert.equal(asset.topology, SYNTHETIC_TOPOLOGY_LABEL);

  const text = textOf(renderToStaticMarkup(createElement(TexasNodeInspector, { node: inspected })));
  assert.match(text, new RegExp(`Status ${escape(STATUS_COPY[inspected.truth.status])}`));
  assert.match(text, new RegExp(`Artifact ${escape(STATUS_COPY[inspected.truth.status])}`));
  // A stamped `source_supported` renders "Source-supported"; it must not appear.
  assert.doesNotMatch(text, /Source-supported/);
});

test("every inspector field points at a per-field provenance key the server actually emits", () => {
  const inspected = node();
  const asset = texasNodeInspectorAsset(inspected);
  const keys = new Set(Object.keys(inspected.fieldProvenance));
  const dangling = asset.fields
    .map((entry) => entry.provenanceId)
    .filter((id) => id !== undefined && !keys.has(id));
  assert.deepEqual(dangling, [], "an inspector field cites an evidence key the server does not emit");
});

test("the inspector names how each critical facility was bound, and never guesses", () => {
  const text = textOf(renderToStaticMarkup(createElement(TexasNodeInspector, { node: node() })));
  assert.match(text, /Central \(same_county\)/);
});
