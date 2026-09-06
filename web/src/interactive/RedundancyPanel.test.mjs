import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const webRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
// Compile inside node_modules so the CommonJS output resolves React through
// the same package tree as the test process.
const outputDirectory = mkdtempSync(join(webRoot, "node_modules", "flux-redundancy-panel-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/data/transport.ts", "src/data/validation.ts", "src/data/client-state.ts", "src/data/interactive-client.ts",
  "src/failure-states/types.ts", "src/failure-states/adapters.ts", "src/failure-states/FailureState.tsx",
  "src/interactive/RedundancyPanel.tsx",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--jsx", "react-jsx", "--outDir", outputDirectory,
], { cwd: webRoot, stdio: "inherit" });
const { RedundancyPanel } = await import(pathToFileURL(join(outputDirectory, "interactive", "RedundancyPanel.js")).href);

const evidenceBackedResponse = {
  busId: "bus-1024", score: 75,
  components: { nMinusOneSurvivability: 80, edgeDisjointPaths: 2, alternativeSourceHops: 3 },
  worstContingency: { branchId: "line:direct", sourceReachable: false },
  evidence: {
    artifactTruth: "synthetic", topology: "synthetic (ACTIVSg2000)",
    provenance: [{ sourceId: "fixture:redundancy", sourceRef: "contract fixture", version: "v1" }],
  },
  assumptions: ["Topology screen only."], limitations: ["No operating conclusion."],
};

test("renders only typed, evidence-backed synthetic bus screening fields", () => {
  const markup = renderToStaticMarkup(createElement(RedundancyPanel, { state: { kind: "ready", data: evidenceBackedResponse } }));
  for (const text of ["Synthetic bus bus-1024", "Reachability screening", "80", "2", "75", "line:direct", "3 graph hops", "fixture:redundancy", "Topology screen only.", "No operating conclusion."]) {
    assert.match(markup, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(markup, /Consumer-site mapping is unavailable/);
  assert.match(markup, /data-redundancy-truth="synthetic"/);
  assert.doesNotMatch(markup, /synthetic \(ACTIVSg2000\)/);
  assert.doesNotMatch(markup, /Incident flow/);
});

test("withholds optional contingency and screening-distance sections when the response does not assert them", () => {
  const markup = renderToStaticMarkup(createElement(RedundancyPanel, {
    state: { kind: "ready", data: { ...evidenceBackedResponse, worstContingency: null, components: { ...evidenceBackedResponse.components, alternativeSourceHops: null } } },
  }));
  assert.match(markup, /Reachability screening/);
  assert.doesNotMatch(markup, /Worst contingency|Screening distance/);
});

test("renders explicit unavailable and malformed response states without bus details", () => {
  const unavailable = renderToStaticMarkup(createElement(RedundancyPanel, {
    state: { kind: "unavailable", source: "server", message: "Redundancy screening has not been mounted.", retryAfterSeconds: null, requestId: "request-447" },
  }));
  assert.match(unavailable, /Unavailable/);
  assert.match(unavailable, /Redundancy screening has not been mounted/);
  assert.doesNotMatch(unavailable, /Synthetic bus/);

  const malformed = renderToStaticMarkup(createElement(RedundancyPanel, {
    state: { kind: "ready", data: { ...evidenceBackedResponse, busId: "" } },
  }));
  assert.match(malformed, /Response could not be used/);
  assert.match(malformed, /did not include a usable synthetic-bus record/);
  assert.doesNotMatch(malformed, /Synthetic bus/);
});
