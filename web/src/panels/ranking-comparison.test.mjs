import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Behavioural tests for the two ranking/comparison panels, rendered against
// the wire shapes in copilot/tools/schemas.py (LinesData, InterventionsData,
// UnavailableOutput).  Every assertion here is one a fabricated default, a
// silent empty list, or a dropped provenance line would fail.

const thisDirectory = dirname(fileURLToPath(import.meta.url));
const webDirectory = fileURLToPath(new URL("../..", import.meta.url));
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-ranking-comparison-"));
const entrypoint = join(outputDirectory, "panel-exports.ts");
const bundle = join(outputDirectory, "panel-exports.mjs");

process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));

writeFileSync(entrypoint, [
  `export { InterventionComparisonPanel } from ${JSON.stringify(join(thisDirectory, "InterventionComparisonPanel.tsx"))};`,
  `export { LineRankingPanel } from ${JSON.stringify(join(thisDirectory, "LineRankingPanel.tsx"))};`,
].join("\n"));

await build({
  absWorkingDir: webDirectory,
  bundle: true,
  entryPoints: [entrypoint],
  format: "esm",
  outfile: bundle,
  platform: "node",
  target: "node20",
});

const { InterventionComparisonPanel, LineRankingPanel } = await import(pathToFileURL(bundle).href);

/** Render and also capture React's console.error output (duplicate/missing key warnings land there). */
function render(Panel, state) {
  const warnings = [];
  const original = console.error;
  console.error = (...args) => warnings.push(args.map(String).join(" "));
  try {
    return { markup: renderToStaticMarkup(React.createElement(Panel, { state })), warnings };
  } finally {
    console.error = original;
  }
}
const ready = (data) => ({ kind: "ready", data });

const fixtureRef = { source_kind: "fixture", artifact_id: "fixture-001", artifact_version: "v1", source_ref: "fixtures/panel-contract.json" };
const heuristicRef = { source_kind: "heuristic", artifact_id: "heur-001", artifact_version: "v3", source_ref: "twin/proxy" };
const PROVENANCE_LINE = "fixture · fixture-001 · v1 · fixtures/panel-contract.json";
const HEURISTIC_CAVEAT = "Heuristic result: not a learned-model estimate.";

const line = (overrides = {}) => ({
  line_id: "line-7", from_bus: "bus-a", to_bus: "bus-b", kv: 345, congestion_usd_yr: 200000,
  uplift_mw: 75, cost_usd: 500000, mw_per_musd: 150, ferc_screen_pass: true, spark_eligible: false,
  ...overrides,
});
const linesData = (overrides = {}) => ({
  status: "available", unavailable: null, provenance: [fixtureRef], region: "ERCOT", tech: "dlr",
  lines: [line(), line({ line_id: "line-8", mw_per_musd: 90, uplift_mw: 40, ferc_screen_pass: false })],
  ...overrides,
});

const intervention = (overrides = {}) => ({
  intervention_id: "site:site-1", kind: "site", run_id: "uri-run-1", lol_reduction_mwh: 42,
  customer_hours_avoided: 88, critical_loads_protected: ["hospital-1", "water-2"],
  ...overrides,
});
const interventionsData = (overrides = {}) => ({
  status: "available", unavailable: null, provenance: [fixtureRef],
  scenario_id: "uri_2021", baseline_run_id: "uri-baseline",
  interventions: [intervention(), intervention({ intervention_id: "line:line-7", kind: "line", run_id: "uri-run-2", lol_reduction_mwh: 7, customer_hours_avoided: 12, critical_loads_protected: [] })],
  assumptions: ["stress hours only", "seed 0 baseline reused"],
  ...overrides,
});

const unavailableData = { status: "unavailable", provenance: [], unavailable: { code: "unsupported_request", reason: "Scenario has no persisted ranking.", retryable: false } };

// ---------- LineRankingPanel ----------

test("line ranking renders every wire row with named, unit-labelled metrics and unique keys", () => {
  const { markup, warnings } = render(LineRankingPanel, ready(linesData()));
  assert.ok(markup.includes("Region: ERCOT · Technology: dlr"), markup);
  assert.ok(markup.includes("line-7: 150 MW/$M · 75 MW uplift · 345 kV · FERC screen passed"), markup);
  assert.ok(markup.includes("line-8: 90 MW/$M · 40 MW uplift · 345 kV · FERC screen not passed"), markup);
  assert.ok(markup.includes(PROVENANCE_LINE), markup);
  assert.deepEqual(warnings, [], "React emitted a key warning while rendering two ranked lines");
});

test("line ranking with an empty lines array explains that nothing was returned", () => {
  const { markup } = render(LineRankingPanel, ready(linesData({ lines: [] })));
  assert.ok(markup.includes("No ranked lines were returned by the server."), markup);
  assert.ok(!markup.includes("<li>line-"), `silent empty list rendered: ${markup}`);
  assert.ok(markup.includes(PROVENANCE_LINE), markup);
});

test("line ranking renders a null metric as unavailable, never as 0 or blank", () => {
  const { markup } = render(LineRankingPanel, ready(linesData({ lines: [line({ mw_per_musd: null, uplift_mw: undefined })] })));
  assert.ok(markup.includes("line-7: unavailable · unavailable · 345 kV"), markup);
  assert.ok(!markup.includes("line-7: 0"), `fabricated default rendered: ${markup}`);
  assert.ok(!markup.includes("line-7:  "), `blank metric rendered: ${markup}`);
});

test("line ranking renders a genuine 0 metric as 0", () => {
  const { markup } = render(LineRankingPanel, ready(linesData({ lines: [line({ mw_per_musd: 0 })] })));
  assert.ok(markup.includes("line-7: 0 MW/$M"), markup);
});

test("line ranking exposes the tool-level unavailable code and reason instead of a data view", () => {
  const { markup } = render(LineRankingPanel, ready(unavailableData));
  assert.ok(markup.includes("unsupported_request: Scenario has no persisted ranking."), markup);
  assert.ok(markup.includes("Source: no artifact provenance returned."), markup);
  assert.ok(!markup.includes("Region:"), markup);
  assert.ok(!markup.includes("Loading artifact"), markup);
});

// ---------- InterventionComparisonPanel ----------

test("intervention comparison renders every intervention with A8 metrics, units and the assumptions list", () => {
  const { markup, warnings } = render(InterventionComparisonPanel, ready(interventionsData()));
  assert.ok(markup.includes("Scenario: uri_2021"), markup);
  assert.ok(markup.includes("Baseline run: uri-baseline"), markup);
  assert.ok(markup.includes("site:site-1 (site, run uri-run-1): 42 MWh loss-of-load reduction · 88 customer-hours avoided · 2 critical loads protected"), markup);
  assert.ok(markup.includes("line:line-7 (line, run uri-run-2): 7 MWh loss-of-load reduction · 12 customer-hours avoided · 0 critical loads protected"), markup);
  assert.ok(markup.includes("<li>stress hours only</li>"), markup);
  assert.ok(markup.includes("<li>seed 0 baseline reused</li>"), markup);
  assert.ok(markup.includes(PROVENANCE_LINE), markup);
  assert.deepEqual(warnings, [], "React emitted a key warning while rendering two interventions");
});

test("intervention comparison with no interventions explains that nothing was returned", () => {
  const { markup } = render(InterventionComparisonPanel, ready(interventionsData({ interventions: [] })));
  assert.ok(markup.includes("No interventions were returned by the server."), markup);
  assert.ok(!markup.includes("loss-of-load reduction"), markup);
});

test("intervention comparison with no assumptions says so instead of omitting the caveat line", () => {
  const { markup } = render(InterventionComparisonPanel, ready(interventionsData({ assumptions: [] })));
  assert.ok(markup.includes("Assumptions: none were returned by the server."), markup);
});

test("intervention comparison renders a null metric as unavailable, never as 0 or blank", () => {
  const { markup } = render(InterventionComparisonPanel, ready(interventionsData({ interventions: [intervention({ lol_reduction_mwh: null, customer_hours_avoided: null })] })));
  assert.ok(markup.includes("site:site-1 (site, run uri-run-1): unavailable · unavailable · 2 critical loads protected"), markup);
  assert.ok(!markup.includes(": 0 MWh"), `fabricated default rendered: ${markup}`);
});

test("intervention comparison renders a genuine 0 metric as 0", () => {
  const { markup } = render(InterventionComparisonPanel, ready(interventionsData({ interventions: [intervention({ lol_reduction_mwh: 0 })] })));
  assert.ok(markup.includes(": 0 MWh loss-of-load reduction"), markup);
});

test("intervention comparison exposes the tool-level unavailable code and reason", () => {
  const { markup } = render(InterventionComparisonPanel, ready(unavailableData));
  assert.ok(markup.includes("unsupported_request: Scenario has no persisted ranking."), markup);
  assert.ok(markup.includes("Source: no artifact provenance returned."), markup);
  assert.ok(!markup.includes("Baseline run:"), markup);
});

// ---------- shared: provenance caveat, loading, failed ----------

for (const [name, Panel, data] of [["line ranking", LineRankingPanel, linesData], ["intervention comparison", InterventionComparisonPanel, interventionsData]]) {
  test(`${name} shows the heuristic caveat only when a provenance source is heuristic`, () => {
    const heuristic = render(Panel, ready(data({ provenance: [fixtureRef, heuristicRef] }))).markup;
    assert.ok(heuristic.includes(HEURISTIC_CAVEAT), heuristic);
    assert.ok(heuristic.includes("heuristic · heur-001 · v3 · twin/proxy"), heuristic);
    const learned = render(Panel, ready(data())).markup;
    assert.ok(!learned.includes(HEURISTIC_CAVEAT), learned);
  });

  test(`${name} renders loading and failed states with distinct text`, () => {
    const loading = render(Panel, { kind: "loading" }).markup;
    assert.ok(loading.includes("<strong>loading</strong>"), loading);
    assert.ok(loading.includes("Loading artifact…"), loading);
    const failed = render(Panel, { kind: "failed", source: "network", message: "Unable to reach the service. Check your connection and try again." }).markup;
    assert.ok(failed.includes("<strong>failed</strong>"), failed);
    assert.ok(failed.includes("Unable to reach the service."), failed);
    assert.ok(!failed.includes("Loading artifact"), `failed state rendered as loading: ${failed}`);
  });
}
