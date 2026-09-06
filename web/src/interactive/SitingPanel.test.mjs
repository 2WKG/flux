import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";

const sourcePath = fileURLToPath(new URL("./SitingPanel.tsx", import.meta.url));
const compiled = transpileModule(readFileSync(sourcePath, "utf8"), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2020 },
  fileName: sourcePath,
});
const module = { exports: {} };
const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
runInNewContext(compiled.outputText, {
  module,
  exports: module.exports,
  require: (name) => {
    if (name === "react") return react;
    throw new Error(`Unexpected dependency in SitingPanel test: ${name}`);
  },
});
const panel = module.exports;

const fixture = {
  schemaVersion: "siting-search/v1",
  resultKind: "synthetic_counterfactual",
  scenario: {
    id: "winter-stress-fixture",
    label: "Fixture winter stress scenario",
    assumptions: ["Synthetic network topology", "Counterfactual unit availability is supplied by the service"],
  },
  candidates: [{
    id: "fixture-candidate-a",
    label: "Synthetic candidate A",
    evidence: [{ label: "Returned loss-of-load delta", value: "120 MWh", provenanceRef: "counterfactual-run:fixture-a" }],
    limitations: ["This fixture does not represent a physical location."],
    provenance: { artifactId: "fixture-siting-run", artifactVersion: "v1", sourceKind: "test fixture" },
  }],
  limitations: ["This is an illustrative fixture for presentation behavior only."],
};

function renderedText(node) {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(renderedText).join(" ");
  if (!node || typeof node !== "object") return "";
  if (typeof node.type === "function") return renderedText(node.type(node.props));
  return renderedText(node.props?.children);
}

test("a fixture result remains explicitly synthetic and carries scenario, evidence, limitation, and provenance frames", () => {
  const presentation = panel.buildSitingPresentation({ state: "ready", response: fixture });
  assert.equal(presentation.state, "synthetic");
  assert.equal(presentation.response.resultKind, "synthetic_counterfactual");
  assert.equal(presentation.response.scenario.assumptions[0], "Synthetic network topology");
  assert.deepEqual(presentation.response.candidates[0].evidence[0], fixture.candidates[0].evidence[0]);
  assert.match(presentation.response.candidates[0].limitations[0], /does not represent a physical location/i);
  assert.equal(presentation.response.candidates[0].provenance.artifactId, "fixture-siting-run");

  const text = renderedText(panel.SitingPanel({ input: { state: "ready", response: fixture } }));
  assert.match(text, /Synthetic counterfactual screening output/);
  assert.match(text, /not physical siting recommendations/i);
  assert.match(text, /Fixture winter stress scenario/);
  assert.match(text, /Returned loss-of-load delta: 120 MWh/);
  assert.match(text, /counterfactual-run:fixture-a/);
  assert.match(text, /fixture-siting-run \(v1\)/);
});

test("unavailable and malformed inputs have no synthetic-success response", () => {
  const unavailable = panel.buildSitingPresentation({ state: "unavailable", message: "Service disabled for this build." });
  assert.equal(unavailable.state, "unavailable");
  assert.equal(unavailable.message, "Service disabled for this build.");

  const malformed = panel.buildSitingPresentation({ state: "ready", response: { ...fixture, candidates: [{ id: "missing-evidence" }] } });
  assert.equal(malformed.state, "malformed");
  assert.equal("response" in malformed, false);

  const unavailableText = renderedText(panel.SitingPanel({ input: { state: "unavailable" } }));
  const malformedText = renderedText(panel.SitingPanel({ input: { state: "ready", response: { candidates: [] } } }));
  assert.match(unavailableText, /Siting search unavailable/);
  assert.match(malformedText, /Siting response could not be used/);
  assert.doesNotMatch(unavailableText, /Synthetic candidate A/);
  assert.doesNotMatch(malformedText, /Synthetic candidate A/);
});
