// The page component is intentionally narrow: it consumes validated `/ask`
// state, keeps trace/error facts visible, and never turns generic response
// data into a scene mutation. These are SSR checks so they exercise no model,
// provider, browser transport, or scene runtime.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(fileURLToPath(new URL("../../package.json", import.meta.url)));
const componentPath = path.join(webRoot, "src/main-assistant/MainAssistant.tsx");
const reducerPath = path.join(webRoot, "src/ask/run-state/reducer.ts");

async function component() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-480-main-assistant-"));
  const entry = path.join(directory, "entry.tsx");
  const output = path.join(directory, "entry.mjs");
  await writeFile(entry, `
    import { renderToStaticMarkup } from "react-dom/server";
    export { chatStatusForRun, chatErrorForRun, sceneActionAvailability, streamCloseFailure } from ${JSON.stringify(componentPath)};
    export { runAsk } from ${JSON.stringify(path.join(webRoot, "src/data/ask-stream.ts"))};
    export { createRunState } from ${JSON.stringify(path.join(webRoot, "src/ask/run-state/reducer.ts"))};
    import { MainAssistant } from ${JSON.stringify(componentPath)};
    export const render = (props) => renderToStaticMarkup(<MainAssistant {...props} />);
  `, "utf8");
  await build({
    entryPoints: [entry], outfile: output, bundle: true, format: "esm", platform: "node", target: "node20",
    absWorkingDir: webRoot, nodePaths: [path.join(webRoot, "node_modules")], tsconfig: path.join(webRoot, "tsconfig.json"),
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
    loader: { ".css": "empty" }, logLevel: "silent",
  });
  try {
    return await import(pathToFileURL(output).href);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

async function reducer() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-480-main-assistant-reducer-"));
  const output = path.join(directory, "reducer.mjs");
  await build({
    entryPoints: [reducerPath], outfile: output, bundle: true, format: "esm", platform: "node", target: "node20",
    absWorkingDir: webRoot, nodePaths: [path.join(webRoot, "node_modules")], tsconfig: path.join(webRoot, "tsconfig.json"), logLevel: "silent",
  });
  try {
    return await import(pathToFileURL(output).href);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

const api = await component();
const stateApi = await reducer();
const identity = { attemptId: "attempt_0123456789abcdef", contextRevision: "scene-r1" };
const event = (type, seq, fields = {}) => ({ id: String(seq), v: 1, seq, type, ...fields });

function state(events) {
  return events.reduce((current, incoming) => stateApi.runReducer(current, { type: "event", identity, event: incoming }), stateApi.createRunState(identity, "source_supported"));
}

function props(run) {
  return {
    run,
    chat: {
      contextRevision: identity.contextRevision,
      context: { scenario_id: null, hour: null, selected_site_id: null, compare_site_id: null, selected_element_id: null, unit_mw: null },
      attemptId: identity.attemptId,
      sourceLabel: "Test scene",
      sourceStatus: "source_supported",
      messages: [],
    },
  };
}

test("shows received tool trace and verified grounding without inferring a scene action", () => {
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "call-1", tool: "score_site", input: { site_id: "site-1" } }),
    event("tool_result", 3, { call_id: "call-1", tool: "score_site", ok: true, result: { site_id: "site-1", score: 82.1, scene_action: "untrusted" }, elapsed_ms: 12 }),
    event("done", 4, { status: "completed", verified: true, unverified_numbers: [] }),
  ]);
  const markup = api.render(props(run));
  assert.match(markup, /Verified against the received tool results and citations/);
  assert.match(markup, /score_site: completed/);
  assert.match(markup, /data-scene-action-availability="unavailable"/);
  assert.match(markup, /absent_from_received_ask_event_data/);
  assert.match(markup, /No scene action is available/);
  assert.doesNotMatch(markup, /Scene action supplied by tool result/);
  assert.deepEqual(api.sceneActionAvailability(run), { availability: "unavailable", reason: "absent_from_received_ask_event_data" });
});

test("passes an unavailable terminal through to the dock and does not replace it with a result", () => {
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "call-2", tool: "top_lines", input: { region: "TX" } }),
    event("tool_result", 3, { call_id: "call-2", tool: "top_lines", ok: false, error: { code: "unavailable", message: "The artifact is missing." }, elapsed_ms: 2 }),
    event("error", 4, { status: "failed", error: { code: "unavailable", message: "The local Copilot backend is not configured.", retryable: false } }),
  ]);
  const markup = api.render(props(run));
  assert.equal(api.chatStatusForRun(run), "error");
  assert.deepEqual(api.chatErrorForRun(run), { code: "unavailable", message: "The local Copilot backend is not configured.", retryable: false });
  assert.match(markup, /Unavailable\./);
  assert.match(markup, /The local Copilot backend is not configured/);
  assert.match(markup, /top_lines: failed/);
  assert.match(markup, /No answer or scene action was inferred/);
  assert.doesNotMatch(markup, /Answer complete/);
});

test("does not fabricate a protocol error into a server terminal payload", () => {
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("text", 3, { delta: "out of order" }),
  ]);
  assert.equal(run.phase, "protocol_error");
  assert.equal(api.chatStatusForRun(run), "error");
  assert.equal(api.chatErrorForRun(run), undefined);
  const markup = api.render(props(run));
  assert.match(markup, /did not supply a terminal error event/);
  assert.match(markup, /Expected event 2, received 3/);
});

// ---------------------------------------------------------------------------
// The seam derives availability from the tool contract, so both arms are real.
// ---------------------------------------------------------------------------

/** A contract-shaped `score_site` output (`src/contracts/copilot-tools.d.ts`). */
const siteScore = (status, extra = {}) => ({
  status,
  site_id: "site-1",
  scenario_id: "uri_2021",
  unit_mw: 300,
  name: "Probe site",
  kind: "substation",
  county_fips: "48001",
  grid_value_score: 82.1,
  safety_score: 4,
  safety_flags: [],
  regulatory_path: "interconnection",
  lol_reduction_mwh: 12,
  congestion_relief_pct: 3,
  blackstart_reach_mw: 40,
  critical_loads_protected: [],
  ...extra,
});

test("a received tool output that declares contract status available reaches the available arm", () => {
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "call-9", tool: "score_site", input: { site_id: "site-1" } }),
    event("tool_result", 3, { call_id: "call-9", tool: "score_site", ok: true, result: siteScore("available"), elapsed_ms: 9 }),
    event("done", 4, { status: "completed", verified: true, unverified_numbers: [] }),
  ]);
  const availability = api.sceneActionAvailability(run);
  assert.equal(availability.availability, "available");
  assert.equal(availability.status, "available");
  assert.equal(availability.result.call_id, "call-9");
  const markup = api.render(props(run));
  assert.match(markup, /data-scene-action-availability="available"/);
  assert.match(markup, /data-scene-action-call="call-9"/);
  assert.doesNotMatch(markup, /data-scene-action-reason=/);
  assert.match(markup, /Scene evidence available from tool result call-9/);
  // Reachable is not the same as over-claiming: v1 still has no action envelope.
  assert.match(markup, /The action itself is still not inferred/);
});

test("a received tool output that declares itself unavailable is reported with the producer's own reason", () => {
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "call-8", tool: "score_site", input: { site_id: "site-1" } }),
    event("tool_result", 3, {
      call_id: "call-8", tool: "score_site", ok: true, elapsed_ms: 4,
      result: siteScore("unavailable", { unavailable: { code: "artifact_unavailable", reason: "The scoring artifact is not published." } }),
    }),
    event("done", 4, { status: "completed", verified: false, unverified_numbers: ["grid_value_score"] }),
  ]);
  const availability = api.sceneActionAvailability(run);
  assert.equal(availability.availability, "unavailable");
  assert.equal(availability.reason, "declared_unavailable_by_received_tool_output");
  assert.equal(availability.unavailable.code, "artifact_unavailable");
  const markup = api.render(props(run));
  assert.match(markup, /data-scene-action-reason="declared_unavailable_by_received_tool_output"/);
  assert.match(markup, /The scoring artifact is not published/);
});

test("a result without the contract's own status field cannot reach the available arm", () => {
  // The adversarial fixture: a plausible-looking payload with a planted
  // `scene_action` and `status: "ok"`, which is not a `ToolStatus`.
  const run = state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "call-7", tool: "score_site", input: {} }),
    event("tool_result", 3, { call_id: "call-7", tool: "score_site", ok: true, elapsed_ms: 1, result: { status: "ok", scene_action: "pan_to", site_id: "site-1" } }),
  ]);
  assert.deepEqual(api.sceneActionAvailability(run), { availability: "unavailable", reason: "absent_from_received_ask_event_data" });
});

// ---------------------------------------------------------------------------
// OQ-1 end to end: the live transport's own `stream_closed` dispatch, through
// the reducer, to the rendered `request_failed` surface. Dropping the dispatch
// in `src/data/ask-stream.ts` OR dropping `streamCloseFailure` from the render
// turns this red.
// ---------------------------------------------------------------------------

const lifecycleFrame = new TextEncoder().encode('data: {"id":"1","v":1,"seq":1,"type":"lifecycle","status":"started"}\n\n');

function streamThatEndsWithout(terminalReads) {
  let index = 0;
  return {
    async connect() {
      return {
        kind: "ready",
        data: {
          reader: {
            async read() {
              const step = terminalReads[index];
              index += 1;
              if (step === undefined) return { done: true, value: undefined };
              if (step === "throw") throw new Error("the socket closed before a terminal frame");
              return { done: false, value: step };
            },
            cancel: async () => undefined,
          },
          decode: (frame) => {
            const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
            return data === "" ? null : JSON.parse(data);
          },
          close() {},
        },
      };
    },
  };
}

for (const [name, reads] of [["EOF", [lifecycleFrame]], ["a broken read", [lifecycleFrame, "throw"]]]) {
  test(`a stream that ends on ${name} without a terminal event renders request_failed`, async () => {
    const identity2 = { attemptId: "attempt_fedcba9876543210", contextRevision: "scene-r1" };
    const { state: run } = await api.runAsk(
      { attempt_id: identity2.attemptId, question: "What changed?", context: {}, history: [] },
      identity2,
      api.createRunState(identity2, "source_supported"),
      { client: streamThatEndsWithout(reads) },
    );
    // The transport, not the test, is what declared the close.
    assert.equal(run.phase, "failed");
    assert.equal(run.terminal, undefined);
    assert.equal(run.failureCode, "stream_ended_without_terminal");

    const markup = api.render({ ...props(run), chat: { ...props(run).chat, attemptId: identity2.attemptId, contextRevision: identity2.contextRevision } });
    // The frozen machine token and the named cause, not a bare sentence.
    assert.match(markup, /data-request-status="request_failed"/);
    assert.match(markup, /data-request-code="stream_ended_without_terminal"/);
    assert.match(markup, /required terminal done or error event/);
    assert.notEqual(api.streamCloseFailure(run), undefined);
    assert.equal(api.chatStatusForRun(run), "error");
  });
}

// ---------------------------------------------------------------------------
// The overlay is narrow: the caller may only speak before the reducer has.
// ---------------------------------------------------------------------------

test("the caller's request overlay is only heard while the run is idle", () => {
  const idle = state([]);
  assert.equal(api.chatStatusForRun(idle), "idle");
  assert.equal(api.chatStatusForRun(idle, { pending: true }), "streaming");
  assert.equal(api.chatStatusForRun(idle, { connectionError: { code: "unavailable", message: "No stream." } }), "error");
  assert.deepEqual(api.chatErrorForRun(idle, { connectionError: { code: "unavailable", message: "No stream." } }), { code: "unavailable", message: "No stream." });

  const done = state([
    event("lifecycle", 1, { status: "started" }),
    event("done", 2, { status: "completed", verified: true, unverified_numbers: [] }),
  ]);
  assert.equal(api.chatStatusForRun(done, { connectionError: { code: "unavailable", message: "No stream." } }), "done");
  assert.equal(api.chatErrorForRun(done, { connectionError: { code: "unavailable", message: "No stream." } }), undefined);
});
