// The rendered synthetic topology must carry the server's own truth label.
//
// `viewport-shell.test.mjs` pins the map's *accessible* name
// ("Full synthetic Texas topology"), which is a constant in the source. Nothing
// pinned the label a sighted operator reads: the `synthetic (ACTIVSg2000)`
// string the model route supplies, rendered into `data-topology` and into the
// scene's own status line. Both could be deleted, or replaced with an
// unlabelled "grid", with every gate green.
//
// So this file renders the real component through the same seam the shell tests
// use -- compile the TSX with esbuild, render with react-dom/server -- and
// asserts the label on both surfaces, and that it is *derived from the payload*
// rather than restated as a constant (a second payload with a different label
// must move both surfaces).
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-texas-topology-render.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { TexasTopologyMap } from "./src/renderer/TexasTopologyMap";
      export const renderMap = (payload) => renderToStaticMarkup(createElement(TexasTopologyMap, { payload }));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "texas-topology-render-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const { renderMap } = await import(compiled.href);

const SYNTHETIC_LABEL = "synthetic (ACTIVSg2000)";

/** A resolved two-bus, one-branch model, the smallest payload that renders the scene. */
function payload(label) {
  return {
    status: "available",
    data: {
      topology: { label, synthetic: true },
      counts: { buses: 2, branches: 1, generators: 0, loads: 0 },
      elements: [
        { element_id: "bus:1", resolved: true, role: "bus", geometry: { type: "Point", coordinates: [-100, 30] } },
        { element_id: "bus:2", resolved: true, role: "bus", geometry: { type: "Point", coordinates: [-98, 32] } },
        { element_id: "line:1", resolved: true, role: "line", geometry: { type: "LineString", coordinates: [[-100, 30], [-98, 32]] } },
      ],
    },
  };
}

const rendered = renderMap(payload(SYNTHETIC_LABEL));
const readable = rendered.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

test("the rendered topology publishes the server's synthetic label as a machine attribute", () => {
  const topology = /data-topology="([^"]*)"/.exec(rendered);
  assert.ok(topology, "the rendered scene must carry a data-topology attribute");
  assert.equal(topology[1], SYNTHETIC_LABEL,
    "data-topology must be the label the model route supplied, not a relabelled or generic topology");
});

test("the visible status line names the synthetic topology a sighted operator is looking at", () => {
  assert.ok(readable.includes(SYNTHETIC_LABEL),
    `the scene's readable status line must name ${SYNTHETIC_LABEL}; rendered text was: ${readable.slice(0, 400)}`);
  // The counts sit in the same line, so the label cannot be satisfied by some
  // other element that happens to carry the string.
  assert.match(readable, new RegExp(`synthetic \\(ACTIVSg2000\\)[^.]*2 resolved buses`),
    "the label must head the scene's own status line, immediately before its resolved counts");
});

test("both surfaces are read from the payload, not restated as a constant", () => {
  // A hard-coded label would keep the two assertions above green while lying
  // about any other topology the route supplies.
  const other = renderMap(payload("synthetic (OTHER-TOPOLOGY)"));
  const otherReadable = other.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  assert.match(other, /data-topology="synthetic \(OTHER-TOPOLOGY\)"/);
  assert.ok(otherReadable.includes("synthetic (OTHER-TOPOLOGY)"));
  assert.ok(!other.includes(SYNTHETIC_LABEL), "the ACTIVSg2000 label must not be restated for a different topology");
});

test("an available model renders the topology and never the unavailable card", () => {
  // The two states must be distinguishable by this probe, or it could not fail:
  // a component that regressed to always rendering the named failure would keep
  // a one-sided assertion green.
  assert.ok(!readable.includes("Texas model unavailable"), "an available payload must not render the unavailable state");
  assert.match(readable, /2 resolved buses · 1 resolved branches/, "the scene must report the counts the route supplied");

  const missing = renderMap({ status: "unavailable", reason: "the model route has no artifact" });
  const missingText = missing.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  assert.match(missingText, /Texas model unavailable: the model route has no artifact/,
    "an unavailable payload must name its own reason, never a plausible default");
  assert.ok(!missing.includes("data-topology"), "the unavailable state must not publish a topology label it does not have");
});
