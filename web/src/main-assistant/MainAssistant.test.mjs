// The page component is intentionally narrow: it consumes validated `/ask`
// state, keeps trace/error facts visible, and never turns generic response
// data into a scene mutation. These are SSR checks so they exercise no model,
// provider, browser transport, or scene runtime.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const componentPath = path.join(webRoot, "src/main-assistant/MainAssistant.tsx");
const reducerPath = path.join(webRoot, "src/ask/run-state/reducer.ts");

async function component() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-480-main-assistant-"));
  const entry = path.join(directory, "entry.tsx");
  const output = path.join(directory, "entry.mjs");
  await writeFile(entry, `
    import { renderToStaticMarkup } from "react-dom/server";
    export { chatStatusForRun, chatErrorForRun, sceneActionAvailability } from ${JSON.stringify(componentPath)};
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
  assert.deepEqual(api.sceneActionAvailability(withoutIdentity), { availability: "unavailable", reason: "absent_from_received_ask_event_data" });
  const refusedMarkup = api.render(props(withoutIdentity));
  assert.match(refusedMarkup, /data-scene-action-availability="unavailable"/);
  // The raw trace still shows the received payload; the scene-action section must not
  // turn that edit hash into an available cascade.
  assert.doesNotMatch(refusedMarkup, /cascade action supplied by tool result/);
});
