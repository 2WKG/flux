import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Renderer-level tests for the five artifact panels against the wire shapes in
// copilot/tools/schemas.py (mirrored in ./copilot-contracts.ts).  Each panel is
// exercised in every ClientState kind (loading, ready, empty, unavailable,
// invalid, failed) and in the panel-owned branches that carry product risk:
// tool-level unavailable code/reason, empty lists, null numerics, provenance
// and the heuristic caveat.  Every assertion is one a fabricated default, a
// silent empty list, a dropped provenance line or a swapped state message fails.

const thisDirectory = dirname(fileURLToPath(import.meta.url));
const webDirectory = fileURLToPath(new URL("../..", import.meta.url));
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-panel-states-"));
const entrypoint = join(outputDirectory, "panel-exports.ts");
const bundle = join(outputDirectory, "panel-exports.mjs");

process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));

writeFileSync(entrypoint, [
  `export { CandidateSitePanel } from ${JSON.stringify(join(thisDirectory, "CandidateSitePanel.tsx"))};`,
  `export { CascadeCriticalPanel } from ${JSON.stringify(join(thisDirectory, "CascadeCriticalPanel.tsx"))};`,
  `export { InterventionComparisonPanel } from ${JSON.stringify(join(thisDirectory, "InterventionComparisonPanel.tsx"))};`,
  `export { LineRankingPanel } from ${JSON.stringify(join(thisDirectory, "LineRankingPanel.tsx"))};`,
  `export { PredictionPanel } from ${JSON.stringify(join(thisDirectory, "PredictionPanel.tsx"))};`,
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

const panels = await import(pathToFileURL(bundle).href);

/** Render and capture React's console.error output (missing/duplicate key warnings land there). */
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
const includesAll = (markup, expected) => { for (const text of expected) assert.ok(markup.includes(text), `expected markup to include ${JSON.stringify(text)}\n${markup}`); };
const includesNone = (markup, forbidden) => { for (const text of forbidden) assert.ok(!markup.includes(text), `expected markup NOT to include ${JSON.stringify(text)}\n${markup}`); };

// Messages owned by web/src/data (kept verbatim; the panels echo ClientState.message).
const NETWORK_FAILURE_MESSAGE = "Unable to reach the service. Check your connection and try again.";
const MALFORMED_RESPONSE_MESSAGE = "The service returned an invalid response. Try again.";
const VERSION_MISMATCH_MESSAGE = "The service returned an incompatible response. Refresh and try again.";
// Messages owned by the panels.
const LOADING_MESSAGE = "Loading artifact…";
const EMPTY_MESSAGE = "No artifact rows are available.";
const NO_PROVENANCE_MESSAGE = "Source: no artifact provenance returned.";
const HEURISTIC_CAVEAT = "Heuristic result: not a learned-model estimate.";

const fixtureRef = { source_kind: "fixture", artifact_id: "fixture-001", artifact_version: "v1", source_ref: "fixtures/panel-contract.json" };
const heuristicRef = { source_kind: "heuristic", artifact_id: "heur-001", artifact_version: "v3", source_ref: "twin/proxy" };
const PROVENANCE_LINE = "fixture · fixture-001 · v1 · fixtures/panel-contract.json";
const HEURISTIC_LINE = "heuristic · heur-001 · v3 · twin/proxy";
const provenance = [fixtureRef];
const available = { status: "available", unavailable: null, provenance };
const unavailableResult = (code, reason) => ({ status: "unavailable", provenance: [], unavailable: { code, reason, retryable: false } });

const line = (overrides = {}) => ({
  line_id: "line-7", from_bus: "bus-a", to_bus: "bus-b", kv: 345, congestion_usd_yr: 200000,
  uplift_mw: 75, cost_usd: 500000, mw_per_musd: 150, ferc_screen_pass: true, spark_eligible: false, ...overrides,
});
const intervention = (overrides = {}) => ({
  intervention_id: "site:site-1", kind: "site", run_id: "uri-run-1", lol_reduction_mwh: 42,
  customer_hours_avoided: 88, critical_loads_protected: ["hospital-1", "water-2"], ...overrides,
});
const element = (overrides = {}) => ({ element_id: "line-7", kind: "line", lost_load_mw: 33, critical_loads_lost: ["hospital-1"], runs: 2, ...overrides });

/**
 * Per-panel contract table.
 *  ready:      a fully populated wire payload
 *  expected:   labelled field renderings that must appear verbatim
 *  nulls:      the same payload with every numeric the panel renders set to null/undefined
 *  nullLabels: the labelled "unavailable" renderings that must then appear
 *  fabricated: the fabricated-default renderings that must NOT appear for that null payload
 *  zero:       one numeric set to 0, and the rendering proving 0 is shown as 0 (not swallowed as unavailable)
 *  dataLabel:  a label that appears only in the data branch (must be absent in the tool-level unavailable branch)
 */
const panelCases = [
  {
    name: "candidate site",
    Panel: panels.CandidateSitePanel,
    ready: {
      ...available, site_id: "site-1", name: "Cedar Station", kind: "coal_retired", county_fips: "48453", scenario_id: "uri_2021",
      unit_mw: 300, safety_score: 91, safety_flags: ["outside floodplain"], grid_value_score: 72,
      lol_reduction_mwh: 420, congestion_relief_pct: 14, blackstart_reach_mw: 50,
      critical_loads_protected: ["hospital-1"], regulatory_path: "fixture path",
    },
    expected: ["<h2>Cedar Station</h2>", "Scenario: uri_2021", "Unit: 300 MW", "Safety score: 91", "Grid value score: 72", "Loss-of-load reduction: 420 MWh", "Protected critical loads: 1"],
    nulls: { safety_score: null, grid_value_score: undefined, lol_reduction_mwh: null, unit_mw: null, critical_loads_protected: null },
    nullLabels: ["Safety score: unavailable", "Grid value score: unavailable", "Loss-of-load reduction: unavailable", "Unit: unavailable", "Protected critical loads: unavailable"],
    fabricated: ["Safety score: 0", "Safety score: </p>", "Grid value score: 0", "Grid value score: </p>", "Loss-of-load reduction: 0", "Loss-of-load reduction: </p>", "Loss-of-load reduction:  MWh", "Unit:  MW", "Unit: 0"],
    zero: { overrides: { safety_score: 0 }, expected: "Safety score: 0</p>" },
    dataLabel: "Safety score:",
  },
  {
    name: "prediction",
    Panel: panels.PredictionPanel,
    ready: {
      ...available, county_fips: "48453", county_name: "Travis", scenario_id: "uri_2021", horizon_h: 72,
      peak_p_out: 0.44, peak_ts: "2021-02-16T19:00:00Z", customers_at_risk: 1200, driver: "wind",
      series: [{ ts: "2021-02-16T19:00:00Z", p_out: 0.44, customers_at_risk: 1200 }],
    },
    expected: ["<h2>Outage prediction</h2>", "Scenario: uri_2021", "County: 48453 (Travis)", "Peak probability: 0.44", "Peak time: 2021-02-16T19:00:00Z", "Customers at risk: 1200", "Driver: wind", "Series points: 1"],
    nulls: { peak_p_out: null, customers_at_risk: undefined, series: null },
    nullLabels: ["Peak probability: unavailable", "Customers at risk: unavailable", "Series points: unavailable"],
    fabricated: ["Peak probability: 0", "Peak probability: </p>", "Customers at risk: 0", "Customers at risk: </p>", "Series points: 0"],
    zero: { overrides: { peak_p_out: 0 }, expected: "Peak probability: 0</p>" },
    dataLabel: "Peak probability:",
  },
  {
    name: "line ranking",
    Panel: panels.LineRankingPanel,
    ready: { ...available, region: "ERCOT", tech: "dlr", lines: [line(), line({ line_id: "line-8", mw_per_musd: 90, uplift_mw: 40, ferc_screen_pass: false })] },
    expected: ["<h2>Line ranking</h2>", "Region: ERCOT · Technology: dlr", "line-7: 150 MW/$M · 75 MW uplift · 345 kV · FERC screen passed", "line-8: 90 MW/$M · 40 MW uplift · 345 kV · FERC screen not passed"],
    nulls: { lines: [line({ mw_per_musd: null, uplift_mw: undefined, kv: null })] },
    nullLabels: ["line-7: unavailable · unavailable · unavailable · FERC screen passed"],
    fabricated: ["line-7: 0", "line-7:  ", " · 0 MW uplift", " ·  MW uplift"],
    zero: { overrides: { lines: [line({ mw_per_musd: 0 })] }, expected: "line-7: 0 MW/$M" },
    dataLabel: "Region:",
  },
  {
    name: "intervention comparison",
    Panel: panels.InterventionComparisonPanel,
    ready: {
      ...available, scenario_id: "uri_2021", baseline_run_id: "uri-baseline",
      interventions: [intervention(), intervention({ intervention_id: "line:line-7", kind: "line", run_id: "uri-run-2", lol_reduction_mwh: 7, customer_hours_avoided: 12, critical_loads_protected: [] })],
      assumptions: ["stress hours only", "seed 0 baseline reused"],
    },
    expected: [
      "<h2>Intervention comparison</h2>", "Scenario: uri_2021", "Baseline run: uri-baseline",
      "site:site-1 (site, run uri-run-1): 42 MWh loss-of-load reduction · 88 customer-hours avoided · 2 critical loads protected",
      "line:line-7 (line, run uri-run-2): 7 MWh loss-of-load reduction · 12 customer-hours avoided · 0 critical loads protected",
      "<p>Assumptions:</p>", "<li>stress hours only</li>", "<li>seed 0 baseline reused</li>",
    ],
    nulls: { interventions: [intervention({ lol_reduction_mwh: null, customer_hours_avoided: undefined, critical_loads_protected: null })] },
    nullLabels: ["site:site-1 (site, run uri-run-1): unavailable · unavailable · unavailable critical loads protected"],
    fabricated: [": 0 MWh", ":  MWh", " · 0 customer-hours", " ·  customer-hours", " · 0 critical loads"],
    zero: { overrides: { interventions: [intervention({ lol_reduction_mwh: 0 })] }, expected: ": 0 MWh loss-of-load reduction" },
    dataLabel: "Baseline run:",
  },
  {
    name: "cascade critical",
    Panel: panels.CascadeCriticalPanel,
    ready: { ...available, region: "ERCOT", n: 10, scenario_ids: ["uri_2021"], partial: true, elements: [element(), element({ element_id: "bus-3", kind: "bus", lost_load_mw: 5, runs: 1 })] },
    expected: ["<h2>Cascade and critical elements</h2>", "Scenarios: uri_2021", "Requested elements: 10 (partial results)", "line-7 (line): 33 MW lost load · 2 runs", "bus-3 (bus): 5 MW lost load · 1 runs"],
    nulls: { n: null, elements: [element({ lost_load_mw: null, runs: undefined })] },
    nullLabels: ["Requested elements: unavailable (partial results)", "line-7 (line): unavailable · unavailable"],
    fabricated: ["Requested elements: 0", "Requested elements:  (", "line-7 (line): 0", "line-7 (line):  MW", " · 0 runs", " ·  runs"],
    zero: { overrides: { elements: [element({ lost_load_mw: 0 })] }, expected: "line-7 (line): 0 MW lost load" },
    dataLabel: "Scenarios:",
  },
];

for (const { name, Panel, ready: data, expected, nulls, nullLabels, fabricated, zero, dataLabel } of panelCases) {
  // ---- shared ClientState kinds: each panel must forward the state and render distinct text per kind ----
  test(`${name} panel renders its loading state`, () => {
    const { markup } = render(Panel, { kind: "loading" });
    includesAll(markup, ["<strong>loading</strong>", LOADING_MESSAGE]);
    includesNone(markup, [dataLabel, "<strong>failed</strong>", "<strong>ready</strong>"]);
  });

  test(`${name} panel renders its empty state`, () => {
    const { markup } = render(Panel, { kind: "empty" });
    includesAll(markup, ["<strong>empty</strong>", EMPTY_MESSAGE]);
    includesNone(markup, [LOADING_MESSAGE, dataLabel]);
  });

  test(`${name} panel renders its unavailable state with the server message and retry hint`, () => {
    const { markup } = render(Panel, { kind: "unavailable", source: "server", message: "Artifact is not available.", retryAfterSeconds: 30, requestId: "request-1" });
    includesAll(markup, ["<strong>unavailable</strong>", "Artifact is not available."]);
    includesNone(markup, [LOADING_MESSAGE, dataLabel]);
  });

  test(`${name} panel renders its invalid state with the validator's message`, () => {
    for (const [reason, message] of [["malformed_response", MALFORMED_RESPONSE_MESSAGE], ["version_mismatch", VERSION_MISMATCH_MESSAGE]]) {
      const { markup } = render(Panel, { kind: "invalid", reason, message });
      includesAll(markup, ["<strong>invalid</strong>", message]);
      includesNone(markup, [LOADING_MESSAGE, dataLabel]);
    }
  });

  test(`${name} panel renders its failed state, never as loading`, () => {
    const network = render(Panel, { kind: "failed", source: "network", message: NETWORK_FAILURE_MESSAGE }).markup;
    includesAll(network, ["<strong>failed</strong>", NETWORK_FAILURE_MESSAGE]);
    includesNone(network, [LOADING_MESSAGE, "<strong>loading</strong>", dataLabel]);
    const server = render(Panel, { kind: "failed", source: "server", message: "Upstream solver crashed.", requestId: "request-2" }).markup;
    includesAll(server, ["<strong>failed</strong>", "Upstream solver crashed."]);
    includesNone(server, [LOADING_MESSAGE, dataLabel]);
  });

  // ---- panel-owned ready branches ----
  test(`${name} panel renders its data state with labelled fields, units and provenance`, () => {
    const { markup, warnings } = render(Panel, ready(data));
    includesAll(markup, [...expected, PROVENANCE_LINE]);
    includesNone(markup, [LOADING_MESSAGE, HEURISTIC_CAVEAT, NO_PROVENANCE_MESSAGE]);
    assert.deepEqual(warnings, [], `React warned while rendering ${name} (missing or duplicate keys?)`);
  });

  test(`${name} panel renders a null or missing numeric as unavailable, never as 0 or blank`, () => {
    const { markup } = render(Panel, ready({ ...data, ...nulls }));
    includesAll(markup, [...nullLabels, PROVENANCE_LINE]);
    includesNone(markup, fabricated);
  });

  test(`${name} panel renders a genuine 0 as 0`, () => {
    const { markup } = render(Panel, ready({ ...data, ...zero.overrides }));
    includesAll(markup, [zero.expected]);
  });

  test(`${name} panel renders the tool-level unavailable code and reason instead of a data view`, () => {
    const { markup } = render(Panel, ready(unavailableResult("unsupported_request", "This scenario has no supported artifact.")));
    includesAll(markup, ["unsupported_request: This scenario has no supported artifact.", NO_PROVENANCE_MESSAGE]);
    includesNone(markup, [dataLabel, LOADING_MESSAGE, "<strong>unavailable</strong>", PROVENANCE_LINE]);
    const withProvenance = render(Panel, ready({ ...unavailableResult("artifact_unavailable", "No persisted rows."), provenance })).markup;
    includesAll(withProvenance, ["artifact_unavailable: No persisted rows.", PROVENANCE_LINE]);
  });

  test(`${name} panel labels an empty provenance list instead of inventing a source`, () => {
    const { markup } = render(Panel, ready({ ...data, provenance: [] }));
    includesAll(markup, [NO_PROVENANCE_MESSAGE]);
    includesNone(markup, ["fixture", "Source: fixture", HEURISTIC_CAVEAT]);
  });

  test(`${name} panel shows the heuristic caveat only when a provenance source is heuristic`, () => {
    const heuristic = render(Panel, ready({ ...data, provenance: [fixtureRef, heuristicRef] })).markup;
    includesAll(heuristic, [HEURISTIC_CAVEAT, PROVENANCE_LINE, HEURISTIC_LINE]);
    const learned = render(Panel, ready({ ...data, provenance: [{ ...fixtureRef, source_kind: "observed" }] })).markup;
    includesNone(learned, [HEURISTIC_CAVEAT]);
  });
}

// ---- list panels: explicit empty-list messages (a bare <ul></ul> is a silent empty state) ----

test("line ranking with an empty lines array explains that nothing was returned", () => {
  const { markup } = render(panels.LineRankingPanel, ready({ ...panelCases[2].ready, lines: [] }));
  includesAll(markup, ["No ranked lines were returned by the server.", "Region: ERCOT · Technology: dlr", PROVENANCE_LINE]);
  includesNone(markup, ["<li>line-", "<ul></ul>"]);
});

test("intervention comparison with no interventions explains that nothing was returned", () => {
  const { markup } = render(panels.InterventionComparisonPanel, ready({ ...panelCases[3].ready, interventions: [] }));
  includesAll(markup, ["No interventions were returned by the server.", "Baseline run: uri-baseline", PROVENANCE_LINE]);
  includesNone(markup, ["loss-of-load reduction", "<ul></ul>"]);
});

test("intervention comparison with no assumptions says so instead of omitting the caveat line", () => {
  const { markup } = render(panels.InterventionComparisonPanel, ready({ ...panelCases[3].ready, assumptions: [] }));
  includesAll(markup, ["Assumptions: none were returned by the server."]);
  includesNone(markup, ["<p>Assumptions:</p>"]);
});

test("cascade critical with no elements explains that nothing was returned", () => {
  const { markup } = render(panels.CascadeCriticalPanel, ready({ ...panelCases[4].ready, elements: [], partial: false }));
  includesAll(markup, ["No critical elements were returned by the server.", "Requested elements: 10</p>", PROVENANCE_LINE]);
  includesNone(markup, ["(partial results)", "<ul></ul>", "MW lost load"]);
});

test("cascade critical marks partial results only when the wire says so", () => {
  const partial = render(panels.CascadeCriticalPanel, ready(panelCases[4].ready)).markup;
  includesAll(partial, ["Requested elements: 10 (partial results)"]);
  const complete = render(panels.CascadeCriticalPanel, ready({ ...panelCases[4].ready, partial: false })).markup;
  includesAll(complete, ["Requested elements: 10</p>"]);
  includesNone(complete, ["(partial results)"]);
});

test("cascade critical panel exposes the wire unavailable code and reason for an unsupported scenario", () => {
  const { markup } = render(panels.CascadeCriticalPanel, ready(unavailableResult("unsupported_request", "This scenario has no supported cascade artifact.")));
  includesAll(markup, ["<h2>Cascade and critical elements</h2>", "unsupported_request: This scenario has no supported cascade artifact.", NO_PROVENANCE_MESSAGE]);
  includesNone(markup, ["Scenarios:", "Requested elements:", LOADING_MESSAGE]);
});

test("cascade critical panel exposes the wire unavailable code and reason", () => {
  const { markup } = render(panels.CascadeCriticalPanel, ready(unavailableResult("artifact_unavailable", "No persisted cascade runs.")));
  includesAll(markup, ["artifact_unavailable: No persisted cascade runs."]);
});

// ---- React keys: two rows per list panel must render without a key warning ----

test("list panels render multiple rows without React key warnings", () => {
  for (const [Panel, data] of [
    [panels.LineRankingPanel, panelCases[2].ready],
    [panels.InterventionComparisonPanel, panelCases[3].ready],
    [panels.CascadeCriticalPanel, panelCases[4].ready],
  ]) {
    const { warnings } = render(Panel, ready({ ...data, provenance: [fixtureRef, heuristicRef] }));
    assert.deepEqual(warnings, []);
  }
});
