// The explainer's rendering contract. Before this file the page could be
// emptied, relabelled `source_supported`, or stripped of its synthetic
// disclosure with the suite green: `explainerBoundary.test.mjs` only read the
// source as text. These checks render the component.
//
// The expected numbers are pinned as literals on purpose. They come from the
// committed server artifact `data/explainer/toy-cascade-trace.json`, whose
// freshness `twin/tests/test_toy_cascade.py` proves against a live re-solve --
// so corrupting the artifact fails here as well as there, and reading the
// expectations back out of the artifact would have made this test blind.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const pagePath = path.join(webRoot, "src/pages/ExplainerPage.tsx");

const TRACE_HASH = "ed58c8fcd45adb72e57f2e2b3abb9e4ddf741bc8dd3db3329d0addab955674cd";

async function render() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-482-explainer-"));
  const entry = path.join(directory, "entry.tsx");
  const output = path.join(directory, "entry.mjs");
  await writeFile(
    entry,
    `
    import { renderToStaticMarkup } from "react-dom/server";
    import { ExplainerPage } from ${JSON.stringify(pagePath)};
    export const markup = renderToStaticMarkup(<ExplainerPage />);
  `,
    "utf8",
  );
  await build({
    entryPoints: [entry],
    outfile: output,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    absWorkingDir: webRoot,
    nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"),
    loader: { ".json": "json" },
    banner: {
      js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
    },
    logLevel: "silent",
  });
  try {
    const { markup } = await import(`${pathToFileURL(output).href}?t=${Date.now()}`);
    return markup;
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

const markup = await render();

test("the page labels itself synthetic and never claims a supported source", () => {
  assert.match(markup, /<main[^>]*data-source-status="synthetic"/);
  for (const claim of ["source_supported", "source_screened", "Source-supported", "Source-screened"]) {
    assert.ok(!markup.includes(claim), `the explainer claims ${claim}`);
  }
});

test("the page credits the server module, artifact, route and trace hash it replays", () => {
  assert.match(markup, /twin\/toy_cascade\.py/);
  assert.match(markup, /data\/explainer\/toy-cascade-trace\.json/);
  assert.match(markup, /\/explainer\/toy-cascade/);
  assert.ok(markup.includes(TRACE_HASH), "the rendered trace hash is not the committed artifact's");
  assert.match(markup, /replays that trace; it computes nothing/);
});

test("the bus-balance table renders the injections and angles the server solved", () => {
  // Stage 1 of the committed artifact: west +120 MW, east -70 MW, theta_east -27.143.
  assert.match(markup, /<td>West generator<\/td><td>120<\/td><td>0<\/td><td>None<\/td>/);
  assert.match(markup, /<td>East load<\/td><td>-70<\/td><td>-27\.143<\/td><td>None<\/td>/);
  assert.match(markup, /<td>Central hub<\/td><td>-30<\/td><td>-16\.429<\/td>/);
});

test("the per-line table renders the DC arithmetic and utilization the server recorded", () => {
  assert.match(markup, /<td>west-hub<\/td>/);
  // (0 - -16.429) / 0.2 = 82.1 MW, 74.7% of a 110 MW rating: within rating.
  assert.match(markup, /\(0 − -16\.429\) \/ 0\.2 = 82\.1 MW/);
  assert.match(markup, /74\.7% \(within rating\)/);
  assert.match(markup, /remove <code>east-south<\/code>|no active line exceeds its listed rating/);
});

test("the diagram renders every corridor with a worded utilization band", () => {
  assert.match(markup, /<svg[^>]*aria-label="Five-bus teaching network at 1\. Normal toy network"/);
  assert.match(markup, /82\.1 MW \/ 110 MW \(within rating\)/);
  assert.ok(!/stroke="#ff7d68"[^>]*>\s*<text[^>]*>[^(]*<\/text>/.test(markup));
});

test("the synthetic disclosures are on the page, not only in the source", async () => {
  assert.match(markup, /All topology, ratings, and injections here are synthetic teaching inputs\./);
  assert.match(markup, /No reactive power or voltage constraints\./);
  assert.match(markup, /No dynamics, stability, or restoration timeline\./);
  assert.match(markup, /Islands balance through proportional load shedding or generation curtailment\./);
  assert.match(markup, /synthetic five-bus teaching network/i);
  assert.match(markup, /not the main page’s fixture or the server’s ACTIVSg2000 topology/);
  const trace = JSON.parse(
    await readFile(new URL("../../../data/explainer/toy-cascade-trace.json", import.meta.url), "utf8"),
  );
  const escape = (text) =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/'/g, "&#x27;");
  for (const limitation of trace.limitations) {
    assert.ok(
      markup.includes(escape(limitation)),
      `the page drops the artifact limitation: ${limitation}`,
    );
  }
});

test("the page renders the recorded stage count, not an invented one", () => {
  assert.match(markup, /Stage 1 of 3/);
  assert.match(markup, /1\. Normal toy network/);
});
