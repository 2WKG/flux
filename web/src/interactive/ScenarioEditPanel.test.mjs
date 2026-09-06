import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const outDir = await mkdtemp(path.join(os.tmpdir(), "flux-scenario-edit-"));
const outfile = path.join(outDir, "entry.mjs");

await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      export { blankGridEdit, insertGridEdit, replaceGridEdit, removeGridEdit, moveGridEdit } from "./src/interactive/ScenarioEditPanel";
      import { ScenarioEditPanel } from "./src/interactive/ScenarioEditPanel";
      export const render = (props) => renderToStaticMarkup(createElement(ScenarioEditPanel, props));
    `,
    resolveDir: webRoot,
    loader: "tsx",
    sourcefile: "scenario-edit-render-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  jsx: "automatic",
  absWorkingDir: webRoot,
  tsconfig: path.join(webRoot, "tsconfig.json"),
  banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
  outfile,
  logLevel: "silent",
});

const panel = await import(pathToFileURL(outfile).href);
process.on("exit", () => { rm(outDir, { recursive: true, force: true }); });

const baseProps = (overrides = {}) => ({
  baseScenarioId: "uri_2021",
  ops: [],
  onOpsChange: () => {},
  serverState: { kind: "unavailable" },
  ...overrides,
});

test("the five documented edit kinds expose only their documented fields", () => {
  const expected = {
    outage: ["Element ID"],
    remove: ["Element ID"],
    add_gen: ["Element ID", "Bus ID", "Scheduled MW", "Maximum MW"],
    add_load: ["Element ID", "Bus ID", "Demand MW"],
    add_line: ["Element ID", "From bus ID", "To bus ID", "Resistance (p.u.)", "Reactance (p.u.)", "Rating (MW)", "Base voltage (kV)", "Length (km)"],
  };
  for (const [kind, fields] of Object.entries(expected)) {
    const markup = panel.render(baseProps({ ops: [panel.blankGridEdit(kind)] }));
    assert.match(markup, new RegExp(`data-grid-edit-kind="${kind}"`));
    assert.match(markup, /data-truth-label="illustrative"/, `${kind} must remain illustrative`);
    for (const field of fields) assert.ok(markup.includes(field), `${kind} is missing ${field}`);
  }
});

test("ordered operations change immutably and are never sorted", () => {
  const initial = [panel.blankGridEdit("outage"), panel.blankGridEdit("add_load")];
  const appended = panel.insertGridEdit(initial, "add_gen");
  assert.deepEqual(initial.map((edit) => edit.kind), ["outage", "add_load"]);
  assert.deepEqual(appended.map((edit) => edit.kind), ["outage", "add_load", "add_gen"]);
  const moved = panel.moveGridEdit(appended, 2, 0);
  assert.deepEqual(moved.map((edit) => edit.kind), ["add_gen", "outage", "add_load"]);
  const replaced = panel.replaceGridEdit(moved, 1, { kind: "remove", element_id: "line:7" });
  assert.deepEqual(replaced.map((edit) => edit.kind), ["add_gen", "remove", "add_load"]);
  assert.deepEqual(panel.removeGridEdit(replaced, 1).map((edit) => edit.kind), ["add_gen", "add_load"]);
  assert.notStrictEqual(appended, initial);
  assert.notStrictEqual(moved, appended);
});

test("all server verdicts, reasons, and the edit hash render without browser inference", () => {
  const markup = panel.render(baseProps({
    serverState: {
      kind: "ready",
      edit_hash: "server-hash-42",
      feasibility: [
        { verdict: "valid", op_index: 0, stage: "geometry", reason: "Server found a compatible bus." },
        { verdict: "invalid", op_index: 1, stage: "solve", reason: "Server found an island." },
        { verdict: "unknown", reason: "Server lacks corridor evidence." },
      ],
    },
  }));
  for (const copy of ["Server: valid", "Server: invalid", "Server: unknown", "Server found a compatible bus.", "Server found an island.", "Server lacks corridor evidence.", "server-hash-42"]) {
    assert.ok(markup.includes(copy), `missing server-supplied ${copy}`);
  }
  assert.ok(!markup.includes("No stable scenario edit endpoint is mounted"));
});

test("loading, unavailable, and error remain explicit states", () => {
  const loading = panel.render(baseProps({ serverState: { kind: "loading" } }));
  assert.match(loading, /data-scenario-edit-state="loading"/);
  assert.match(loading, /browser has not evaluated this edit/);

  const unavailable = panel.render(baseProps({ serverState: { kind: "unavailable" } }));
  assert.match(unavailable, /data-scenario-edit-state="unavailable"/);
  assert.match(unavailable, /No stable scenario edit endpoint is mounted/);

  const failed = panel.render(baseProps({ serverState: { kind: "error", reason: "The server returned 503." } }));
  assert.match(failed, /data-scenario-edit-state="error"/);
  assert.match(failed, /The server returned 503\./);
});
