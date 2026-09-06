/**
 * The one App, composed.
 *
 * `viewport-shell.test.mjs` pins the shell's own layout and vocabulary. It
 * cannot see whether the landed panels are actually mounted in it: the shell
 * passed every one of its assertions while `ChatDock`, `Inspector`,
 * `ResultCards`, `RunTrace`, `FailureState` and `LayerControls` sat unreachable
 * from the entry. This file is the composition's own gate.
 *
 * Every assertion here is over rendered markup or a real function call. The
 * named mutations it must catch, one per test: unmounting any single component,
 * relabelling a status, giving the inspector the shell's own class, dropping the
 * offline fallback, and defaulting an evidence class the producer never sent.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-composed-app.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { App } from "./src/main";
      export { descriptorFor, descriptorsFor, LayerDescriptorRefusal } from "./src/layers/descriptor-adapter";
      export { LAYER_REGISTRY, buildRegistrySnapshots } from "./src/layers/registry";
      export { STATUS_COPY } from "./src/source-truth";
      export const renderApp = () => renderToStaticMarkup(createElement(App));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "composed-app-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic",
  packages: "external", loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const app = await import(compiled.href);

const markup = app.renderApp();
const text = markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

test("every landed panel is mounted in the one App", () => {
  // Each entry is a marker only that component can produce: its own class or
  // its own aria-label. Unmounting any one of them turns this red.
  const mounted = {
    "chat dock": /class="flux-chat"/,
    "chat transcript": /class="flux-chat-transcript"/,
    "result cards": /class="ask-result__empty"|class="ask-results"/,
    "run trace phase": /data-run-phase="idle"/,
    "run trace": /class="run-trace"/,
    "failure state": /class="failure-state"/,
    "inspector": /class="asset-inspector"/,
    "physical inventory panel": /aria-label="Source-backed physical inventory"/,
    "inventory coverage disclosure": /aria-label="Coverage and geometry availability"/,
    "inventory map slot": /class="grid-map"/,
  };
  const missing = Object.entries(mounted).filter(([, pattern]) => !pattern.test(markup)).map(([name]) => name);
  assert.deepEqual(missing, [], `not mounted in App: ${missing.join(", ")}`);
});

test("the inspector is composed in the primary support slot without borrowing the retired shell class", () => {
  const inspectorClasses = [...markup.matchAll(/class="([^"]*)"/g)]
    .map((match) => match[1].split(/\s+/))
    .filter((classes) => classes.includes("inspector"));
  assert.equal(inspectorClasses.length, 0, "the retired shell inspector class must not survive the primary route");
  assert.match(markup, /<aside class="primary-demo__inspector" aria-label="Evidence inspector">/);
  assert.match(markup, /class="asset-inspector"/, "the composed inspector must carry its own class");
});

test("the composed primary route does not label a mixed source surface as a synthetic fixture", () => {
  assert.match(markup, /<main data-source-status="unavailable" data-primary-demo="true">/);
});

test("the primary route puts physical inventory and its source boundary in the spatial stage", () => {
  assert.match(markup, /aria-label="Primary spatial stage"/);
  assert.match(markup, /aria-label="Source-backed physical inventory"/);
  assert.match(markup, /Physical inventory only; electrical model: none/);
});

test("the composed screen renders no status label but the ones its data supports", () => {
  // The synthetic fixture and six unavailable layers can produce exactly two of
  // the six display strings. Relabelling any surface introduces a third.
  const shown = Object.entries(app.STATUS_COPY)
    .filter(([, label]) => new RegExp(`(^| )${label}( |$|\\.)`).test(text))
    .map(([token]) => token)
    .sort();
  assert.deepEqual(shown, ["synthetic", "unavailable"].sort());
});

test("the run trace, when mounted, carries the scene's own status and not the reducer default", () => {
  // `createRunState`'s default source status is `source_supported`. A trace
  // mounted without the scene's status would render a source claim this screen
  // does not have -- which `viewport-shell.test.mjs` also forbids in text.
  for (const match of markup.matchAll(/class="run-trace"[^>]*data-source-status="([^"]*)"/g)) {
    assert.equal(match[1], "synthetic");
  }
  assert.doesNotMatch(text, /Source-supported/);
});

test("descriptorFor refuses rather than defaulting an evidence class the producer never sent", () => {
  const definition = { id: "topology", label: "Topology", description: "" };
  assert.throws(
    () => app.descriptorFor(definition, { id: "topology", label: "Topology", status: "source_supported" }),
    /missing_evidence_disclosure|supplied no evidence disclosure/,
  );
  // The two terminal tokens assert no evidence, so they convert cleanly.
  const unavailable = app.descriptorFor(definition, { id: "topology", label: "Topology", status: "unavailable", reason: "named" });
  assert.equal(unavailable.evidenceClass, "unavailable");
  assert.deepEqual(unavailable.visibility, { enabled: false, reason: "named" });
});

test("descriptorFor asserts the registry id is a layer category instead of assuming it", () => {
  assert.throws(
    () => app.descriptorFor({ id: "topolgy", label: "Topology", description: "" }, { id: "topolgy", label: "Topology", status: "unavailable", reason: "r" }),
    /not one of the six layer categories/,
  );
  // The real registry still converts, so the assertion is not vacuous.
  const snapshots = app.buildRegistrySnapshots({});
  const { layers, refusals } = app.descriptorsFor(app.LAYER_REGISTRY, snapshots);
  assert.equal(layers.length, app.LAYER_REGISTRY.length);
  assert.deepEqual(refusals, []);
});
