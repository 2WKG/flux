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

const provenance = {
  source_kind: "fixture",
  artifact_id: "fixture-001",
  artifact_version: "v1",
};

const panelCases = [
  {
    name: "candidate site",
    Panel: panels.CandidateSitePanel,
    ready: {
      site_id: "site-1", name: "Cedar Station", scenario_id: "uri_2021", status: "ranked",
      safety_score: 91, grid_value_score: 72, provenance,
    },
    expected: ["Cedar Station", "Safety score: 91", "fixture-001"],
  },
  {
    name: "prediction",
    Panel: panels.PredictionPanel,
    ready: {
      county_fips: "48453", scenario_id: "uri_2021", p_out: 0.44, customers_at_risk: 1200,
      driver: "wind", model_kind: "lightgbm", model_version: "2026.09", provenance,
    },
    expected: ["Outage prediction", "County: 48453", "Probability: 0.44"],
  },
  {
    name: "line ranking",
    Panel: panels.LineRankingPanel,
    ready: [{
      line_id: "line-7", scenario_id: "uri_2021", intervention: "dlr", score: 3.1,
      source_class: "observed", provenance,
    }],
    expected: ["Line ranking", "line-7: 3.1", "source observed"],
  },
  {
    name: "intervention comparison",
    Panel: panels.InterventionComparisonPanel,
    ready: {
      scenario_id: "uri_2021", intervention_id: "site:site-1", status: "supported", value: 42,
      source_class: "simulated", provenance,
    },
    expected: ["Intervention comparison", "Intervention: site:site-1", "Value: 42"],
  },
  {
    name: "cascade critical",
    Panel: panels.CascadeCriticalPanel,
    ready: {
      scenario_id: "uri_2021", status: "supported", critical_elements: ["line-7"], provenance,
    },
    expected: ["Cascade and critical elements", "Scenario: uri_2021", "line-7"],
  },
];

for (const { name, Panel, ready, expected } of panelCases) {
  test(`${name} panel renders its data state`, () => {
    const markup = render(Panel, { kind: "ready", data: ready });
    for (const text of expected) assert.match(markup, new RegExp(text));
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
