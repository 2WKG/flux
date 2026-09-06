/** Tests for the per-layer legend model of 2WKG-373.
 *
 * The registry, data-status disclosure, and suppression rules already landed on
 * master; this adds the legend *model* -- no surface renders it yet, so the
 * ticket's "each layer has a legend" clause stays open. These assertions are
 * rules rather than shape checks: every entry must carry readable text and a
 * non-colour glyph, the entry set must be exactly the six frozen statuses with
 * no decorative seventh, every layer must get a legend, and an unrecognised
 * status must fail closed the same way `filters.ts` refuses it.
 */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = new URL("../../", import.meta.url);
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-layers-legend-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));

// Compiled with esbuild under the project tsconfig, the same seam
// src/layers/layer-controls.test.mjs uses, rather than a bare `tsc` invocation:
// `../source-truth.ts` -- the owner of the six display strings this module
// imports -- uses the project's extensionless imports, which only resolve under
// that tsconfig. `npm run typecheck` remains the type gate; this is a compile.
const bundle = join(outputDirectory, "entry.mjs");
await build({
  stdin: {
    contents: [
      'export * from "./src/layers/legend";',
      'export * from "./src/layers/registry";',
      'export { STATUS_COPY } from "./src/source-truth";',
    ].join("\n"),
    resolveDir: fileURLToPath(webRoot),
    loader: "ts",
    sourcefile: "legend-test-entry.ts",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  absWorkingDir: fileURLToPath(webRoot),
  tsconfig: join(fileURLToPath(webRoot), "tsconfig.json"),
  outfile: bundle,
  logLevel: "silent",
});

const {
  STATUS_LEGEND,
  legendForLayer,
  legendsForLayers,
  UNKNOWN_STATUS_GLYPH,
  REQUEST_ID_UNSUPPLIED,
  LAYER_REGISTRY,
  buildRegistrySnapshots,
  snapshotOf,
  // The display strings have one owner; read from it here so a divergence
  // between the owner and the legend is a failure, not a second spelling.
  STATUS_COPY,
} = await import(pathToFileURL(bundle).href);

const FROZEN_STATUSES = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
  "unavailable",
  "request_failed",
];

test("the legend holds exactly the six frozen statuses, with no decorative seventh", () => {
  assert.deepEqual(
    STATUS_LEGEND.map((entry) => entry.status),
    FROZEN_STATUSES,
  );
  // `illustrative` was retired because no server field asserts it. A legend is
  // exactly the place someone would be tempted to reintroduce it.
  assert.ok(!STATUS_LEGEND.some((entry) => entry.status === "illustrative"));
  // Checked against code with comments stripped: the module docstring names the
  // retired label in order to explain its absence, which is not a reintroduction.
  const source = readFileSync(new URL("src/layers/legend.ts", webRoot), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  assert.doesNotMatch(source, /illustrative/);
});

test("no entry relies on colour alone: each carries readable text and a named glyph", () => {
  for (const entry of STATUS_LEGEND) {
    assert.ok(entry.label.trim().length > 0, `${entry.status} has no label`);
    assert.ok(entry.description.trim().length > 0, `${entry.status} has no description`);
    assert.ok(entry.glyph.trim().length > 0, `${entry.status} has no glyph`);
    // A glyph must be a name, never a colour value.
    assert.doesNotMatch(entry.glyph, /^#|rgb|hsl/i, `${entry.status} glyph looks like a colour`);
  }
  // Labels are distinct, so two statuses can never read identically.
  assert.equal(new Set(STATUS_LEGEND.map((e) => e.label)).size, FROZEN_STATUSES.length);
});

test("every registry layer gets a legend carrying its current status", () => {
  const snapshots = buildRegistrySnapshots(
    Object.fromEntries(LAYER_REGISTRY.map((d) => [d.id, { kind: "unavailable", reason: "no accepted coverage" }])),
  );
  const legends = legendsForLayers(snapshots);

  assert.equal(legends.length, LAYER_REGISTRY.length);
  assert.deepEqual(
    legends.map((l) => l.layerId),
    LAYER_REGISTRY.map((d) => d.id),
  );
  for (const legend of legends) {
    assert.equal(legend.currentStatus, "unavailable");
    assert.equal(legend.currentReason, "no accepted coverage");
    assert.equal(legend.entries.length, FROZEN_STATUSES.length);
    assert.equal(legend.unrecognized, false);
  }
});

test("a layer's own reason travels with its legend rather than being dropped", () => {
  const definition = LAYER_REGISTRY[0];
  const legend = legendForLayer(
    snapshotOf(definition, { kind: "request_failed", reason: "provider timeout", requestId: "req-7" }),
  );

  assert.equal(legend.currentStatus, "request_failed");
  assert.equal(legend.currentReason, "provider timeout");
  // The IA's accompanying copy for the `Request failed` row requires the request
  // ID when the producer supplies one; the snapshot carries it, so the legend must.
  assert.equal(legend.currentRequestId, "req-7");
  assert.equal(legend.unrecognized, false);
});

test("a request_failed layer with no request ID refuses by name rather than defaulting", () => {
  const legend = legendForLayer(
    snapshotOf(LAYER_REGISTRY[0], { kind: "request_failed", reason: "provider timeout" }),
  );

  assert.equal(legend.currentStatus, "request_failed");
  // Named refusal, never a fabricated or plausible-looking ID.
  assert.equal(legend.currentRequestId, REQUEST_ID_UNSUPPLIED);
  assert.equal(REQUEST_ID_UNSUPPLIED, "request-id-unsupplied");
  assert.doesNotMatch(REQUEST_ID_UNSUPPLIED, /^req[-_]?\d/i, "the refusal must not read as an ID");
});

test("a layer that did not fail carries no request ID at all", () => {
  const available = legendForLayer(
    snapshotOf(LAYER_REGISTRY[1], { kind: "available", status: "source_supported" }),
  );
  assert.equal(available.currentRequestId, undefined);

  const unavailable = legendForLayer(
    snapshotOf(LAYER_REGISTRY[0], { kind: "unavailable", reason: "no accepted coverage" }),
  );
  assert.equal(unavailable.currentRequestId, undefined);
});

test("the six labels come from their single owner, and match the IA table by label", () => {
  // One owner: `src/source-truth.ts` STATUS_COPY, as `status-glyphs.ts` declares.
  // Relabelling any status in the owner moves this assertion.
  assert.deepEqual(
    STATUS_LEGEND.map((entry) => entry.label),
    FROZEN_STATUSES.map((status) => STATUS_COPY[status]),
  );

  // And the owner's strings are the IA's "UI label" column. Rows are found by
  // their label, not by line number, so the table may move in the document.
  const iaTable = readFileSync(
    new URL("../docs/design/minnesota-demo-narrative-ia.md", webRoot),
    "utf8",
  );
  const lines = iaTable.split("\n");
  const header = lines.findIndex((line) => line.startsWith("| UI label |"));
  assert.ok(header > 0, "the IA no longer has a truth-label table with a UI label column");
  const body = [];
  for (let i = header + 2; i < lines.length && lines[i].startsWith("|"); i += 1) {
    body.push(lines[i].replace(/^\||\|$/g, "").split(" | ").map((cell) => cell.trim()));
  }
  const truthRows = new Map(body.map((cells) => [cells[0], cells]));
  assert.equal(truthRows.size, FROZEN_STATUSES.length, "the IA table is no longer six rows");

  for (const entry of STATUS_LEGEND) {
    assert.ok(truthRows.has(entry.label), `no IA truth-label row reads "${entry.label}"`);
  }
  // The row this PR's request-ID carry answers to, located by its label.
  assert.match(truthRows.get("Request failed")[3], /request ID/);
});

test("an unrecognised status fails closed instead of being coerced to a friendly default", () => {
  const legend = legendForLayer({ id: "topology", label: "Topology", status: "illustrative" });

  assert.equal(legend.unrecognized, true);
  assert.equal(legend.currentStatus, "unavailable");
  // It still gets the full key, and the unknown glyph is a name, not a colour.
  assert.equal(legend.entries.length, FROZEN_STATUSES.length);
  assert.equal(UNKNOWN_STATUS_GLYPH, "unrecognized-status");
});

test("an available layer keeps its status and carries no invented reason", () => {
  const legend = legendForLayer(
    snapshotOf(LAYER_REGISTRY[1], { kind: "available", status: "source_supported" }),
  );

  assert.equal(legend.currentStatus, "source_supported");
  assert.equal(legend.currentReason, undefined);
  assert.equal(legend.unrecognized, false);
});
