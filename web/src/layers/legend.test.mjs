/** Tests for the per-layer legend that completes 2WKG-373.
 *
 * The registry, data-status disclosure, and suppression rules already landed on
 * master; what remained was "each layer has a legend". These assertions are
 * rules rather than shape checks: every entry must carry readable text and a
 * non-colour glyph, the entry set must be exactly the six frozen statuses with
 * no decorative seventh, every layer must get a legend, and an unrecognised
 * status must fail closed the same way `filters.ts` refuses it.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = new URL("../../", import.meta.url);
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-layers-legend-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Spawn tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/layers/legend.ts",
    "src/layers/registry.ts",
    "--target", "ES2022",
    "--module", "NodeNext",
    "--moduleResolution", "NodeNext",
    "--outDir", outputDirectory,
  ],
  { cwd: fileURLToPath(webRoot), stdio: "inherit" },
);

const { STATUS_LEGEND, legendForLayer, legendsForLayers, UNKNOWN_STATUS_GLYPH } = await import(
  pathToFileURL(join(outputDirectory, "layers", "legend.js")).href
);
const { LAYER_REGISTRY, buildRegistrySnapshots, snapshotOf } = await import(
  pathToFileURL(join(outputDirectory, "layers", "registry.js")).href
);

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
  assert.equal(legend.unrecognized, false);
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
