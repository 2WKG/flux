// The fixture is the captured `/interactive/redundancy` payload
// (`src/contracts/interactive-payloads.json`), produced by running
// `siting.redundancy.score_redundancy`.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
const outputDirectory = mkdtempSync(join(webRoot, ".tmp-redundancy-panel-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/data/transport.ts", "src/data/validation.ts", "src/data/client-state.ts", "src/data/interactive-client.ts",
  "src/failure-states/types.ts", "src/failure-states/adapters.ts", "src/failure-states/FailureState.tsx", "src/interactive/RedundancyPanel.tsx",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--jsx", "react-jsx", "--outDir", outputDirectory,
], { cwd: webRoot, stdio: "inherit" });
writeFileSync(join(outputDirectory, "package.json"), '{"type":"commonjs"}');
const { RedundancyPanel } = await import(pathToFileURL(join(outputDirectory, "interactive", "RedundancyPanel.js")).href);
const { toRedundancyView } = await import(pathToFileURL(join(outputDirectory, "data", "interactive-client.js")).href);
const { SYNTHETIC_TOPOLOGY_LABEL } = await import(pathToFileURL(join(outputDirectory, "scene", "minnesota-adapter.js")).href);

const captured = JSON.parse(readFileSync(new URL("../contracts/interactive-payloads.json", import.meta.url), "utf8"))
  .routes["/interactive/redundancy"].response;

const render = (payload) =>
  renderToStaticMarkup(createElement(RedundancyPanel, { state: { kind: "ready", data: toRedundancyView(payload) } }));
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Rendered text only: an attribute the user never sees is not a disclosure. */
const textOf = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

const number = (value) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);

test("the score is the server's, formatted, and never recomputed from components", () => {
  const markup = render(captured);
  const components = captured.components;
  // The score the review's probe computed in the browser.
  const browserWouldCompute = 0.5 * components.n_minus_one_survivability + 0.3 * components.edge_disjoint_path_score;
  assert.notEqual(number(browserWouldCompute), number(captured.score), "the probe must be able to tell the two states apart");
  assert.match(markup, new RegExp(`data-redundancy-score="true">${escape(number(captured.score))}`));
  assert.doesNotMatch(markup, new RegExp(`data-redundancy-score="true">${escape(number(browserWouldCompute))}`));
});

test("the synthetic topology disclosure is rendered from the server's flag", () => {
  const markup = render(captured);
  assert.equal(captured.evidence.synthetic_topology, true);
  // The token itself must reach the *user*, not merely an attribute: a chip that
  // says only "Synthetic" leaves the ACTIVSg2000 disclosure unsaid.
  assert.match(textOf(markup), new RegExp(escape(SYNTHETIC_TOPOLOGY_LABEL)));
  assert.match(markup, new RegExp(`data-redundancy-topology="${escape(SYNTHETIC_TOPOLOGY_LABEL)}"`));
  assert.match(markup, /data-redundancy-truth="synthetic"/);
});

test("a server that asserts no synthetic topology gets no topology claim", () => {
  const markup = render({
    ...captured,
    synthetic_topology: false,
    evidence: { ...captured.evidence, synthetic_topology: false },
  });
  assert.doesNotMatch(markup, new RegExp(escape(SYNTHETIC_TOPOLOGY_LABEL)));
  assert.doesNotMatch(textOf(markup), new RegExp(escape(SYNTHETIC_TOPOLOGY_LABEL)));
  assert.match(markup, /data-redundancy-truth="unavailable"/);
  assert.match(markup, /asserts no topology/);
  assert.doesNotMatch(markup, /Source-supported|Source-screened/);
});

test("the server's own evidence fields are shown, not summarised away", () => {
  const markup = render(captured);
  for (const value of [
    captured.evidence.status,
    captured.evidence.branch_selection,
    captured.evidence.persistence,
    captured.evidence.cascade,
    captured.worst_contingency.branch_id,
  ]) {
    assert.match(markup, new RegExp(escape(String(value))));
  }
});

test("a failure state renders a named refusal and no screening number", () => {
  const markup = renderToStaticMarkup(createElement(RedundancyPanel, {
    state: { kind: "unavailable", source: "server", message: "Redundancy endpoint is not deployed.", retryAfterSeconds: null, requestId: "request-2" },
  }));
  assert.match(markup, /Redundancy endpoint is not deployed/);
  assert.doesNotMatch(markup, /Reachability screening/);
});
