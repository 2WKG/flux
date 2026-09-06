import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { build } from "esbuild";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const here = new URL(".", import.meta.url);
const webRoot = new URL("../../", import.meta.url);

// Same seam as src/ask/run-state/reducer.test.mjs: compile the TSX and import it,
// then assert on the markup the panel actually produces. React stays external so
// the renderer and the component share one React instance; the compiled entry is
// written inside node_modules so those bare specifiers still resolve.
const compiled = new URL("../../node_modules/.cache/flux-inspector-render.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { Inspector } from "./Inspector";
      export * as fixtures from "./fixtures";
      export const render = (asset) => renderToStaticMarkup(createElement(Inspector, { asset }));
    `,
    resolveDir: here.pathname,
    loader: "tsx",
    sourcefile: "inspector-render-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  outfile: compiled.pathname,
});
const { render, fixtures } = await import(compiled.href);

/** Rendered text only: markup tags and attributes are not the claim under test. */
const text = (asset) => render(asset).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

test("a source-supported asset renders its server-asserted identity and fields", () => {
  const rendered = text(fixtures.sourceBacked);
  assert.match(rendered, /Server-described asset/);
  assert.match(rendered, /Status Source supported/);
  assert.match(rendered, /Artifact Source supported/);
  assert.match(rendered, /Server supplied MW/);
  assert.match(rendered, /Uncertainty: Uncertainty supplied by server/);
});

test("a screened asset is labelled screened, never supported", () => {
  const rendered = text(fixtures.sourceScreened);
  assert.match(rendered, /Status Source screened/);
  assert.match(rendered, /Artifact Source screened/);
  assert.doesNotMatch(rendered, /Source supported/);
});

test("a hypothetical asset renders Hypothetical and never an invented artifact token", () => {
  const rendered = text(fixtures.hypothetical);
  assert.match(rendered, /Status Hypothetical/);
  assert.match(rendered, /Artifact Hypothetical/);
  assert.match(rendered, /does not establish a real-world condition/);
  // `source_backed` is not in the IA vocabulary (src/labels.ts).
  assert.doesNotMatch(rendered, /source_backed/);
});

test("source-neutral is not unlabelled: a synthetic asset names its topology", () => {
  const rendered = text(fixtures.synthetic);
  assert.match(rendered, /Status Synthetic/);
  assert.match(rendered, /Artifact Synthetic/);
  assert.match(rendered, /Topology synthetic \(ACTIVSg2000\)/);
  assert.match(rendered, /must not be read as a real facility/);
});

test("an unavailable response renders the unavailable state and no substituted identity", () => {
  const rendered = text(fixtures.unavailable);
  assert.match(rendered, /Status Unavailable/);
  assert.match(rendered, /Fixture: source detail is explicitly unavailable/);
  assert.match(rendered, /Identity unavailable/);
  assert.match(rendered, /Provenance unavailable/);
});

test("a request_failed payload carrying metrics renders neither the metric nor the identity", () => {
  const rendered = text(fixtures.unsafeFailure);
  assert.match(rendered, /Status Request failed/);
  assert.match(rendered, /Artifact Request failed/);
  assert.match(rendered, /Fixture: the source request failed/);
  assert.doesNotMatch(rendered, /42 MW/);
  assert.doesNotMatch(rendered, /Must not render/);
  assert.match(rendered, /Identity unavailable/);
});

test("a status/label mismatch withholds the supplied identity and metrics", () => {
  const rendered = text(fixtures.mismatched);
  assert.match(rendered, /Asset status and artifact label do not agree/);
  assert.doesNotMatch(rendered, /42 MW/);
  assert.doesNotMatch(rendered, /Must not render/);
  assert.match(rendered, /Status Unavailable/);
});

test("a malformed detail shape withholds the detail", () => {
  const rendered = text(fixtures.malformed);
  assert.match(rendered, /Asset detail is malformed/);
  assert.match(rendered, /Status Unavailable/);
});

test("a payload that is not an object, and no asset at all, both fail closed", () => {
  assert.match(text("source_supported"), /No server asset was supplied/);
  assert.match(text({ status: "not_a_token", artifactLabel: "not_a_token" }), /Asset status is missing or not recognized/);
  assert.match(text(null), /No asset selected/);
});

function run(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, options);
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", reject);
    child.on("close", (code) => code === 0 ? resolve(output) : reject(new Error(output)));
  });
}

test("the browser harness bundles the inspector with no network dependency", async () => {
  const dist = await mkdtemp(path.join(os.tmpdir(), "flux-inspector-harness-"));
  try {
    await run("node", ["scripts/build.mjs"], { cwd: webRoot, env: { ...process.env, FLUX_WEB_ENTRY: "src/inspector/browser-harness.tsx", FLUX_WEB_DIST: dist } });
    const server = http.createServer(async (request, response) => {
      const file = request.url === "/assets/app.js" ? path.join(dist, "assets/app.js") : path.join(dist, "index.html");
      response.writeHead(200, { "content-type": file.endsWith(".js") ? "text/javascript" : "text/html" });
      response.end(await readFile(file));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const origin = `http://127.0.0.1:${server.address().port}`;
      const app = await (await fetch(`${origin}/assets/app.js`)).text();
      assert.match(app, /Inspector browser harness/);
      assert.doesNotMatch(app, /\bfetch\s*\(/);
      assert.doesNotMatch(app, /XMLHttpRequest|EventSource/);
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  } finally {
    await rm(dist, { recursive: true, force: true });
  }
});
