import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const compiled = new URL("../../../node_modules/.cache/gnn-message-passing.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./messagePassing.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const {
  contingencyCounts,
  GNN_MODEL_OUTPUTS,
  GNN_STATUS,
  GNN_STATUS_EVIDENCE,
  hopDistances,
  messagePassingRounds,
  nodeDegrees,
  receptiveField,
  SCHEMATIC_EDGES,
  SCHEMATIC_NODES,
} = await import(`${compiled.href}?t=${Date.now()}`);

test("the schematic graph is well formed: every edge joins two distinct known nodes, once", () => {
  const ids = new Set(SCHEMATIC_NODES.map((node) => node.id));
  assert.equal(ids.size, SCHEMATIC_NODES.length);
  const pairs = new Set();
  for (const edge of SCHEMATIC_EDGES) {
    assert.ok(ids.has(edge.from) && ids.has(edge.to), `${edge.id} references an unknown node`);
    assert.notEqual(edge.from, edge.to);
    const key = [edge.from, edge.to].sort().join("~");
    assert.ok(!pairs.has(key), `${edge.id} duplicates a branch`);
    pairs.add(key);
    assert.ok(edge.reactance > 0 && edge.ratingMw > 0);
  }
  const degrees = nodeDegrees();
  assert.equal(
    Object.values(degrees).reduce((sum, value) => sum + value, 0),
    2 * SCHEMATIC_EDGES.length,
    "handshake lemma: degrees must sum to twice the edge count",
  );
  assert.ok(Object.values(degrees).every((degree) => degree > 0), "no isolated bus");
});

test("message passing reaches the graph one hop at a time from the west generator", () => {
  const rounds = messagePassingRounds("b1", 5);
  assert.deepEqual(rounds[0].reached, ["b1"]);
  assert.deepEqual(rounds[0].carryingEdgeIds, []);
  assert.deepEqual(rounds[1].newlyReached, ["b2", "b3"]);
  assert.deepEqual(rounds[2].newlyReached, ["b4"]);
  assert.deepEqual(rounds[3].newlyReached, ["b5", "b6"]);
  assert.deepEqual(rounds[4].newlyReached, ["b7"]);
  assert.deepEqual(rounds[5].newlyReached, ["b8", "b9"]);
  assert.equal(rounds[5].reached.length, SCHEMATIC_NODES.length);
  for (const round of rounds) {
    // Hop 0 is the seed holding its own features, reached by no edge; every later
    // hop reaches each new node across exactly one carrying edge.
    assert.equal(round.carryingEdgeIds.length, round.hop === 0 ? 0 : round.newlyReached.length);
    assert.equal(new Set(round.reached).size, round.reached.length, "a node is reached at most once");
  }
});

test("hop distances agree with the rounds and are symmetric between two nodes", () => {
  const distances = hopDistances("b1");
  assert.equal(distances.b1, 0);
  assert.equal(distances.b4, 2);
  assert.equal(distances.b7, 4);
  assert.equal(distances.b9, 5);
  assert.ok(Object.values(distances).every((value) => value !== null), "the schematic is connected");
  for (const node of SCHEMATIC_NODES) {
    assert.equal(hopDistances("b1")[node.id], distances[node.id]);
    assert.equal(
      hopDistances(node.id).b1,
      distances[node.id],
      `hop distance b1 <-> ${node.id} must be symmetric on an undirected graph`,
    );
  }
});

test("the receptive field grows with layers and reports what the depth cannot see", () => {
  const total = SCHEMATIC_NODES.length;
  const zero = receptiveField("b1", 0);
  assert.equal(zero.seenCount, 1);
  assert.equal(zero.blindCount, total - 1);
  const two = receptiveField("b1", 2);
  assert.equal(two.seenCount, 4);
  assert.deepEqual(two.blind, ["b5", "b6", "b7", "b8", "b9"]);
  let previous = 0;
  for (let layers = 0; layers <= 6; layers += 1) {
    const field = receptiveField("b1", layers);
    assert.ok(field.seenCount >= previous, "the receptive field never shrinks");
    assert.equal(field.seenCount + field.blindCount, total);
    previous = field.seenCount;
  }
  assert.equal(receptiveField("b1", 5).blindCount, 0);
  assert.equal(receptiveField("b1", 6).seenCount, total, "extra layers past the diameter add nothing");
});

test("bad inputs fail loudly rather than returning a plausible default", () => {
  assert.throws(() => messagePassingRounds("nope", 2), /Unknown seed node/);
  assert.throws(() => messagePassingRounds("b1", -1), /non-negative integer/);
  assert.throws(() => messagePassingRounds("b1", 1.5), /non-negative integer/);
});

test("contingency counts are exact combinatorics over the schematic branches", () => {
  const counts = contingencyCounts();
  assert.equal(counts.edges, SCHEMATIC_EDGES.length);
  assert.equal(counts.n1, 12);
  assert.equal(counts.n2, 66);
  assert.equal(counts.n2, (counts.edges * (counts.edges - 1)) / 2);
});

test("the section declares the GNN as not running and shows no model output", async () => {
  assert.equal(GNN_STATUS, "not_running");
  assert.ok(GNN_STATUS_EVIDENCE.length >= 3);
  assert.deepEqual(GNN_MODEL_OUTPUTS, {
    model_count: 0,
    run_count: 0,
    prediction_count: 0,
    published_error_metric_count: 0,
  });

  const raw = await Promise.all(
    ["./GnnSection.tsx", "./messagePassing.ts", "./index.ts"].map((name) =>
      readFile(new URL(name, import.meta.url), "utf8"),
    ),
  );
  // Prose about what the section refuses to do ("no WebGL, no network call") is not
  // a violation, so the code rules run against the source with comments removed.
  const sources = raw.map((source) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, ""));
  for (const source of sources) {
    assert.doesNotMatch(source, /(?:from\s*|import\s*\()["'](?:deck\.gl|@deck\.gl\/|maplibre-gl|react-map-gl)/);
    assert.doesNotMatch(source, /\bfetch\s*\(|XMLHttpRequest|WebGL|getContext\s*\(/);
    // No accuracy, error, or speed claim may appear: none has been published.
    assert.doesNotMatch(source, /\d+(?:\.\d+)?\s*%\s*(?:accura|error|MAPE|R2)/i);
    assert.doesNotMatch(source, /\d+(?:\.\d+)?\s*(?:x|×)\s*(?:faster|speed)/i);
    assert.doesNotMatch(source, /\b\d+(?:\.\d+)?\s*(?:ms|milliseconds|seconds)\b/i);
  }

  const section = sources[0];
  assert.match(section, /Status: not running/);
  assert.match(section, /Published error metrics/);
  assert.match(section, /Use the model to screen\. Use the solver to decide\./);
});
