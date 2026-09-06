/**
 * The container is the seam where a server response becomes what the panel
 * renders. Everything it may do is a rename or a drop; it may never turn an
 * unrecognised row into a verdict, and it may never produce a `ready` state
 * from a failure.
 */
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const outDir = await mkdtemp(path.join(os.tmpdir(), "flux-scenario-edit-container-"));
const outfile = path.join(outDir, "entry.mjs");
process.on("exit", () => { rm(outDir, { recursive: true, force: true }); });

await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      export { serverVerdicts, serverStateFor, NO_EDIT_ENDPOINT, ScenarioEditContainer } from "./src/interactive/ScenarioEditContainer";
      import { ScenarioEditContainer } from "./src/interactive/ScenarioEditContainer";
      export const render = (props) => renderToStaticMarkup(createElement(ScenarioEditContainer, props));
    `,
    resolveDir: webRoot,
    loader: "tsx",
    sourcefile: "scenario-edit-container-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", target: "node20", jsx: "automatic",
  absWorkingDir: webRoot, tsconfig: path.join(webRoot, "tsconfig.json"),
  loader: { ".css": "empty" },
  banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
  outfile, logLevel: "silent",
});
const container = await import(pathToFileURL(outfile).href);

test("only a server-supplied verdict becomes a verdict", () => {
  const rows = container.serverVerdicts({
    feasibility: [
      { verdict: "valid", reason: "Server found a compatible bus.", op_index: 0, stage: "geometry" },
      // No verdict the server owns: dropped, never reinterpreted.
      { reason: "The solver did not reach this operation." },
      { verdict: "looks_valid", reason: "Not a server verdict." },
      { verdict: "invalid" },
    ],
  });
  assert.deepEqual(rows, [
    { verdict: "valid", reason: "Server found a compatible bus.", op_index: 0, stage: "geometry" },
  ]);
});

test("a payload with no feasibility array yields no verdicts at all", () => {
  for (const payload of [null, undefined, {}, { feasibility: "soon" }, []]) {
    assert.deepEqual(container.serverVerdicts(payload), []);
  }
});

test("only a ready client state produces a ready panel state", () => {
  assert.deepEqual(container.serverStateFor({ kind: "loading" }), { kind: "loading" });
  assert.deepEqual(container.serverStateFor({ kind: "unavailable", message: "Not deployed." }), {
    kind: "unavailable", reason: "Not deployed.",
  });
  assert.deepEqual(container.serverStateFor({ kind: "unavailable" }), {
    kind: "unavailable", reason: container.NO_EDIT_ENDPOINT,
  });
  assert.deepEqual(container.serverStateFor({ kind: "failed", message: "Unable to reach the service." }), {
    kind: "error", reason: "Unable to reach the service.",
  });
  assert.deepEqual(container.serverStateFor({ kind: "invalid", message: "Malformed." }), {
    kind: "error", reason: "Malformed.",
  });
  assert.deepEqual(
    container.serverStateFor({ kind: "ready", data: { edit_hash: "h1", feasibility: [] } }),
    { kind: "ready", edit_hash: "h1", feasibility: [] },
  );
  // A receipt the server did not send is not invented.
  assert.deepEqual(container.serverStateFor({ kind: "ready", data: {} }), { kind: "ready", feasibility: [] });
});

test("with no interactive route mounted the composer refuses by name", () => {
  const markup = container.render({ baseScenarioId: "uri_2021" });
  assert.match(markup, /data-scenario-edit-state="unavailable"/);
  assert.match(markup, /No stable scenario edit endpoint is mounted/);
  assert.doesNotMatch(markup, /data-feasibility-verdict=/);
  assert.match(markup, /Submit to the scenario edit service/);
});
