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
const { CascadePlaybackPanel, cascadeStages, elementMeaning, networkProvenanceLabel } = await import(compiled.href);

/** One artifact reference, the shape the frozen `ArtifactRef` publishes. */
const PROVENANCE = [
  {
    artifact_id: "flux:cascade:uri_2021",
    artifact_version: "3.1.0",
    source_kind: "simulated",
    source_ref: "twin/cascade.py::run_cascade",
  },
];

/** PR #331's `_result()` envelope around the frozen `CascadeData`. */
const response = (runId, overrides = {}) => ({
  model_fidelity: "dc_screening",
  network_provenance: "synthetic_activsg2000",
  limitations: ["Synthetic topology."],
  data: {
    run_id: runId,
    scenario_id: "uri_2021",
    hour: 3,
    status: "available",
    steps: 2,
    lost_load_mw: 12.5,
    counties_dark: ["48453"],
    critical_loads_lost: [{ id: "hospital:1", name: "North Hospital", kind: "hospital", hour_lost: 4 }],
    provenance: PROVENANCE,
    tripped_element_ids: [
      { element_id: "line:later", kind: "line", cause: "overload", stage: 2 },
      { element_id: "gen:forced", kind: "gen", cause: "forced", stage: 0 },
    ],
    ...overrides,
  },
});

test("solver stages are sorted by returned stage without deriving new events", () => {
  const stages = cascadeStages(response("run-a").data);
  assert.deepEqual(stages.map((stage) => stage.stage), [0, 2]);
  assert.equal(stages[0].tripped[0].element_id, "gen:forced");
  assert.equal(stages[1].tripped[0].cause, "overload");
});

test("an element kind outside the frozen union is refused, never given a plausible default", () => {
  // The four kinds `TrippedElement.kind` publishes each read as themselves.
  assert.equal(elementMeaning("line"), "Transmission line outage");
  assert.equal(elementMeaning("gen"), "Provider outage");
  assert.equal(elementMeaning("trafo"), "Transformer outage");
  assert.equal(elementMeaning("bus"), "Substation bus outage");
  // Anything else names the refusal and the unknown kind; it never claims an
  // outage meaning the contract does not publish.
  for (const unknown of ["impedance", "static_generator", "load", ""]) {
    const meaning = elementMeaning(unknown);
    assert.match(meaning, /^Unavailable/, `"${unknown}" was given a meaning instead of a refusal`);
    assert.ok(meaning.includes(unknown), "the refusal must name the kind it refused");
    for (const plausible of [/Transmission/, /Provider/, /Transformer/, /Substation/]) {
      assert.doesNotMatch(meaning, plausible, `"${unknown}" was labelled with a real kind's meaning`);
    }
  }
});

test("the network provenance token is rendered as its published label", () => {
  assert.equal(networkProvenanceLabel("synthetic_activsg2000"), "synthetic (ACTIVSg2000)");
  // `copilot/interactive_routes.py`'s `interactive_labels()` sends
  // `pipelines.labels.SYNTHETIC_TOPOLOGY_LABEL` itself, not a token, so the
  // published label must survive the mapping unchanged rather than be reported
  // as unlabelled.
  assert.equal(networkProvenanceLabel("synthetic (ACTIVSg2000)"), "synthetic (ACTIVSg2000)");
  // A token with no published label is named as unlabelled, not printed as prose.
  assert.match(networkProvenanceLabel("some_other_case"), /unlabelled provenance token/);
});

async function mount(props) {
  const dom = new JSDOM("<div id=app></div>", { url: "http://localhost" });
  const overrides = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  // `globalThis.navigator` is an accessor-only global from Node 21 on, so
  // `Object.assign` throws `Cannot set property navigator of #<Object> which
  // has only a getter` and every test below crashes before it runs. Defining
  // each key sets and restores all five on any supported Node.
  const previous = new Map(Object.keys(overrides).map((key) => [key, globalThis[key]]));
  const define = (key, value) => Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  for (const [key, value] of Object.entries(overrides)) define(key, value);
  const root = createRoot(dom.window.document.getElementById("app"));
  await act(async () => root.render(createElement(CascadePlaybackPanel, props)));
  return {
    dom,
    root,
    text() {
      return dom.window.document.body.textContent;
    },
    async click(name) {
      const button = [...dom.window.document.querySelectorAll("button")].find((item) => item.textContent === name);
      assert.ok(button, `button ${name} exists`);
      await act(async () => button.click());
    },
    async flush() { await act(async () => {}); },
    async wait(ms) { await act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); }); },
    async dispose() {
      await act(async () => root.unmount());
      for (const [key, value] of previous) define(key, value);
      dom.window.close();
    },
  };
}

const ONE_LINE = [{ id: "line:7", label: "Named corridor", kind: "line" }];

test("a cancelled or stale server response never replaces a newer accepted run", async () => {
  const pending = [];
  const panel = await mount({
    elements: ONE_LINE,
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
    assert.doesNotMatch(panel.text(), /cancelled-run/);
    assert.match(panel.text(), /Request cancelled/);

    await panel.click("Run selected outages");
    await panel.click("Cancel run");
    await panel.click("Run selected outages");
    await act(async () => pending[2].resolve(response("newer-run")));
    assert.match(panel.text(), /newer-run/);
    await act(async () => pending[1].resolve(response("stale-run")));
    assert.doesNotMatch(panel.text(), /stale-run/);
  } finally {
    await panel.dispose();
  }
});

test("a superseded response the panel never aborted is still refused", async () => {
  // The test above cancels, and cancelling aborts. This one supersedes a run
  // *without* the panel ever calling `controller.abort()`: the stated budget
  // expires, which retires the run and leaves its request promise live, and
  // then a second run is started. A guard that only asked whether the panel's
  // own controller had been aborted would accept the late first response; only
  // the generation counter can refuse it.
  const pending = [];
  const panel = await mount({
    elements: ONE_LINE,
    scenarioId: "uri_2021",
    hour: 3,
    budgetSeconds: 0.3,
    defaultSelectedElementIds: ["line:7"],
    runCascade: (request, signal) => new Promise((resolve) => pending.push({ request, signal, resolve })),
  });
  try {
    await panel.click("Run selected outages");
    await panel.wait(420);
    assert.match(panel.text(), /Request failed: The server did not return a cascade result/);

    await panel.click("Run selected outages");
    assert.equal(pending.length, 2, "the second run must issue its own request");
    await act(async () => pending[1].resolve(response("accepted-run")));
    assert.match(panel.text(), /accepted-run/);

    await act(async () => pending[0].resolve(response("superseded-run")));
    assert.doesNotMatch(panel.text(), /superseded-run/, "a superseded response replaced the accepted run");
    assert.match(panel.text(), /accepted-run/);
  } finally {
    await panel.dispose();
  }
});

test("the immutable edit hash is forwarded to the cascade request", async () => {
  let cascadeRequest;
  const panel = await mount({
    elements: [{ id: "gen:9", label: "Provider", kind: "gen" }],
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
    assert.match(panel.text(), /edited-run/);
  } finally {
    await panel.dispose();
  }
});

test("an edit the server accepted without an immutable hash never reaches the cascade route", async () => {
  for (const editHash of ["", undefined, "not-a-hash", "abc"]) {
    let cascadeCalls = 0;
    const panel = await mount({
      elements: ONE_LINE,
      scenarioId: "uri_2021",
      hour: 3,
      defaultSelectedElementIds: ["line:7"],
      prepareEdit: async () => ({
        data: { edit_hash: editHash },
        model_fidelity: "dc_screening",
        network_provenance: "synthetic_activsg2000",
        limitations: [],
      }),
      runCascade: async () => { cascadeCalls += 1; return response("must-not-run"); },
    });
    try {
      await panel.click("Run selected outages");
      await panel.flush();
      assert.equal(cascadeCalls, 0, `a cascade ran on edit_hash ${JSON.stringify(editHash)}`);
      assert.match(panel.text(), /Request failed: The server accepted the edit without an immutable edit hash\./);
      assert.doesNotMatch(panel.text(), /must-not-run/);
    } finally {
      await panel.dispose();
    }
  }
});

test("every rendered frame carries the server artifact it came from", async () => {
  const panel = await mount({
    elements: ONE_LINE,
    scenarioId: "uri_2021",
    hour: 3,
    defaultSelectedElementIds: ["line:7"],
    runCascade: async () => response("evidenced-run"),
  });
  try {
    await panel.click("Run selected outages");
    await panel.flush();
    // The run header names the model and the *labelled* network provenance.
    assert.match(panel.text(), /Model: dc_screening\. Network: synthetic \(ACTIVSg2000\)\./);
    assert.doesNotMatch(panel.text(), /synthetic_activsg2000/, "the raw machine token must not be shown as prose");
    // The artifact list names id, version, kind and reference.
    const artifacts = panel.dom.window.document.querySelector('ul[aria-label="Server artifacts backing this run"]');
    assert.ok(artifacts, "the result must list the artifacts it is bound to");
    assert.match(artifacts.textContent, /flux:cascade:uri_2021/);
    assert.match(artifacts.textContent, /version 3\.1\.0/);
    assert.match(artifacts.textContent, /twin\/cascade\.py::run_cascade/);

    // And every playback frame states the artifact id@version it traces to.
    await panel.click("Show stage 0");
    const stageZero = panel.dom.window.document.querySelector('section[aria-label="Cascade stage 0"]');
    assert.ok(stageZero, "stage 0 must render once it is shown");
    assert.match(stageZero.textContent, /Evidence: flux:cascade:uri_2021@3\.1\.0/);
    await panel.click("Show next stage");
    const stageTwo = panel.dom.window.document.querySelector('section[aria-label="Cascade stage 2"]');
    assert.ok(stageTwo, "stage 2 must render once it is shown");
    assert.match(stageTwo.textContent, /Evidence: flux:cascade:uri_2021@3\.1\.0/);
  } finally {
    await panel.dispose();
  }
});

test("a cascade result with no artifact provenance renders a named refusal, not a stage list", async () => {
  for (const provenance of [undefined, []]) {
    const panel = await mount({
      elements: ONE_LINE,
      scenarioId: "uri_2021",
      hour: 3,
      defaultSelectedElementIds: ["line:7"],
      runCascade: async () => response("unevidenced-run", { provenance }),
    });
    try {
      await panel.click("Run selected outages");
      await panel.flush();
      assert.match(panel.text(), /Unavailable · code insufficient_evidence/);
      assert.doesNotMatch(panel.text(), /unevidenced-run/, "an unevidenced envelope was rendered as a result");
      assert.equal(panel.dom.window.document.querySelector('section[aria-label="Server cascade result"]'), null);
      assert.equal(panel.dom.window.document.querySelector('section[aria-label="Cascade stage 0"]'), null);
    } finally {
      await panel.dispose();
    }
  }
});

test("a result the server marked unavailable is never treated as ready", async () => {
  const panel = await mount({
    elements: ONE_LINE,
    scenarioId: "uri_2021",
    hour: 3,
    defaultSelectedElementIds: ["line:7"],
    runCascade: async () => response("refused-run", {
      status: "unavailable",
      unavailable: { code: "invalid_prerequisite", reason: "The requested interactive edit is not available.", retryable: false },
    }),
  });
  try {
    await panel.click("Run selected outages");
    await panel.flush();
    // The machine `code` from the frozen `Unavailable` survives to the screen.
    assert.match(panel.text(), /Unavailable · code invalid_prerequisite: The requested interactive edit is not available\./);
    assert.doesNotMatch(panel.text(), /refused-run/);
    assert.equal(panel.dom.window.document.querySelector('section[aria-label="Server cascade result"]'), null);
  } finally {
    await panel.dispose();
  }
});

test("the stated budget is armed: a run that outlives it ends in a named state", async () => {
  const panel = await mount({
    elements: ONE_LINE,
    scenarioId: "uri_2021",
    hour: 3,
    budgetSeconds: 0.05,
    defaultSelectedElementIds: ["line:7"],
    runCascade: (request, signal) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    }),
  });
  try {
    await panel.click("Run selected outages");
    assert.match(panel.text(), /The server is solving the cascade/);
    await panel.wait(220);
    assert.match(panel.text(), /Request failed: The server did not return a cascade result within the stated 0\.05-second budget\./);
    assert.equal(panel.dom.window.document.querySelector('section[aria-label="Server cascade result"]'), null);
  } finally {
    await panel.dispose();
  }
});

test("an unreachable interactive route lands in a named unavailable state, not a blank panel", async () => {
  const panel = await mount({
    elements: ONE_LINE,
    scenarioId: "uri_2021",
    hour: 3,
    defaultSelectedElementIds: ["line:7"],
    runCascade: async () => {
      throw Object.assign(new Error("Unable to reach the service. Check your connection and try again."), {
        name: "InteractiveRequestError",
        kind: "unavailable",
      });
    },
  });
  try {
    await panel.click("Run selected outages");
    await panel.flush();
    assert.match(panel.text(), /Unavailable · code none supplied: Unable to reach the service\./);
  } finally {
    await panel.dispose();
  }
});

test.after(async () => {
  await rm(compiled.pathname, { force: true });
});
