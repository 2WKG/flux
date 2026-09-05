import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

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
const render = (Panel, state) => renderToStaticMarkup(React.createElement(Panel, { state }));

const provenance = [{
  source_kind: "fixture",
  artifact_id: "fixture-001",
  artifact_version: "v1",
  source_ref: "fixtures/panel-contract.json",
}];

const panelCases = [
  {
    name: "candidate site",
    Panel: panels.CandidateSitePanel,
    ready: {
      status: "available", unavailable: null, provenance,
      site_id: "site-1", name: "Cedar Station", kind: "coal_retired", county_fips: "48453", scenario_id: "uri_2021",
      unit_mw: 300, safety_score: 91, safety_flags: ["outside floodplain"], grid_value_score: 72,
      lol_reduction_mwh: 420, congestion_relief_pct: 14, blackstart_reach_mw: 50,
      critical_loads_protected: ["hospital-1"], regulatory_path: "fixture path",
    },
    expected: ["Cedar Station", "Unit: 300 MW", "Loss-of-load reduction: 420 MWh", "fixtures/panel-contract.json"],
  },
  {
    name: "prediction",
    Panel: panels.PredictionPanel,
    ready: {
      status: "available", unavailable: null, provenance,
      county_fips: "48453", county_name: "Travis", scenario_id: "uri_2021", horizon_h: 72,
      peak_p_out: 0.44, peak_ts: "2021-02-16T19:00:00Z", customers_at_risk: 1200, driver: "wind",
      series: [{ ts: "2021-02-16T19:00:00Z", p_out: 0.44, customers_at_risk: 1200 }],
    },
    expected: ["Outage prediction", "County: 48453 (Travis)", "Peak probability: 0.44", "Series points: 1"],
  },
  {
    name: "line ranking",
    Panel: panels.LineRankingPanel,
    ready: {
      status: "available", unavailable: null, provenance, region: "ERCOT", tech: "dlr",
      lines: [{
        line_id: "line-7", from_bus: "bus-a", to_bus: "bus-b", kv: 345, congestion_usd_yr: 200000,
        uplift_mw: 75, cost_usd: 500000, mw_per_musd: 150, ferc_screen_pass: true, spark_eligible: false,
      }],
    },
    expected: ["Region: ERCOT · Technology: dlr", "line-7: 150 MW/$M", "75 MW uplift", "FERC screen passed"],
  },
  {
    name: "intervention comparison",
    Panel: panels.InterventionComparisonPanel,
    ready: {
      status: "available", unavailable: null, provenance,
      scenario_id: "uri_2021", baseline_run_id: "uri-baseline",
      interventions: [{
        intervention_id: "site:site-1", kind: "site", run_id: "site-run", lol_reduction_mwh: 42,
        customer_hours_avoided: 88, critical_loads_protected: ["hospital-1", "water-2"],
      }],
      assumptions: ["fixture assumption"],
    },
    expected: ["Baseline run: uri-baseline", "site:site-1 (site): 42 MWh", "88 customer-hours avoided", "2 critical loads protected"],
  },
  {
    name: "cascade critical",
    Panel: panels.CascadeCriticalPanel,
    ready: {
      status: "available", unavailable: null, provenance, region: "ERCOT", n: 10, scenario_ids: ["uri_2021"], partial: true,
      elements: [{ element_id: "line-7", kind: "line", lost_load_mw: 33, critical_loads_lost: ["hospital-1"], runs: 2 }],
    },
    expected: ["Scenarios: uri_2021", "Requested elements: 10 (partial results)", "line-7 (line): 33 MW lost load", "2 runs"],
  },
];

for (const { name, Panel, ready, expected } of panelCases) {
  test(`${name} panel renders its data state`, () => {
    const markup = render(Panel, { kind: "ready", data: ready });
    for (const text of expected) assert.ok(markup.includes(text), `expected panel markup to include ${text}`);
  });

  test(`${name} panel renders its empty state`, () => {
    const markup = render(Panel, { kind: "empty" });
    assert.match(markup, /<strong>empty<\/strong>/);
    assert.match(markup, /No artifact rows are available\./);
  });

  test(`${name} panel renders its unavailable state`, () => {
    const markup = render(Panel, {
      kind: "unavailable", source: "server", message: "Artifact is not available.",
      retryAfterSeconds: 30, requestId: "request-1",
    });
    assert.match(markup, /<strong>unavailable<\/strong>/);
    assert.match(markup, /Artifact is not available\./);
  });

  test(`${name} panel renders its invalid state`, () => {
    const markup = render(Panel, {
      kind: "invalid", reason: "malformed_response", message: "The server returned an invalid response.",
    });
    assert.match(markup, /<strong>invalid<\/strong>/);
    assert.match(markup, /The server returned an invalid response\./);
  });
}

test("cascade critical panel exposes the wire unavailable code and reason", () => {
  const markup = render(panels.CascadeCriticalPanel, {
    kind: "ready",
    data: {
      status: "unavailable",
      provenance: [],
      unavailable: { code: "artifact_unavailable", reason: "No persisted cascade runs.", retryable: false },
    },
  });
  assert.match(markup, /artifact_unavailable: No persisted cascade runs\./);
});
