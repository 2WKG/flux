import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const webRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const outputDirectory = mkdtempSync(join(webRoot, ".tmp-balance-panel-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/data/transport.ts", "src/data/validation.ts", "src/data/client-state.ts", "src/data/interactive-client.ts",
  "src/failure-states/types.ts", "src/failure-states/adapters.ts", "src/failure-states/FailureState.tsx", "src/interactive/BalancePanel.tsx",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--jsx", "react-jsx", "--outDir", outputDirectory,
], { cwd: webRoot, stdio: "inherit" });
writeFileSync(join(outputDirectory, "package.json"), '{"type":"commonjs"}');
const { BalancePanel } = await import(pathToFileURL(join(outputDirectory, "interactive", "BalancePanel.js")).href);

const response = {
  scenarioId: "mn_peak", editHash: "edit-001", scope: "state",
  servedLoadMw: 150, generationMw: 145, slackMw: 5, residualMw: 0,
  fuelSplitMw: { wind: 35, gas: 110 }, editDelta: [{ metric: "residual_mw", valueMw: -3 }],
  evidence: { artifactTruth: "synthetic", topology: "synthetic (ACTIVSg2000)", capabilityBasis: "nameplate", provenance: [{ sourceId: "fixture:balance", sourceRef: "fixture row" }] },
  assumptions: ["Declared scenario."], limitations: ["No operating conclusion."],
};

test("renders only server-supplied metrics, fuel split, provenance, and caveats", () => {
  const markup = renderToStaticMarkup(createElement(BalancePanel, { state: { kind: "ready", data: response } }));
  for (const text of ["150 MW", "145 MW", "5 MW", "0 MW", "35 MW", "110 MW", "-3 MW", "Synthetic model evidence", "Nameplate accounting", "fixture:balance", "Declared scenario.", "No operating conclusion."]) {
    assert.match(markup, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(markup, /data-balance-truth="synthetic"/);
});

test("renders an explicit unavailable state and no invented grid metric", () => {
  const markup = renderToStaticMarkup(createElement(BalancePanel, {
    state: { kind: "unavailable", source: "server", message: "Balance endpoint is not deployed.", retryAfterSeconds: null, requestId: "request-1" },
  }));
  assert.match(markup, /Unavailable/);
  assert.match(markup, /Balance endpoint is not deployed/);
  assert.doesNotMatch(markup, /Served load|Generation|Slack|Residual/);
});
