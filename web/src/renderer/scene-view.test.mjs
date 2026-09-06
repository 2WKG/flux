import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-scene-view-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Same shape as src/scene/minnesota-adapter.test.mjs: compile the one module under
// test with this Node binary (the .bin/tsc shim is POSIX-only) and import the output.
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/renderer/scene-view.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  PLACEABLE_STATUS_LABELS,
  STATUS_LABELS,
  acceptedPoints,
  sceneViewFor,
  statusLabelOf,
} = await import(pathToFileURL(join(outputDirectory, "scene-view.js")).href);

/** An ACTIVSg2000-family node: synthetic topology at central-Minnesota coordinates. */
function syntheticTopologyScene() {
  return {
    kind: "topology_scene",
    nodes: [{ id: "activsg2000-1", name: "Synthetic bus", position: [-94.2, 46.2], truthLabel: "synthetic" }],
    provenance: { layer: "buses", crs: "EPSG:4326", sourceNames: [], fixtureBatchIds: [], topology: "synthetic (ACTIVSg2000)" },
  };
}

/** The master adapter's accepted shape. */
function sourceBackedTopologyScene() {
  return {
    kind: "topology_scene",
    nodes: [{ id: "mn-1", name: "Accepted node", position: [-93.26, 44.98], truthLabel: "source_backed" }],
    provenance: { layer: "buses", crs: "EPSG:4326", sourceNames: ["mn_accepted"], fixtureBatchIds: ["batch-1"], topology: null },
  };
}

/** PR #210's server-bound shape, same decision, different vocabulary. */
function boundPlacement(statusLabel = "source_supported") {
  return {
    kind: "bound_placement",
    placement: {
      id: "artifact-1:scene-1",
      sourceArtifactId: "artifact-1",
      archetypeId: "substation",
      semanticType: "substation",
      position: [-93.26, 44.98],
      statusLabel,
    },
  };
}

test("the six shared status tokens are the whole vocabulary and only two may place geometry", () => {
  assert.deepEqual([...STATUS_LABELS], [
    "source_supported",
    "source_screened",
    "hypothetical",
    "synthetic",
    "unavailable",
    "request_failed",
  ]);
  assert.deepEqual([...PLACEABLE_STATUS_LABELS], ["source_supported", "source_screened"]);
  for (const label of ["synthetic", "hypothetical", "unavailable", "request_failed"]) {
    assert.ok(!PLACEABLE_STATUS_LABELS.includes(label), `${label} must never place geometry`);
  }
});

test("an unknown label is reported unavailable, never upgraded into a placeable one", () => {
  for (const label of [undefined, null, "", "source_backed_ish", "accepted", "observed", 7] ) {
    const status = statusLabelOf(label);
    assert.ok(STATUS_LABELS.includes(status), `${String(label)} produced ${status}`);
    assert.equal(status, "unavailable", `${String(label)} must not be upgraded`);
  }
  // The only translation between the two adapter vocabularies.
  assert.equal(statusLabelOf("source_backed"), "source_supported");
  assert.equal(statusLabelOf("synthetic"), "synthetic");
});

test("synthetic ACTIVSg2000 topology is never rendered as a geographic feature layer", () => {
  const view = sceneViewFor(syntheticTopologyScene());

  assert.equal(view.status, "synthetic");
  // The node is carried (the renderer must be able to say what it refused)...
  assert.equal(view.points.length, 1);
  assert.deepEqual(view.points[0].position, [-94.2, 46.2]);
  // ...and it is refused.
  assert.deepEqual(acceptedPoints(view), []);
  assert.match(view.detail, /not rendered as a geographic feature layer/i);
});

test("one synthetic node suppresses the whole layer, it is not filtered out of it", () => {
  const mixed = {
    kind: "topology_scene",
    nodes: [
      { id: "mn-1", name: "Accepted", position: [-93.26, 44.98], truthLabel: "source_backed" },
      { id: "activsg2000-1", name: "Synthetic", position: [-94.2, 46.2], truthLabel: "synthetic" },
    ],
  };
  const view = sceneViewFor(mixed);
  assert.equal(view.status, "synthetic");
  assert.deepEqual(acceptedPoints(view), []);
});

test("accepted source-backed topology does reach the renderer, in both adapter vocabularies", () => {
  // Mutation-verification for the refusal tests above: if acceptedPoints() were a
  // constant [] the refusals would pass vacuously. This is the state that must draw.
  const master = sceneViewFor(sourceBackedTopologyScene());
  assert.equal(master.status, "source_supported");
  assert.equal(acceptedPoints(master).length, 1);
  assert.deepEqual(acceptedPoints(master)[0], {
    id: "mn-1",
    position: [-93.26, 44.98],
    statusLabel: "source_supported",
  });

  const bound = sceneViewFor(boundPlacement("source_supported"));
  assert.equal(bound.status, "source_supported");
  assert.equal(acceptedPoints(bound).length, 1);
  assert.equal(acceptedPoints(bound)[0].id, "artifact-1:scene-1");

  const screened = sceneViewFor(boundPlacement("source_screened"));
  assert.equal(acceptedPoints(screened).length, 1);

  for (const refused of ["hypothetical", "synthetic", "unavailable", "request_failed"]) {
    const view = sceneViewFor(boundPlacement(refused));
    assert.equal(view.status, refused);
    assert.deepEqual(acceptedPoints(view), [], `${refused} placement must not be drawn`);
  }
});

test("rejections and aggregate coverage carry no drawable geometry, in both vocabularies", () => {
  const rejected = sceneViewFor({ kind: "rejected", reason: "synthetic_topology_not_minnesota", detail: "Texas-shaped." });
  assert.equal(rejected.status, "unavailable");
  assert.deepEqual(rejected.points, []);
  assert.equal(rejected.detail, "Texas-shaped.");

  const failed = sceneViewFor({ kind: "rejected", reason: "request_failed", detail: "The layer request failed." });
  assert.equal(failed.status, "request_failed");

  const zones = sceneViewFor({ kind: "aggregate_zones", zones: [{ id: "z1", name: "Zone", truthLabel: "source_backed" }], renderableGeometry: false });
  assert.deepEqual(acceptedPoints(zones), []);

  const coverage = sceneViewFor({
    kind: "aggregate_coverage",
    manifestFormat: "flux-minnesota-aggregate-v1",
    allocationStatus: "source_supported",
    allocationLimit: "aggregate only",
    sourceIds: ["s1"],
    renderableGeometry: false,
  });
  // An accepted aggregate keeps its accepted status label and still draws nothing:
  // renderableGeometry is false, so there is no geometry to accept.
  assert.equal(coverage.status, "source_supported");
  assert.deepEqual(acceptedPoints(coverage), []);
  assert.match(coverage.detail, /no renderable geometry/i);
});

test("a malformed or unlabeled node is refused whole, never partially drawn", () => {
  for (const nodes of [
    [{ id: "mn-1", position: [-93.26, 44.98], truthLabel: "source_backed" }, { id: "bad", position: ["x", 1], truthLabel: "source_backed" }],
    [{ id: "", position: [-93.26, 44.98], truthLabel: "source_backed" }],
    [{ id: "mn-1", position: [Number.NaN, 44.98], truthLabel: "source_backed" }],
    [{ id: "mn-1", position: [-93.26, 44.98] }],
  ]) {
    const view = sceneViewFor({ kind: "topology_scene", nodes });
    assert.deepEqual(acceptedPoints(view), [], JSON.stringify(nodes));
  }
});
