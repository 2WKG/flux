// Behavioural tests for the source-truth layer controls.
//
// Nothing here reads the component's source text: the TSX is compiled with esbuild and
// imported, then rendered with `renderToStaticMarkup`, so every assertion is made against
// markup a browser would receive. The same seam is used by web/test/viewport-shell.test.mjs
// and web/test/shell-source-label.test.mjs.
//
// Each assertion below was verified to go RED under a matching mutation of
// src/layers/LayerControls.tsx; the mutations are listed on PR #211.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { build } from "esbuild";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
const run = promisify(execFile);

const ENTRY = `
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LayerControls, resolveLayer, nextVisibleLayerIds, prunedVisibleLayerIds } from "./src/layers/LayerControls";
import { harnessLayers } from "./src/layers/LayerControlsHarness";
export { resolveLayer, nextVisibleLayerIds, prunedVisibleLayerIds, harnessLayers };
export const render = (props) => renderToStaticMarkup(createElement(LayerControls, props));
`;

const outDir = await mkdtemp(path.join(os.tmpdir(), "flux-layer-controls-"));
const outfile = path.join(outDir, "entry.mjs");
await build({
  stdin: { contents: ENTRY, resolveDir: webRoot, loader: "tsx", sourcefile: "layer-controls-render-entry.tsx" },
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  jsx: "automatic",
  absWorkingDir: webRoot,
  tsconfig: path.join(webRoot, "tsconfig.json"),
  // The stylesheet is asserted separately, by parsing it; the node render does not need it.
  loader: { ".css": "empty" },
  // react-dom/server is CJS and dynamically requires node builtins.
  banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
  outfile,
  logLevel: "silent",
});
const mod = await import(pathToFileURL(outfile).href);
process.on("exit", () => { rm(outDir, { recursive: true, force: true }); });

const evidence = {
  source: "Fixture source",
  vintage: "Fixture vintage",
  coverage: "Fixture coverage",
  transformation: "Fixture transformation",
  uncertainty: "Fixture uncertainty",
  syntheticTopologyCaveat: "Fixture topology caveat",
};

const layer = (over) => ({
  id: "l1",
  label: "Layer one",
  category: "flows",
  sourceStatus: "source_supported",
  evidenceClass: "observed",
  evidence,
  visibility: { enabled: true },
  ...over,
});

const renderOne = (over, visibleLayerIds = []) =>
  mod.render({ layers: [layer(over)], visibleLayerIds, onVisibleLayerIdsChange: () => {} });

const textOf = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

// 1. The IA's exact display copy, per token. Relabelling any token fails here.
test("each status renders the IA's exact truth label", () => {
  const expected = {
    source_supported: "Source-supported",
    source_screened: "Source-screened",
    hypothetical: "Hypothetical",
    synthetic: "Synthetic",
    unavailable: "Unavailable",
    request_failed: "Request failed",
  };
  for (const [token, copy] of Object.entries(expected)) {
    const over = token === "unavailable" || token === "request_failed"
      ? { sourceStatus: token, evidence: undefined, visibility: { enabled: false, reason: "Producer reason." } }
      : { sourceStatus: token };
    const markup = renderOne(over);
    assert.match(markup, new RegExp(`data-status="${token}"`), `${token} must carry its own token`);
    assert.ok(textOf(markup).includes(copy), `${token} must render "${copy}"`);
  }
  // The IA hyphenates; the unhyphenated forms are the drift this test exists to catch.
  const screened = textOf(renderOne({ sourceStatus: "source_screened" }));
  assert.ok(!screened.includes("Source supported"), "screened data must never read as source-supported");
  assert.ok(!screened.includes("Source screened"), "the IA copy is hyphenated");
});

// 2. Fail-closed on an unrecognised status, named as a refusal rather than silently relabelled.
test("an unrecognised source status fails closed as Unavailable", () => {
  const markup = renderOne({ sourceStatus: "source_backed" });
  assert.match(markup, /data-status="unavailable"/, "an unknown token must fail closed to unavailable");
  assert.match(markup, /data-refusal="unrecognized_status"/, "the refusal must be named");
  assert.ok(!textOf(markup).includes("Source-supported"), "an unknown token must never present as supported");
  assert.match(markup, /disabled=""/, "a refused layer cannot be requested");
});

// 3. Distinct tokens stay distinct: a failed request is not a missing artifact.
test("request_failed without evidence keeps its own label", () => {
  const markup = renderOne({ sourceStatus: "request_failed", evidence: undefined, visibility: { enabled: false, reason: "Upstream provider returned 503; retry in a minute." } });
  assert.match(markup, /data-status="request_failed"/, "request_failed must not be downgraded to unavailable");
  const text = textOf(markup);
  assert.ok(text.includes("Request failed"), "the asserted label must survive");
  assert.ok(!text.includes("Unavailable"), "the two statuses must not be conflated");
  assert.ok(text.includes("Upstream provider returned 503; retry in a minute."), "the producer's reason must be shown");
});

// 4. No plausible default: with no producer reason the panel refuses by name.
test("no browser-invented reason is ever rendered", () => {
  const markup = renderOne({ sourceStatus: "unavailable", evidence: undefined, visibility: { enabled: true } });
  assert.ok(!markup.includes("This layer is not available for display."), "the browser must not invent a reason");
  assert.match(markup, /data-refusal="missing_status_reason"/, "the missing reason must be named as a refusal");
  assert.match(markup, /data-status="unavailable"/);
  assert.match(markup, /disabled=""/, "a layer with no supplied reason cannot be requested");
});

// 5. The evidence disclosure is load-bearing: all five fields plus the synthetic caveat.
test("the evidence disclosure renders every disclosed field", () => {
  const markup = renderOne({ sourceStatus: "synthetic", evidenceClass: "fixture" });
  assert.match(markup, /<dl class="layer-evidence"/, "the disclosure list must be rendered");
  for (const label of ["Source", "Vintage", "Coverage", "Transformation", "Uncertainty", "Topology caveat"]) {
    assert.ok(textOf(markup).includes(label), `the disclosure must label ${label}`);
  }
  for (const value of Object.values(evidence)) {
    assert.ok(textOf(markup).includes(value), `the disclosure must show ${value}`);
  }
});

// 6. The visibility filter refuses blocked layers instead of passing them to the parent.
test("a blocked layer cannot be added to the requested-visibility list", () => {
  const blocked = layer({ id: "blocked", sourceStatus: "unavailable", evidence: undefined, visibility: { enabled: false, reason: "Artifact not built; build it first." } });
  const open = layer({ id: "open" });
  const layers = [open, blocked];
  assert.equal(mod.nextVisibleLayerIds(layers, [], blocked, true), null, "requesting a blocked layer must be refused");
  assert.deepEqual(mod.nextVisibleLayerIds(layers, [], open, true), ["open"], "an unblocked layer is still requestable");
  assert.deepEqual(mod.nextVisibleLayerIds(layers, ["open"], open, false), [], "unchecking still works");
});

// 7. A layer that becomes blocked leaves the parent's list and renders unchecked.
test("a disabled layer is retracted from the visible list", () => {
  const blocked = layer({ id: "blocked", sourceStatus: "unavailable", evidence: undefined, visibility: { enabled: false, reason: "Artifact not built." } });
  const open = layer({ id: "open" });
  assert.deepEqual(
    mod.prunedVisibleLayerIds([open, blocked], ["open", "blocked"]),
    ["open"],
    "a blocked layer must be dropped from the requested list",
  );
  const markup = renderOne(
    { id: "l1", sourceStatus: "unavailable", evidence: undefined, visibility: { enabled: false, reason: "Artifact not built." } },
    ["l1"],
  );
  assert.ok(!markup.includes("checked=\"\""), "a disabled layer must not render checked");
});

// 8. Unknown category / evidence class fail closed too, matching the PR body's claim.
test("an unrecognised category or evidence class fails closed", () => {
  for (const over of [{ category: "weather" }, { evidenceClass: "vibes" }]) {
    const markup = renderOne(over);
    assert.match(markup, /data-status="unavailable"/, `${JSON.stringify(over)} must fail closed`);
    assert.match(markup, /data-refusal="unrecognized_descriptor"/, "the refusal must be named");
  }
});

// 9. The IA binds "not a recommendation" to the Hypothetical label itself.
test("hypothetical carries the IA's required accompanying copy", () => {
  const markup = renderOne({ sourceStatus: "hypothetical" });
  assert.ok(textOf(markup).includes("Not a recommendation."), "hypothetical must say it is not a recommendation");
});

// 10. The harness fixture must not present anything as source-supported that is not.
test("the committed harness fixture labels itself honestly", () => {
  const markup = mod.render({ layers: mod.harnessLayers, visibleLayerIds: [], onVisibleLayerIdsChange: () => {} });
  assert.ok(!markup.includes("This layer is not available for display."));
  assert.match(markup, /data-status="request_failed"/, "the failed-request row must keep its token");
  assert.match(markup, /data-refusal="unrecognized_status"/, "the unknown-token row must be refused");
  assert.deepEqual(
    mod.prunedVisibleLayerIds(mod.harnessLayers, ["topology", "events"]),
    ["topology"],
    "the harness's blocked initial selection must be retracted",
  );
});

// 11. The harness page must actually load the stylesheet it is measured through, and the
// build must emit it. Without this the responsive rules are unreachable in the browser.
test("the harness build emits the stylesheet the harness page links", { timeout: 120000 }, async () => {
  const html = await readFile(path.join(webRoot, "src/layers/harness.html"), "utf8");
  assert.match(html, /<link[^>]+rel="stylesheet"[^>]+href="\/assets\/app\.css"/, "the harness page must link the bundled CSS");

  const dist = await mkdtemp(path.join(os.tmpdir(), "flux-harness-dist-"));
  try {
    await run("node", ["scripts/build.mjs"], {
      cwd: webRoot,
      env: {
        ...process.env,
        FLUX_WEB_ENTRY: "src/layers/LayerControlsHarness.tsx",
        FLUX_WEB_HTML: "src/layers/harness.html",
        FLUX_WEB_DIST: dist,
      },
    });
    const emittedHtml = await readFile(path.join(dist, "index.html"), "utf8");
    assert.ok(emittedHtml.includes("Layer controls harness"), "the harness page, not the app page, must be served");
    assert.match(emittedHtml, /href="\/assets\/app\.css"/, "the served page must link the CSS");
    const css = await readFile(path.join(dist, "assets", "app.css"), "utf8");
    assert.ok(css.includes(".layer-controls"), "the component's CSS must be in the emitted bundle");
    // The narrow-viewport rules exist only if this block reaches the page.
    assert.match(css, /@media\s*\(max-width:\s*480px\)/, "the narrow-viewport block must be emitted");
    assert.match(css, /white-space:\s*nowrap/, "the status chips keep their no-wrap treatment");
  } finally {
    await rm(dist, { recursive: true, force: true });
  }
});
