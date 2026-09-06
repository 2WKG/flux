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
 * **And the label rule is proved NON-VACUOUSLY.** The first cut of this seam
 * read the source-backed physical-inventory layer route, whose 11 949 Texas
 * assets carry `eia860_2025er` / `hifld-lines-2024-09-30` provenance and never
 * derive `synthetic (ACTIVSg2000)`. Every mutation probe went red and the scene
 * still drew nothing against a real server, because the guarantee held only
 * where nothing was rendered. So the ready-state tests below are driven against
 * `data/artifacts/synthetic_topology/tx/activsg2000-current-v1.json.gz` — the
 * **committed release the `/demo/model` route itself serves**, decompressed and
 * replayed through the real read client — and they assert that thousands of
 * nodes actually render. A hand-written fixture cannot satisfy them.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { gunzipSync } from "node:zlib";
import { mkdir, readFile } from "node:fs/promises";
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

/**
 * The committed synthetic-topology release, exactly as `/demo/model` serves it.
 *
 * `copilot/routes/model_geometry.py` answers with `artifact["payload"]` from this
 * very file when no DuckDB build is present, so this is the production body, not
 * a fixture derived from a spec. Every ready-state assertion below runs against
 * it; if the route's real content ever stopped carrying the synthetic topology,
 * these tests would go red rather than passing vacuously.
 */
const RELEASE_PATH = new URL("../../data/artifacts/synthetic_topology/tx/activsg2000-current-v1.json.gz", import.meta.url);
const RELEASE_ARTIFACT = JSON.parse(gunzipSync(await readFile(RELEASE_PATH)).toString("utf8"));
const RELEASE_PAYLOAD = RELEASE_ARTIFACT.payload;
assert.equal(RELEASE_ARTIFACT.artifact_id, "tx:synthetic-topology:activsg2000-current-v1",
  "the committed release this suite replays must be the synthetic topology artifact");

/** The words a synthetic ACTIVSg2000 element must render, composed from the owners. */
const NODE_LABEL = scene.sourceSummary(
  scene.deriveSourceTruth({ sourceId: "bus:1001", sourceRef: TOPOLOGY }),
);

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

const plain = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const labelsIn = (markup) =>
  [...markup.matchAll(/<span class="primary-scene-label">([^<]*)<\/span>/g)].map((match) => match[1].trim());

async function readyScene(payload = RELEASE_PAYLOAD) {
  const { client, urls } = transport([payload]);
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "ready", `expected a ready scene, got ${JSON.stringify(state).slice(0, 400)}`);
  return { state, urls };
}

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
    "synthetic topology workspace": /aria-label="Full synthetic Texas topology workspace"/,
  })) {
    assert.match(markup, pattern, `${name} must still be mounted beside the primary scene`);
  }
  // The scene sits outside the workspace grid, so the shell's own layout contract
  // (viewport-shell.test.mjs) is untouched by it.
  assert.ok(markup.indexOf('class="primary-scene"') > markup.indexOf('class="workspace model-workspace"'));
});

test("the first paint claims no simulation it has not read", () => {
  const markup = scene.renderApp();
  // No node and no label: the server render has asked for nothing, so the scene
  // may carry no drawn node and no derived label.
  assert.deepEqual(labelsIn(markup), []);
  assert.ok(!plain(markup.slice(markup.indexOf('class="primary-scene"'))).includes(TOPOLOGY));
});

test("the committed release actually renders: the label rule is not vacuously true", async () => {
  const { state } = await readyScene();
  // The whole point. Against the real route's own release, nodes exist.
  assert.ok(state.nodes.length > 1000,
    `the committed release must actually draw nodes, got ${state.nodes.length}`);
  assert.equal(state.nodes.length, 3669, "buses + generators + loads of the committed release");
  assert.equal(state.topology.label, TOPOLOGY);
  assert.equal(state.topology.declaredBuses, 2000);
  // Branches are LineStrings, not node positions: disclosed, not drawn, not relabelled.
  assert.equal(state.excluded, 3206);
  assert.equal(state.refusedTopology, 0,
    "every element of the committed release derives the asserted synthetic topology");
});

test("every rendered node carries the synthetic topology label derived from its own provenance", async () => {
  const { state } = await readyScene();
  const markup = scene.renderScene(state);
  const labels = labelsIn(markup);
  assert.ok(labels.length > 0, "the ready scene must render at least one labelled node");
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

test("an element whose provenance is not the synthetic topology is refused, never relabelled into the scene", async () => {
  const elements = RELEASE_PAYLOAD.data.elements;
  const buses = elements.filter((element) => element.role === "bus").slice(0, 3);
  // The same element shape the route publishes, with a foreign topology in its
  // own provenance. Nothing else about it changes.
  const foreign = {
    ...buses[0],
    element_id: "bus:999999",
    source_id: "bus:999999",
    provenance: { coordinate_source: "tamu_aux", topology: "observed (EIA-860 2025ER)" },
  };
  const only = {
    ...RELEASE_PAYLOAD,
    data: { ...RELEASE_PAYLOAD.data, elements: [foreign] },
  };
  const { client } = transport([only]);
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "no_synthetic_topology_nodes");
  assert.ok(state.message.includes("1 element"), `the refusal must count what it read: ${state.message}`);
  const markup = scene.renderScene(state);
  assert.deepEqual(labelsIn(markup), []);
  assert.ok(!plain(markup).includes(TOPOLOGY));
  assert.match(markup, /aria-label="Primary simulation scene"/);
  assert.ok(plain(markup).includes(scene.STATUS_COPY.unavailable));

  // Mixed input: the synthetic nodes are drawn and the rest are disclosed, not drawn.
  const mixedPayload = {
    ...RELEASE_PAYLOAD,
    data: { ...RELEASE_PAYLOAD.data, elements: [...buses, foreign] },
  };
  const { client: mixed } = transport([mixedPayload]);
  const both = await scene.loadPrimaryScene({}, mixed);
  assert.equal(both.kind, "ready");
  assert.equal(both.nodes.length, buses.length);
  assert.equal(both.excluded, 1);
  assert.equal(both.refusedTopology, 1);
  assert.equal(labelsIn(scene.renderScene(both)).length, buses.length);
  assert.match(plain(scene.renderScene(both)),
    /1 loaded element is not drawn as node, of which 1 does not derive the asserted synthetic topology/);
});

/**
 * The regression this suite exists to prevent: the seam pointed at the wrong route.
 *
 * `GET /api/v1/grid/layers/{layer}` serves the committed **physical inventory**
 * release below -- 11 949 Texas assets whose provenance is `eia860_2025er` and
 * `hifld-lines-2024-09-30`. Not one of them derives `synthetic (ACTIVSg2000)`,
 * which is why reading that route drew nothing while every mutation probe still
 * went red. This test replays that release's own records through the seam and
 * pins the two facts together: the source-backed route's real content is not
 * drawable here, and the scene says so by name rather than rendering an empty
 * simulation that looks fine.
 */
const INVENTORY_PATH = new URL("../../data/artifacts/physical_inventory/tx/physical-inventory-1.1.0.json.gz", import.meta.url);
const INVENTORY = JSON.parse(gunzipSync(await readFile(INVENTORY_PATH)).toString("utf8"));

test("the source-backed physical inventory cannot feed this scene, and is refused by name", async () => {
  const assets = INVENTORY.assets;
  assert.ok(assets.length > 10_000, `expected the real inventory release, got ${assets.length} assets`);
  // Not one asset of the real release derives the asserted synthetic topology.
  const derived = assets.filter((asset) => scene.deriveSourceTruth({
    sourceId: String(asset.provenance?.source_id ?? ""),
    sourceRef: String(asset.provenance?.source_ref ?? ""),
  }).topology === TOPOLOGY);
  assert.equal(derived.length, 0,
    "the source-backed release derives no synthetic topology; that is why it cannot be this scene's route");

  // Its records, carried in the model route's own envelope, draw nothing and are named.
  const elements = assets.slice(0, 200).map((asset) => ({
    element_id: String(asset.asset_id),
    source_id: String(asset.provenance?.source_id ?? ""),
    resolved: true,
    role: "asset",
    geometry: asset.display_geometry,
    provenance: { coordinate_source: "source", topology: String(asset.provenance?.source_ref ?? "") },
  }));
  const { client } = transport([{ ...RELEASE_PAYLOAD, data: { ...RELEASE_PAYLOAD.data, elements } }]);
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "no_synthetic_topology_nodes");
  const markup = scene.renderScene(state);
  assert.deepEqual(labelsIn(markup), []);
  assert.ok(!plain(markup).includes(TOPOLOGY));
});

test("the primary simulation never draws a release that declares another topology", async () => {
  const foreignRelease = {
    ...RELEASE_PAYLOAD,
    data: { ...RELEASE_PAYLOAD.data, topology: { ...RELEASE_PAYLOAD.data.topology, label: "observed (EIA-860 2025ER)" } },
  };
  const { client } = transport([foreignRelease]);
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "foreign_topology_refused");
  assert.ok(state.message.includes("observed (EIA-860 2025ER)"));
  assert.deepEqual(labelsIn(scene.renderScene(state)), []);
});

test("the read is the published read-only model route, and one request", async () => {
  const { urls } = await readyScene();
  assert.equal(urls.length, 1, "one request for the whole release, and no more");
  const parsed = new URL(urls[0], "http://localhost");
  assert.equal(parsed.pathname, scene.PRIMARY_SCENE_PATH, "the published route, not a hand-rolled path");
  assert.equal(parsed.pathname, "/demo/model");
});

test("a status this scene cannot draw is named, never guessed at", async () => {
  // `/demo/model` publishes `available` / `partial` / `unavailable`; an
  // `unavailable` answer arrives as the shared failure envelope (asserted
  // separately below). Any other status is one this scene has no rule for, and
  // it is refused by name rather than treated as a drawable release.
  const { client } = transport([{ ...RELEASE_PAYLOAD, status: "degraded" }]);
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.code, "model_route_unavailable");
  assert.ok(state.message.includes("degraded"));
  assert.deepEqual(labelsIn(scene.renderScene(state)), []);
});

test("a partial release is drawn, and says so through its own declared status", async () => {
  const { state } = await readyScene({ ...RELEASE_PAYLOAD, status: "partial" });
  assert.ok(state.nodes.length > 0, "a partial release still carries drawable synthetic nodes");
});

test("with the API unreachable the scene names the state instead of drawing an empty simulation", async () => {
  const client = scene.createReadApiClient(async () => { throw new TypeError("Failed to fetch"); });
  const state = await scene.loadPrimaryScene({}, client);
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
    error: { code: "unavailable", message: "Synthetic model geometry is unavailable.", retryable: true, retry_after_s: 30, details: { reason: "unavailable" } },
    meta: { api_version: "v1", request_id: "req-42", generated_at: "2026-09-06T00:00:00Z" },
  }), { status: 503, headers: { "content-type": "application/json" } }));
  const state = await scene.loadPrimaryScene({}, client);
  assert.equal(state.kind, "unavailable");
  assert.equal(state.message, "Synthetic model geometry is unavailable.");
  assert.equal(state.requestId, "req-42");
  assert.match(plain(scene.renderScene(state)), /Synthetic model geometry is unavailable\./);
});

test("the schematic layout places every node it is given and asserts no geography", async () => {
  const { state } = await readyScene();
  const sample = state.nodes.slice(0, 200);
  const placed = scene.placeNodes(sample);
  assert.equal(placed.length, sample.length, "no node is silently dropped by the layout");
  for (const node of placed) {
    assert.equal(typeof node.xy[0], "number");
    assert.ok(Math.abs(node.xy[0]) <= scene.SCENE_EXTENT + 1e-9, "the layout stays inside the schematic square");
    assert.ok(Math.abs(node.xy[1]) <= scene.SCENE_EXTENT + 1e-9);
    assert.equal(scene.nodeText(node), node.label, "the layout never rewrites a node's words");
  }
  // A layout is not a projection: the drawn coordinates are not the published ones.
  assert.notDeepEqual(placed.map((node) => [...node.xy]), sample.map((node) => [...node.position]));
  assert.deepEqual(scene.placeNodes([]), []);
});
