/** Tests for the suppression-disclosure salvage from the closed PR #219.
 *
 * Every assertion here is a rule, not a shape check: the six IA glyph names
 * are pinned literally against
 * `docs/design/minnesota-demo-narrative-ia.md:225-230`, an unrecognised status
 * must fail closed, an unreported layer must be unavailable with a named
 * reason, and filtering six unavailable layers to zero visible must still
 * disclose all six.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = new URL("../../", import.meta.url);
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-layers-suppression-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Spawn tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/layers/filters.ts",
    "src/layers/registry.ts",
    "src/layers/status-glyphs.ts",
    "--target", "ES2022",
    "--module", "NodeNext",
    "--moduleResolution", "NodeNext",
    "--outDir", outputDirectory,
  ],
  { cwd: webRoot, stdio: "inherit" },
);

const layersOut = join(outputDirectory, "layers");
const {
  applyFilters,
  noFilters,
  suppressesUncertainty,
  uncertainSuppressions,
  lowerConfidenceStatuses,
  UNRECOGNIZED_STATUS,
} = await import(pathToFileURL(join(layersOut, "filters.js")).href);
const { buildRegistrySnapshots, LAYER_REGISTRY, snapshotOf } = await import(
  pathToFileURL(join(layersOut, "registry.js")).href
);
const { STATUS_GLYPHS, glyphForStatus, UNKNOWN_STATUS_GLYPH } = await import(
  pathToFileURL(join(layersOut, "status-glyphs.js")).href
);
const { ASSET_STATUS_TOKENS } = await import(pathToFileURL(join(outputDirectory, "labels.js")).href);

const snapshot = (overrides) => ({ id: "topology", label: "Topology", status: "source_supported", ...overrides });

// ---------------------------------------------------------------------------
// Vocabulary: imported from ../labels.ts, never restated here.
// ---------------------------------------------------------------------------

test("the salvaged modules key off the six tokens labels.ts owns, restating none of them", () => {
  assert.deepEqual([...ASSET_STATUS_TOKENS].sort(), Object.keys(STATUS_GLYPHS).sort());
  const sources = ["filters.ts", "registry.ts", "status-glyphs.ts"].map((name) =>
    readFileSync(fileURLToPath(new URL(`src/layers/${name}`, webRoot)), "utf8"),
  );
  for (const [index, source] of sources.entries()) {
    assert.match(source, /from "\.\.\/labels\.js"/, `module ${index} must import the vocabulary`);
    // A restated union would list two or more tokens as adjacent literals.
    assert.equal(
      /"source_supported"[\s|,]*\n?\s*\|?\s*"source_screened"/.test(source),
      false,
      `module ${index} must not restate the token union`,
    );
  }
});

// ---------------------------------------------------------------------------
// IA glyph names: the exact strings, pinned to the table row they come from.
// ---------------------------------------------------------------------------

test("each status carries the exact glyph name the IA visual-treatment column names", () => {
  assert.deepEqual(STATUS_GLYPHS, {
    source_supported: "check",
    source_screened: "half-check",
    hypothetical: "arrow",
    synthetic: "dotted-fill",
    unavailable: "blocked",
    request_failed: "error",
  });
  // And the names are actually in the IA table rows they claim (225-230).
  const ia = readFileSync(fileURLToPath(new URL("../docs/design/minnesota-demo-narrative-ia.md", webRoot)), "utf8")
    .split("\n");
  const rows = {
    source_supported: 225,
    source_screened: 226,
    hypothetical: 227,
    synthetic: 228,
    unavailable: 229,
    request_failed: 230,
  };
  for (const [status, line] of Object.entries(rows)) {
    const treatment = ia[line - 1].split("|")[3];
    const expected = STATUS_GLYPHS[status].replace("-", "[ -]");
    assert.match(
      treatment,
      new RegExp(expected),
      `${status}: glyph "${STATUS_GLYPHS[status]}" must appear in the IA visual treatment at line ${line}`,
    );
  }
});

test("a status outside the frozen six resolves to a named refusal glyph, never undefined", () => {
  assert.equal(glyphForStatus("source_backed"), UNKNOWN_STATUS_GLYPH);
  assert.equal(glyphForStatus(undefined), UNKNOWN_STATUS_GLYPH);
  assert.equal(typeof glyphForStatus("illustrative"), "string");
});

// ---------------------------------------------------------------------------
// Registry: an unreported layer is unavailable with a named reason.
// ---------------------------------------------------------------------------

test("a layer whose data is absent renders unavailable with a named reason, never an empty success", () => {
  const snapshots = buildRegistrySnapshots({});
  assert.equal(snapshots.length, LAYER_REGISTRY.length);
  assert.equal(snapshots.length, 6);
  for (const entry of snapshots) {
    assert.equal(entry.status, "unavailable", `${entry.id} must not be reported as available`);
    assert.equal(typeof entry.reason, "string");
    assert.ok(entry.reason.includes(entry.label), "the reason must name the layer it is about");
    assert.ok(entry.reason.length > 0, "unavailable snapshot must carry a named reason");
  }
});

test("a partially-reported registry still reports every layer, the missing ones as unavailable", () => {
  const snapshots = buildRegistrySnapshots({
    provenance: { kind: "available", status: "source_supported" },
    proposals: { kind: "available", status: "hypothetical" },
    flows: { kind: "request_failed", reason: "the flow read failed", requestId: "request-7" },
  });
  const byId = Object.fromEntries(snapshots.map((s) => [s.id, s]));
  assert.equal(byId.provenance.status, "source_supported");
  assert.equal(byId.proposals.status, "hypothetical");
  assert.equal(byId.flows.status, "request_failed");
  assert.equal(byId.flows.requestId, "request-7");
  assert.equal(byId.topology.status, "unavailable");
  assert.equal(byId.facilities.status, "unavailable");
  assert.equal(byId.events.status, "unavailable");
});

// ---------------------------------------------------------------------------
// Filtering never silently erases uncertainty.
// ---------------------------------------------------------------------------

test("nothing is suppressed and nothing is disclosed when no filter is active", () => {
  const result = applyFilters(buildRegistrySnapshots({}), noFilters());
  assert.equal(result.visible.length, 6);
  assert.equal(result.suppressed.length, 0);
  assert.equal(suppressesUncertainty(result), false);
});

test("filtering the full unavailable-by-default registry down to nothing still discloses all six", () => {
  // The sharpest form of the rule: every layer is unavailable (no data wired
  // up yet) and a filter hides all unavailable layers to declutter the view.
  // The visible set collapses to nothing, but the suppressed list must still
  // name every single one -- filtering must never make an entire unavailable
  // registry disappear as if it had succeeded with zero layers.
  const snapshots = buildRegistrySnapshots({});
  const result = applyFilters(snapshots, {
    hiddenLayerIds: new Set(),
    excludedStatuses: new Set(["unavailable"]),
  });

  assert.equal(result.visible.length, 0);
  assert.equal(result.suppressed.length, 6);
  assert.equal(suppressesUncertainty(result), true);
  assert.equal(uncertainSuppressions(result).length, 6);
  assert.deepEqual(
    result.suppressed.map((entry) => entry.layerId).sort(),
    ["events", "facilities", "flows", "proposals", "provenance", "topology"],
  );
  for (const entry of result.suppressed) {
    assert.equal(entry.status, "unavailable");
    assert.ok(entry.reason.length > 0, `${entry.layerId} was hidden with no stated reason`);
  }
});

test("a status filter discloses what it hid, and the layer's own producer reason wins", () => {
  const snapshots = [
    snapshot({ id: "events", label: "Events", status: "unavailable", reason: "no scenario artifact was built" }),
    snapshot({ id: "facilities", label: "Facilities", status: "synthetic" }),
  ];
  const result = applyFilters(snapshots, {
    hiddenLayerIds: new Set(),
    excludedStatuses: new Set(["unavailable", "synthetic"]),
  });
  assert.equal(result.visible.length, 0);
  const byId = Object.fromEntries(result.suppressed.map((entry) => [entry.layerId, entry]));
  // Producer reason verbatim, not replaced by a generic filter label.
  assert.equal(byId.events.reason, "no scenario artifact was built");
  assert.equal(byId.events.cause, "status_filter");
  // No producer reason, so the filter states its own why -- and names the status.
  assert.match(byId.facilities.reason, /synthetic/);
  assert.match(byId.facilities.reason, /status filter/);
});

test("a layer suppressed by both a manual toggle and a status filter is reported once, as manual", () => {
  const snapshots = [snapshot({ id: "events", label: "Events", status: "unavailable", reason: "no scenario artifact" })];
  const result = applyFilters(snapshots, {
    hiddenLayerIds: new Set(["events"]),
    excludedStatuses: new Set(["unavailable"]),
  });
  assert.equal(result.suppressed.length, 1);
  assert.equal(result.suppressed[0].cause, "manual_toggle");
  assert.equal(result.suppressed[0].reason, "no scenario artifact");
});

test("every uncertain status is flagged by suppressesUncertainty when hidden", () => {
  for (const status of ["source_screened", "hypothetical", "synthetic", "unavailable", "request_failed"]) {
    const result = applyFilters([snapshot({ id: "flows", label: "Flows", status })], {
      hiddenLayerIds: new Set(["flows"]),
      excludedStatuses: new Set(),
    });
    assert.equal(suppressesUncertainty(result), true, `status ${status} must be flagged`);
    assert.equal(uncertainSuppressions(result).length, 1);
  }
  const supported = applyFilters([snapshot({ id: "flows", label: "Flows", status: "source_supported" })], {
    hiddenLayerIds: new Set(["flows"]),
    excludedStatuses: new Set(),
  });
  assert.equal(suppressesUncertainty(supported), false);
  assert.equal(lowerConfidenceStatuses().has("source_supported"), false);
});

// ---------------------------------------------------------------------------
// Fail closed: the defect this salvage fixes. #219 passed these through.
// ---------------------------------------------------------------------------

test("an unrecognised status fails closed: never visible, always disclosed, always uncertain", () => {
  const result = applyFilters([snapshot({ id: "topology", label: "Topology", status: "source_backed" })], noFilters());
  assert.equal(result.visible.length, 0, "an unrecognised status must never reach the visible set");
  assert.equal(result.suppressed.length, 1);
  assert.equal(result.suppressed[0].status, "unavailable");
  assert.equal(result.suppressed[0].cause, UNRECOGNIZED_STATUS);
  assert.equal(UNRECOGNIZED_STATUS, "unrecognized_status");
  assert.match(result.suppressed[0].reason, /source_backed/, "the refusal must name the offending value");
  assert.match(result.suppressed[0].reason, /labels\.ts/, "the refusal must name the owning vocabulary");
  assert.equal(suppressesUncertainty(result), true);
});

test("an invented 'illustrative' status cannot pass through applyFilters", () => {
  const result = applyFilters([snapshot({ id: "events", label: "Events", status: "illustrative" })], noFilters());
  assert.equal(result.visible.length, 0);
  assert.equal(result.suppressed[0].cause, UNRECOGNIZED_STATUS);
  assert.equal(glyphForStatus("illustrative"), UNKNOWN_STATUS_GLYPH);
});

test("a snapshot with a missing or non-string status is refused, not defaulted", () => {
  for (const bad of [undefined, null, 42, ""]) {
    const result = applyFilters([snapshot({ status: bad })], noFilters());
    assert.equal(result.visible.length, 0, `status ${String(bad)} must not be shown`);
    assert.equal(result.suppressed[0].cause, UNRECOGNIZED_STATUS);
    assert.equal(result.suppressed[0].status, "unavailable");
  }
});

test("snapshotOf never produces an available snapshot without a status", () => {
  const definition = LAYER_REGISTRY[0];
  assert.equal(snapshotOf(definition, { kind: "unavailable", reason: "not built" }).status, "unavailable");
  assert.equal(snapshotOf(definition, { kind: "request_failed", reason: "boom" }).status, "request_failed");
  assert.equal(snapshotOf(definition, { kind: "available", status: "synthetic" }).status, "synthetic");
});
