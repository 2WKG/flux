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
      import { App } from "./src/pages/MainPage";
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
    "layer controls": /class="layer-controls"/,
    "layer status legend": /aria-label="Layer status legend"/,
    "Texas topology workspace": /aria-label="Full synthetic Texas topology workspace"/,
    "Texas model mount": /class="map scene-viewport"/,
    "named model-route fallback": /Texas model topology unavailable/,
  };
  const missing = Object.entries(mounted).filter(([, pattern]) => !pattern.test(markup)).map(([name]) => name);
  assert.deepEqual(missing, [], `not mounted in App: ${missing.join(", ")}`);
});

test("the default composition mounts the Texas model surface without a five-bus inspector rail", () => {
  // The full network is the primary surface. The old scenario inspector and
  // physical-inventory panel remain separate components for their own routes,
  // but neither may displace the model viewport on the default route.
  assert.match(markup, /<section class="workspace model-workspace" aria-label="Full synthetic Texas topology workspace">/);
  assert.match(markup, /class="map scene-viewport"/);
  assert.match(markup, /Texas model topology unavailable/);
  assert.doesNotMatch(markup, /class="asset-inspector"|aria-label="Scenario inspector"|Source-backed physical inventory/);
});

test("the composed shell publishes the machine provenance token, not prose", () => {
  assert.match(markup, /<main data-source-status="synthetic">/);
});

test("every layer renders unavailable with a named producer reason before any route answers", () => {
  // The first render has asked for nothing yet, so nothing may be shown as
  // available. `buildRegistrySnapshots({})` is the honest state and the rows
  // must show it: six rows, every one `unavailable`, every one with a reason.
  const rows = [...markup.matchAll(/<li class="layer-row"[^>]*data-status="([^"]*)"/g)].map((match) => match[1]);
  assert.equal(rows.length, app.LAYER_REGISTRY.length, "one row per registered layer");
  assert.deepEqual([...new Set(rows)], ["unavailable"], "no layer may be available before a route answered");
  const reasons = [...markup.matchAll(/class="layer-reason" role="note">([^<]*)</g)].map((match) => match[1]);
  assert.equal(reasons.length, app.LAYER_REGISTRY.length, "every unavailable layer must carry the producer's reason");
  for (const reason of reasons) assert.ok(reason.trim().length > 0);
});

test("the composed screen renders no status label but the ones its data supports", () => {
  // The synthetic fixture and six unavailable layers produce two of the six
  // display strings. The mounted scenario edit composer (2WKG-440) adds exactly
  // one more: an edit a user composes is a proposal, and `hypothetical` is the
  // IA's token for a proposal (`docs/design/texas-demo-narrative-ia.md`, the
  // truth-label table). It is rendered from `STATUS_COPY`, not written here.
  // The set stays exact, so relabelling any surface still introduces a fourth
  // and fails.
  const shown = Object.entries(app.STATUS_COPY)
    .filter(([, label]) => new RegExp(`(^| )${label}( |$|\\.)`).test(text))
    .map(([token]) => token)
    .sort();
  assert.deepEqual(shown, ["hypothetical", "synthetic", "unavailable"].sort());
  // And the three that would be claims this screen cannot make stay absent.
  for (const token of ["source_supported", "source_screened", "request_failed"]) {
    assert.ok(!shown.includes(token), `the composed screen renders ${token}`);
  }
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

test("the filter's suppressed half is rendered: no layer disappears without its reason", () => {
  // `applyFilters` (spec §C.2) is the module that guarantees a filtered-out
  // layer is still disclosed. It was compiled into the bundle but had no
  // importer, so the guarantee had no renderer. On the first paint nothing is
  // in the visible set, so every registered layer is suppressed and every one
  // must appear here carrying its own producer reason -- unmount the panel, or
  // render `visible` without `suppressed`, and this goes red.
  assert.match(markup, /aria-label="Hidden layer disclosures"/, "the suppression disclosure must be mounted");
  const disclosed = [...markup.matchAll(/<li class="layer-suppression">(.*?)<\/li>/g)].map((match) => match[1]);
  assert.equal(disclosed.length, app.LAYER_REGISTRY.length, "one disclosure per suppressed layer");
  for (const entry of disclosed) {
    const plain = entry.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    assert.match(plain, /Cause: manual_toggle\.$/, "each disclosure names why the layer was suppressed");
    assert.ok(plain.length > 40, `a disclosure must carry the producer's reason, not just a label: ${plain}`);
  }
  // The count claim is the filter's own, not a restated constant.
  assert.match(text, new RegExp(`${app.LAYER_REGISTRY.length} of ${app.LAYER_REGISTRY.length} layers are not shown`));
});
