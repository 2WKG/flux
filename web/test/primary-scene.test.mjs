/**
 * The primary simulation scene, with teeth (2WKG-479).
 *
 * PR #292 and PR #304 both claimed to make the deck.gl simulation the main
 * route, and in both of them **every one of five mutation probes stayed green**:
 * relabelling every node "Source-supported", deleting the label outright, never
 * mounting the scene, and promoting a fixture to the primary simulation were all
 * invisible to the repository. This file is what makes those mutations red, and
 * it is written so that nothing in it can pass by reading source text:
 *
 *  - the composition is asserted on the App's own rendered markup;
 *  - the labels are asserted on the rendered text of the node list, which is
 *    the same string `PrimarySceneDeck`'s `getText` draws (both call `nodeText`);
 *  - the request rules are asserted on the URLs a recording transport received;
 *  - the refusals are asserted by driving the real read seam against real
 *    response bodies, never by matching a sentence in the source.
 *
 * The probes this file is required to catch are listed in the PR body with the
 * exact command and the red output each one produced.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-primary-scene.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { App } from "./src/pages/MainPage";
      import { PrimaryScene } from "./src/renderer/PrimaryScene";
      export * from "./src/data/primary-scene";
      export { nodeText, placeNodes, SCENE_EXTENT } from "./src/renderer/primary-scene-layout";
      export { createReadApiClient } from "./src/data/client-state";
      export { STATUS_COPY, sourceSummary, deriveSourceTruth } from "./src/source-truth";
      export { SYNTHETIC_TOPOLOGY_LABEL } from "./src/scene/minnesota-adapter";
      export { GRID_STATE_BBOX, MAX_PAGES } from "./src/data/grid-client";
      export const renderApp = () => renderToStaticMarkup(createElement(App));
      export const renderScene = (scene) =>
        renderToStaticMarkup(createElement(PrimaryScene, { scene, onRetry: () => {} }));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "primary-scene-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic",
  packages: "external", loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const scene = await import(compiled.href);

const TOPOLOGY = scene.SYNTHETIC_TOPOLOGY_LABEL;
/** The words a synthetic ACTIVSg2000 node must render, composed from the owners. */
const NODE_LABEL = scene.sourceSummary(
  scene.deriveSourceTruth({ sourceId: "activsg2000_case", sourceRef: "data/raw/activsg2000_current/case.m" }),
);

/** A source-backed provenance block, in the shape `spatialItem` accepts. */
const provenanceOf = (sourceId, sourceRef) => ({
  source_id: sourceId, source_record_id: "rec-1", authority: "test authority",
  source_ref: sourceRef, source_version: "v1", retrieved_at: "2026-09-06T00:00:00Z",
});

function item(id, lon, lat, { sourceId = "activsg2000_case", sourceRef = "data/raw/activsg2000_current/case.m" } = {}) {
  return {
    asset_id: id, asset_class: "generation", asset_kind: "bus",
    availability: "available",
    display_geometry: { type: "Point", coordinates: [lon, lat] },
    display_crs: "EPSG:4326",
    native_geometry: null, native_crs: null,
    geometry_status: "source", geometry_accuracy_basis: null, geometry_precision_m: null,
    transform_provenance: null,
    provenance: provenanceOf(sourceId, sourceRef),
  };
}

function page(items, { nextCursor = null, cursor = null, state = "tx", layer = "generation" } = {}) {
  return {
    api_version: "v1", state, artifact_version: "1.1.0", artifact_id: "us-tx:physical-inventory:1.1.0",
    release_sha256: "0".repeat(64), layer, inventory_mode: "physical_observed",
    electrical_model_mode: "none", items,
    page: { limit: 100, cursor, next_cursor: nextCursor, total: items.length },
    coverage: [],
  };
}

/** A transport that records every URL and answers the bodies it is given, in order. */
function transport(bodies) {
  const urls = [];
  const queue = [...bodies];
  return {
    urls,
    client: scene.createReadApiClient(async (url) => {
      urls.push(String(url));
      const body = queue.length > 1 ? queue.shift() : queue[0];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }),
  };
}

const NODES = [item("bus-1", -99.1, 31.2), item("bus-2", -97.4, 30.1), item("bus-3", -95.8, 29.4)];

async function readyScene() {
  const { client } = transport([page(NODES)]);
  const state = await scene.loadPrimaryScene({ layers: ["generation"] }, client);
  assert.equal(state.kind, "ready", `expected a ready scene, got ${JSON.stringify(state)}`);
  return state;
}

const plain = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const labelsIn = (markup) =>
  [...markup.matchAll(/<span class="primary-scene-label">([^<]*)<\/span>/g)].map((match) => match[1].trim());

test("the App mounts the primary simulation scene beside the panels it already carries", () => {
  const markup = scene.renderApp();
  assert.match(markup, /<section class="primary-scene" aria-label="Primary simulation scene">/);
  // Beside, not instead of: unmounting any of these is a different regression
  // that composed-app.test.mjs also catches, and the scene must not cause one.
  for (const [name, pattern] of Object.entries({
    "chat dock": /class="flux-chat"/,
    "run trace": /class="run-trace"/,
    "result cards": /class="ask-result__empty"|class="ask-results"/,
    "layer controls": /class="layer-controls"/,
    "inspector": /class="asset-inspector"/,
    "physical inventory panel": /aria-label="Source-backed physical inventory"/,
  })) {
    assert.match(markup, pattern, `${name} must still be mounted beside the primary scene`);
  }
  // The scene sits outside the workspace grid, so the shell's own layout contract
  // (viewport-shell.test.mjs) is untouched by it.
  assert.ok(markup.indexOf('class="primary-scene"') > markup.indexOf('class="inspector"'));
});

test("the first paint claims no simulation it has not read", () => {
  const markup = scene.renderApp();
  // No node, no label, and above all not the topology assertion: the server
  // render has asked for nothing, so it may not carry the synthetic topology
  // claim. `viewport-shell.test.mjs` pins the same thing for the whole screen.
  assert.deepEqual(labelsIn(markup), []);
  assert.ok(!plain(markup).includes(TOPOLOGY));
});

test("every rendered node carries the synthetic topology label derived from its own provenance", async () => {
  const state = await readyScene();
  assert.equal(state.nodes.length, NODES.length);
  const markup = scene.renderScene(state);
  const labels = labelsIn(markup);
  assert.equal(labels.length, state.nodes.length, "one rendered label per drawn node");
  for (const label of labels) {
    assert.ok(label.length > 0, "a node may never render an empty label");
    assert.ok(label.includes(TOPOLOGY), `a drawn node must carry ${TOPOLOGY}; got "${label}"`);
    assert.ok(label.includes(scene.STATUS_COPY.synthetic), "and the status word its data supports");
    assert.equal(label, NODE_LABEL, "the words are the derived ones, not a relabelling");
  }
  // The canvas draws the same string through the same owner, so a label dropped
  // on either surface is dropped on both.
  for (const node of state.nodes) assert.equal(scene.nodeText(node), node.label);
  assert.deepEqual([...new Set(state.nodes.map((node) => node.truth.topology))], [TOPOLOGY]);
});

test("a record whose provenance is not the synthetic topology is refused, never relabelled into the scene", async () => {
  const foreign = [item("line-1", -95.0, 30.0, { sourceId: "hifld-lines-2024-09-30", sourceRef: "https://example.invalid/lines" })];
  const { client } = transport([page(foreign, { layer: "line" })]);
  const state = await scene.loadPrimaryScene({ layers: ["line"] }, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "no_synthetic_topology_nodes");
  assert.ok(state.message.includes("1 record"), `the refusal must count what it read: ${state.message}`);
  // And the panel renders that state, with no node list and no borrowed label.
  const markup = scene.renderScene(state);
  assert.deepEqual(labelsIn(markup), []);
  assert.ok(!plain(markup).includes(TOPOLOGY));
  assert.match(markup, /aria-label="Primary simulation scene"/);
  assert.ok(plain(markup).includes(scene.STATUS_COPY.unavailable));

  // Mixed input: the synthetic nodes are drawn and the rest are disclosed, not drawn.
  const { client: mixed } = transport([page([...NODES, ...foreign])]);
  const both = await scene.loadPrimaryScene({ layers: ["generation"] }, mixed);
  assert.equal(both.kind, "ready");
  assert.equal(both.nodes.length, NODES.length);
  assert.equal(both.excluded, 1);
  assert.equal(labelsIn(scene.renderScene(both)).length, NODES.length);
  assert.match(plain(scene.renderScene(both)), /1 loaded record is not part of the asserted synthetic topology/);
});

test("the primary simulation never draws another state's release", async () => {
  const { client } = transport([page(NODES, { state: "mn" })]);
  const state = await scene.loadPrimaryScene({ state: "mn", layers: ["generation"] }, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "foreign_state_refused");
  assert.ok(state.message.includes("mn"));
  assert.deepEqual(labelsIn(scene.renderScene(state)), []);
});

test("the read is the versioned layer route, cursor-paged and bounded by the extent it is given", async () => {
  const bbox = [-106, 25, -93, 37];
  const { urls, client } = transport([
    page(NODES.slice(0, 2), { nextCursor: "cursor-2" }),
    page(NODES.slice(2), { cursor: "cursor-2" }),
  ]);
  const state = await scene.loadPrimaryScene({ layers: ["generation"], bbox }, client);
  assert.equal(state.kind, "ready");
  assert.equal(state.nodes.length, NODES.length, "the walk must follow the cursor, not stop at page one");
  assert.equal(urls.length, 2, "one request per page, and no more");
  for (const url of urls) {
    const parsed = new URL(url, "http://localhost");
    assert.match(parsed.pathname, /^\/api\/v1\/grid\/layers\/[^/]+$/, "the versioned route, not a hand-rolled path");
    assert.equal(parsed.searchParams.get("bbox"), bbox.join(","), "every page request carries the extent");
    assert.ok(Number(parsed.searchParams.get("limit")) > 0, "every page request is bounded by a limit");
  }
  assert.equal(new URL(urls[0], "http://localhost").searchParams.get("cursor"), null);
  assert.equal(new URL(urls[1], "http://localhost").searchParams.get("cursor"), "cursor-2");
  assert.equal(state.truncated, false);
});

test("a walk that never ends stops at the cap and discloses it rather than looping", async () => {
  const { urls, client } = transport([page(NODES, { nextCursor: "always-more" })]);
  const state = await scene.loadPrimaryScene({ layers: ["generation"] }, client);
  assert.equal(state.kind, "ready");
  assert.equal(urls.length, scene.MAX_PAGES, "the walk is capped");
  assert.equal(state.truncated, true);
  assert.equal(state.nextCursor, "always-more");
  assert.match(plain(scene.renderScene(state)), /page walk stopped at its cap/);
});

test("with the API unreachable the scene names the state instead of drawing an empty simulation", async () => {
  const client = scene.createReadApiClient(async () => { throw new TypeError("Failed to fetch"); });
  const state = await scene.loadPrimaryScene({ layers: ["generation"] }, client);
  assert.equal(state.kind, "unavailable");
  assert.ok(["unavailable", "request_failed"].includes(state.status));
  assert.ok(state.message.length > 0, "the refusal must carry a reason");
  const markup = scene.renderScene(state);
  assert.deepEqual(labelsIn(markup), [], "an unreachable API may not produce a drawn node");
  assert.match(markup, /Retry the simulation request/);
});

test("the server's own refusal survives to the scene, verbatim", async () => {
  const client = scene.createReadApiClient(async () => new Response(JSON.stringify({
    status: "unavailable", data: null,
    error: { code: "unavailable", message: "No release 1.1.0 is published for state tx.", retryable: true, retry_after_s: 30, details: { reason: "release_not_found" } },
    meta: { api_version: "v1", request_id: "req-42", generated_at: "2026-09-06T00:00:00Z" },
  }), { status: 503, headers: { "content-type": "application/json" } }));
  const state = await scene.loadPrimaryScene({ layers: ["generation"] }, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.message, "No release 1.1.0 is published for state tx.");
  assert.equal(state.requestId, "req-42");
  assert.match(plain(scene.renderScene(state)), /No release 1\.1\.0 is published for state tx\./);
});

test("the schematic layout places every node it is given and asserts no geography", async () => {
  const state = await readyScene();
  const placed = scene.placeNodes(state.nodes);
  assert.equal(placed.length, state.nodes.length, "no node is silently dropped by the layout");
  for (const node of placed) {
    assert.equal(typeof node.xy[0], "number");
    assert.ok(Math.abs(node.xy[0]) <= scene.SCENE_EXTENT + 1e-9, "the layout stays inside the schematic square");
    assert.ok(Math.abs(node.xy[1]) <= scene.SCENE_EXTENT + 1e-9);
    assert.equal(scene.nodeText(node), node.label, "the layout never rewrites a node's words");
  }
  // A layout is not a projection: the drawn coordinates are not the published ones.
  assert.notDeepEqual(placed.map((node) => [...node.xy]), state.nodes.map((node) => [...node.position]));
  assert.deepEqual(scene.placeNodes([]), []);
});
