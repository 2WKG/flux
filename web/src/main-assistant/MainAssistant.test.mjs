// The page component is intentionally narrow: it consumes validated `/ask`
// state, keeps trace/error facts visible, and never turns generic response
// data into a scene mutation. These are SSR checks so they exercise no model,
// provider, browser transport, or scene runtime.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
// The seam derives availability from the additive `tool_result.result.scene_action`
// envelope -- the one field a real /ask frame actually carries. The earlier
// revision of this block keyed on `ToolOutput.status`, which `copilot/narration.py`
// strips before the result is emitted, so both of its arms were unreachable in
// production. The captured-frame test below is what keeps this honest.
// ---------------------------------------------------------------------------

test("reads its argument: the declared scene_action envelope decides availability", () => {
  const sceneAction = (fields) => state([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "cascade-call", tool: "cascade", input: {} }),
    event("tool_result", 3, {
      call_id: "cascade-call",
      tool: "cascade",
      ok: true,
      elapsed_ms: 12,
      result: { scene_action: { action_id: "action-7", kind: "cascade", tool_call_id: "cascade-call", reversible: true, status: "available", ...fields } },
    }),
    event("done", 4, { status: "completed", verified: true, unverified_numbers: [] }),
  ]);

  // With its own run identity the action is available, and the helper says which kind.
  const withIdentity = sceneAction({ cascade_id: "cascade-1" });
  const available = api.sceneActionAvailability(withIdentity);
  assert.equal(available.availability, "available");
  assert.equal(available.action.kind, "cascade");
  assert.equal(available.result.call_id, "cascade-call");
  const availableMarkup = api.render(props(withIdentity));
  assert.match(availableMarkup, /data-scene-action-availability="available"/);
  assert.match(availableMarkup, /cascade action supplied by tool result cascade-call/);

  // The same envelope without the identity its kind requires stays unavailable, so the
  // two states are distinguishable and neither is hardcoded.
  const withoutIdentity = sceneAction({ edit_hash: "an-edit-is-not-a-run" });
  const refused = api.sceneActionAvailability(withoutIdentity);
  assert.equal(refused.availability, "unavailable", "an envelope missing its identity must never be available");
  // The adapter marked this envelope unavailable itself, so the seam reports the
  // producer's own reason rather than collapsing it into "nothing arrived". That
  // is what keeps the `declared_unavailable_by_received_tool_output` arm
  // reachable instead of dead.
  assert.equal(refused.reason, "declared_unavailable_by_received_tool_output");
  assert.match(refused.declined.reason, /no stable cascade_id/);
  const refusedMarkup = api.render(props(withoutIdentity));
  assert.match(refusedMarkup, /data-scene-action-availability="unavailable"/);
  // The raw trace still shows the received payload; the scene-action section must not
  // turn that edit hash into an available cascade.
  assert.doesNotMatch(refusedMarkup, /cascade action supplied by tool result/);
});

// ---------------------------------------------------------------------------
// NON-VACUITY (decisions 20 and 31). The two tests above are hand-written. This
// one is not: `capture-ask-scene-action.mjs` boots the REAL FastAPI app over
// real HTTP (uvicorn, real ToolDispatcher, real interactive service, real
// CopilotEventStream) and records the frames it emits into
// `fixtures/ask-scene-action-frames.json`. Feeding those recorded frames
// through the real reducer must reach the available arm, or the seam reads a
// field the server does not send.
// ---------------------------------------------------------------------------

test("a captured real /ask stream reaches the available arm", () => {
  const captured = JSON.parse(
    readFileSync(path.join(webRoot, "src/main-assistant/fixtures/ask-scene-action-frames.json"), "utf8"),
  );
  assert.ok(captured.frames.length >= 4, "the capture is empty; re-run capture-ask-scene-action.mjs");
  const toolResult = captured.frames.find((frame) => frame.type === "tool_result");
  assert.ok(toolResult, "the captured stream carried no tool_result frame");
  // The field the seam reads has to be in the bytes the server sent.
  assert.ok(toolResult.result.scene_action, "the captured tool_result carries no scene_action envelope");

  const capturedIdentity = { attemptId: captured.attempt_id, contextRevision: "scene-r1" };
  const run = captured.frames.reduce(
    (current, incoming) => stateApi.runReducer(current, { type: "event", identity: capturedIdentity, event: incoming }),
    stateApi.createRunState(capturedIdentity, "source_supported"),
  );
  const availability = api.sceneActionAvailability(run);
  assert.equal(availability.availability, "available", "a real captured frame does not reach the available arm");
  assert.equal(availability.action.kind, "cascade");
  assert.equal(availability.result.call_id, toolResult.call_id);

  const markup = api.render({
    ...props(run),
    chat: { ...props(run).chat, attemptId: capturedIdentity.attemptId, contextRevision: "scene-r1" },
  });
  assert.match(markup, /data-scene-action-availability="available"/);
  assert.match(markup, /cascade action supplied by tool result/);
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

test("a caller-directed abort declares the close instead of leaving the run streaming", async () => {
  // The review of #364 proved this by driving the real `runAsk` with an aborted
  // signal: the promise rejected and `onState` was never called once, so the run
  // kept its `active` phase and `chatStatusForRun` reported `streaming` forever
  // while three documents said the close was dispatched "on every EOF, abort,
  // and broken read". This drives a REAL AbortController through the REAL
  // transport; deleting the dispatch at `src/data/ask-stream.ts` turns it red.
  const controller = new AbortController();
  const identity3 = { attemptId: "attempt_abcdef0123456789", contextRevision: "scene-r1" };
  let observed = api.createRunState(identity3, "source_supported");
  let calls = 0;

  const abortingClient = {
    async connect() {
      return {
        kind: "ready",
        data: {
          reader: {
            async read() {
              if (calls === 0) {
                calls += 1;
                return { done: false, value: lifecycleFrame };
              }
              // What a real fetch body does when its signal aborts mid-read.
              controller.abort();
              const error = new Error("The operation was aborted.");
              error.name = "AbortError";
              throw error;
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

  await assert.rejects(
    api.runAsk(
      { attempt_id: identity3.attemptId, question: "What changed?", context: {}, history: [] },
      identity3,
      observed,
      {
        client: abortingClient,
        signal: controller.signal,
        onState: (next) => { observed = next; },
      },
    ),
    /aborted/i,
    "the caller must still receive the rejection",
  );

  // The rejection is not the whole contract: the close has to have been declared.
  assert.equal(observed.phase, "failed", "an aborted run must not stay active/streaming");
  assert.equal(observed.failureCode, "stream_ended_without_terminal");
  assert.notEqual(api.chatStatusForRun(observed), "streaming");
  const aborted = observed.issues.find((issue) => issue.kind === "stream_ended_without_terminal");
  assert.ok(aborted, "the abort close was never recorded as an issue");
  // The reason travels with the close, so abort is distinguishable from EOF.
  assert.match(aborted.message, /aborted before the required terminal/);
});

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
