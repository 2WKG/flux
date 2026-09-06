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
      export { STATUS_COPY } from "./src/source-truth";
      export { ASSET_STATUS_TOKENS } from "./src/labels";
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
    assert.match(markup, /data-truth-label="hypothetical"/, `${kind} must be labelled hypothetical`);
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

/** The prohibited decorative status word, spelled once, without seeding it. */
const PROHIBITED_STATUS_WORD = ["illus", "trative"].join("");

test("the panel's truth label is an IA token and never the prohibited status word", () => {
  const markup = panel.render(baseProps({ ops: [panel.blankGridEdit("add_gen"), panel.blankGridEdit("add_line")] }));

  // Every truth label this panel can render is one of the six IA tokens...
  const labels = [...markup.matchAll(/data-truth-label="([^"]*)"/g)].map((match) => match[1]);
  assert.ok(labels.length > 0, "the panel rendered no truth label at all");
  for (const label of labels) {
    assert.ok(panel.ASSET_STATUS_TOKENS.includes(label), `"${label}" is not one of the six IA status tokens`);
    assert.equal(label, "hypothetical", "an editable proposal is hypothetical per the IA truth-label table");
  }

  // ...and its display string has one owner.
  assert.ok(markup.includes(panel.STATUS_COPY.hypothetical), "the chip does not render STATUS_COPY.hypothetical");

  // The prohibited word must not appear anywhere the panel renders, in copy or
  // in an attribute. Three frozen contracts refuse it by name.
  assert.ok(
    !markup.toLowerCase().includes(PROHIBITED_STATUS_WORD),
    "the prohibited decorative status word is back in the rendered panel",
  );
  assert.match(markup, /data-scenario-edit-panel="hypothetical"/);
});

test("no feasibility verdict is invented while the server has not returned one", () => {
  // The panel's headline safety property: "Feasibility comes only from the
  // server; this panel does not calculate it." Nothing asserted it before, so a
  // browser-invented "looks valid" screen passed with the whole suite green.
  const verdictShaped = /looks valid|\(feasible\)|\(infeasible\)|Browser screen|appears feasible|likely feasible/i;
  for (const serverState of [
    { kind: "loading" },
    { kind: "unavailable" },
    { kind: "error", reason: "The server returned 503." },
    { kind: "ready", edit_hash: "server-hash-42", feasibility: [] },
  ]) {
    const markup = panel.render(baseProps({
      ops: [panel.blankGridEdit("add_gen"), panel.blankGridEdit("add_line")],
      serverState,
    }));
    assert.doesNotMatch(markup, verdictShaped, `a verdict-shaped claim appeared for ${serverState.kind}`);
    assert.doesNotMatch(markup, /data-feasibility-verdict=/, `a verdict row appeared for ${serverState.kind}`);
  }
});

test("every rendered verdict string is server-keyed copy, never composed in the browser", () => {
  const owned = new Set(["Server: valid", "Server: invalid", "Server: unknown"]);
  const markup = panel.render(baseProps({
    ops: [panel.blankGridEdit("add_gen")],
    serverState: {
      kind: "ready",
      edit_hash: "server-hash-42",
      feasibility: [{ verdict: "valid", op_index: 0, reason: "Server found a compatible bus." }],
    },
  }));
  const rendered = [...markup.matchAll(/<strong>(Server: [a-z]+)<\/strong>/g)].map((match) => match[1]);
  assert.deepEqual(rendered, ["Server: valid"]);
  for (const value of rendered) assert.ok(owned.has(value), `"${value}" is not a verdictCopy value`);

  // And the operation heading carries no verdict of its own.
  const headings = [...markup.matchAll(/<strong>(\d+\. [^<]*)<\/strong>/g)].map((match) => match[1]);
  assert.deepEqual(headings, ["1. Add producer"], "the operation heading gained a browser-composed verdict");
});
