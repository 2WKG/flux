// The fixture is the captured `/interactive/balance` payload
// (`src/contracts/interactive-payloads.json`), produced by running
// `twin.balance.balance_report`. The previous fixture was an invented
// camelCase shape whose numbers summed to zero, so an assertion that the
// browser does not compute the residual could not fail.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
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
const { toBalanceView } = await import(pathToFileURL(join(outputDirectory, "data", "interactive-client.js")).href);

const captured = JSON.parse(readFileSync(new URL("../contracts/interactive-payloads.json", import.meta.url), "utf8"))
  .routes["/interactive/balance"].response;

const render = (payload) =>
  renderToStaticMarkup(createElement(BalancePanel, { state: { kind: "ready", data: toBalanceView(payload) } }));

const mw = (value) => `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)} MW`;
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("renders only the server's own MW fields and the server's capability basis", () => {
  const markup = render(captured);
  for (const value of [captured.draw_mw, captured.capability_mw, captured.dispatch_mw, captured.headroom_mw]) {
    assert.match(markup, new RegExp(escape(mw(value))));
  }
  // The basis is the producer's free-text sentence, rendered verbatim; the old
  // client demanded an enum and would have rejected this string outright.
  assert.match(markup, new RegExp(escape(captured.capability_basis)));
  for (const limitation of captured.limitations) {
    assert.match(markup, new RegExp(escape(limitation)));
  }
});

test("headroom is the server's field, not capability minus draw", () => {
  // This payload's headroom deliberately disagrees with the subtraction a
  // browser might perform. If the panel ever computes the figure itself, the
  // rendered value becomes 50 MW and this assertion fails.
  const disagreeing = { ...captured, headroom_mw: -2 };
  const derived = disagreeing.capability_mw - disagreeing.draw_mw;
  assert.notEqual(derived, -2, "the probe payload must be able to tell the two states apart");

  const markup = render(disagreeing);
  assert.match(markup, new RegExp(`data-balance-headroom="true">${escape(mw(-2))}`));
  assert.doesNotMatch(markup, new RegExp(`data-balance-headroom="true">${escape(mw(derived))}`));
});

test("the absence of provenance is stated, never labelled as a source claim", () => {
  const markup = render(captured);
  assert.match(markup, /data-balance-provenance="unavailable"/);
  assert.match(markup, /carries no provenance record/);
  assert.doesNotMatch(markup, /Source-supported|Source-screened/);
});

test("renders an explicit unavailable state and no invented grid metric", () => {
  const markup = renderToStaticMarkup(createElement(BalancePanel, {
    state: { kind: "unavailable", source: "server", message: "Balance endpoint is not deployed.", retryAfterSeconds: null, requestId: "request-1" },
  }));
  assert.match(markup, /Unavailable/);
  assert.match(markup, /Balance endpoint is not deployed/);
  assert.doesNotMatch(markup, /Consumer draw|Producer capability|Scheduled dispatch|Headroom/);
});
