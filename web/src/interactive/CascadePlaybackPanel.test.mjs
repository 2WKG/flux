import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { createElement } from "react";

const here = new URL(".", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-cascade-playback.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: 'export * from "./CascadePlaybackPanel";',
    resolveDir: here.pathname,
    loader: "tsx",
    sourcefile: "cascade-playback-test-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  outfile: compiled.pathname,
});
const { CascadePlaybackPanel, cascadeStages } = await import(compiled.href);

const response = (runId) => ({
  model_fidelity: "dc_screening",
  network_provenance: "synthetic_activsg2000",
  limitations: ["Synthetic topology."],
  data: {
    run_id: runId,
    scenario_id: "uri_2021",
    hour: 3,
    lost_load_mw: 12.5,
    tripped_element_ids: [
      { element_id: "line:later", kind: "line", cause: "overload", stage: 2 },
      { element_id: "gen:forced", kind: "generator", cause: "forced", stage: 0 },
    ],
    county_impacts: [{ county_fips: "48453", stage: 2, customers_out: 19 }],
    critical_loads_lost: [{ id: "hospital:1", name: "North Hospital", stage: 2 }],
  },
});

test("solver stages are sorted by returned stage without deriving new events", () => {
  const stages = cascadeStages(response("run-a").data);
  assert.deepEqual(stages.map((stage) => stage.stage), [0, 2]);
  assert.equal(stages[0].tripped[0].element_id, "gen:forced");
  assert.equal(stages[1].tripped[0].cause, "overload");
});

async function mount(props) {
  const dom = new JSDOM("<div id=app></div>", { url: "http://localhost" });
  const keys = ["window", "document", "navigator", "HTMLElement", "IS_REACT_ACT_ENVIRONMENT"];
  const previous = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const restore = () => {
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  };
  const install = (key, value) => Object.defineProperty(globalThis, key, {
    value,
    configurable: true,
    enumerable: previous.get(key)?.enumerable ?? true,
    writable: true,
  });
  let root;
  try {
    install("window", dom.window);
    install("document", dom.window.document);
    install("navigator", dom.window.navigator);
    install("HTMLElement", dom.window.HTMLElement);
    install("IS_REACT_ACT_ENVIRONMENT", true);
    root = createRoot(dom.window.document.getElementById("app"));
    await act(async () => root.render(createElement(CascadePlaybackPanel, props)));
  } catch (error) {
    restore();
    dom.window.close();
    throw error;
  }
  return {
    dom,
    root,
    async click(name) {
      const button = [...dom.window.document.querySelectorAll("button")].find((item) => item.textContent === name);
      assert.ok(button, `button ${name} exists`);
      await act(async () => button.click());
    },
    async flush() { await act(async () => {}); },
    async dispose() {
      try {
        await act(async () => root.unmount());
      } finally {
        restore();
        dom.window.close();
      }
    },
  };
}

test("a cancelled or stale server response never replaces a newer accepted run", async () => {
  const pending = [];
  const panel = await mount({
    elements: [{ id: "line:7", label: "Named corridor", kind: "line" }],
    scenarioId: "uri_2021",
    hour: 3,
    defaultSelectedElementIds: ["line:7"],
    runCascade: (request, signal) => new Promise((resolve) => pending.push({ request, signal, resolve })),
  });
  try {
    await panel.click("Run selected outages");
    assert.deepEqual(pending[0].request.element_ids, ["line:7"]);
    await panel.click("Cancel run");
    await act(async () => pending[0].resolve(response("cancelled-run")));
    assert.doesNotMatch(panel.dom.window.document.body.textContent, /cancelled-run/);
    assert.match(panel.dom.window.document.body.textContent, /Request cancelled/);

    await panel.click("Run selected outages");
    await panel.click("Cancel run");
    await panel.click("Run selected outages");
    await act(async () => pending[2].resolve(response("newer-run")));
    assert.match(panel.dom.window.document.body.textContent, /newer-run/);
    await act(async () => pending[1].resolve(response("stale-run")));
    assert.doesNotMatch(panel.dom.window.document.body.textContent, /stale-run/);
  } finally {
    await panel.dispose();
  }
});

test("the immutable edit hash is forwarded to the cascade request", async () => {
  let cascadeRequest;
  const panel = await mount({
    elements: [{ id: "gen:9", label: "Provider", kind: "generator" }],
    scenarioId: "uri_2021",
    hour: 4,
    seed: 7,
    defaultSelectedElementIds: ["gen:9"],
    prepareEdit: async (request) => {
      assert.deepEqual(request, {
        base_scenario_id: "uri_2021",
        hour: 4,
        seed: 7,
        ops: [{ op: "outage", element_id: "gen:9" }],
      });
      return { data: { edit_hash: "a".repeat(16) }, model_fidelity: "dc_screening", network_provenance: "synthetic_activsg2000", limitations: [] };
    },
    runCascade: async (request) => {
      cascadeRequest = request;
      return response("edited-run");
    },
  });
  try {
    await panel.click("Run selected outages");
    await panel.flush();
    assert.deepEqual(cascadeRequest, {
      element_ids: ["gen:9"],
      scenario_id: "uri_2021",
      hour: 4,
      seed: 7,
      edit_hash: "a".repeat(16),
    });
    assert.match(panel.dom.window.document.body.textContent, /edited-run/);
  } finally {
    await panel.dispose();
  }
});

test.after(async () => {
  await rm(compiled.pathname, { force: true });
});
