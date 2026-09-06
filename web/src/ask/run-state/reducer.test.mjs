import assert from "node:assert/strict";
import { build } from "esbuild";
import test from "node:test";

const entry = new URL("./reducer.ts", import.meta.url).pathname;
const bundle = await build({ entryPoints: [entry], bundle: true, format: "esm", platform: "node", write: false });
const reducer = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString("base64")}`);

const identity = { attemptId: "attempt-current", contextRevision: "rev-current" };
const event = (type, seq, fields = {}) => ({ id: String(seq), v: 1, seq, type, ...fields });
const started = () => event("lifecycle", 1, { status: "started" });
const call = () => event("tool_call", 2, { callId: "opaque-call", tool: "score_site", input: { site_id: "site-1" } });
const result = () => event("tool_result", 3, { callId: "opaque-call", tool: "score_site", ok: true, result: { site_id: "site-1" }, elapsedMs: 12 });
const done = () => event("done", 4, { status: "completed", verified: true, unverifiedNumbers: [] });
const reduce = (state, action) => reducer.runReducer(state, action);
const receive = (state, incoming, run = identity) => reduce(state, { type: "event", identity: run, event: incoming });

test("preserves the serialized tool trace and only completes on done", () => {
  let state = reducer.createRunState(identity);
  for (const incoming of [started(), call(), result(), done()]) state = receive(state, incoming);
  assert.equal(state.phase, "completed");
  assert.equal(state.trace.length, 4);
  assert.equal(state.tools["opaque-call"].result.elapsedMs, 12);
  assert.equal(state.expectedSeq, 5);
});

test("does not reorder a gap or fabricate a trace", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = receive(state, event("text", 3, { delta: "late" }));
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.text, "");
  assert.equal(state.trace.length, 1);
  assert.match(state.issues[0].message, /Expected event 2/);
});

test("rejects another attempt or scene revision as stale without advancing this run", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = receive(state, call(), { attemptId: "attempt-old", contextRevision: "rev-old" });
  assert.equal(state.phase, "active");
  assert.equal(state.expectedSeq, 2);
  assert.equal(state.trace.length, 1);
  assert.equal(state.issues[0].kind, "stale");
});

test("makes cancellation a request until the server confirms cancelled", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = reduce(state, { type: "cancel_requested", identity });
  assert.equal(state.phase, "cancelling");
  state = receive(state, event("error", 2, { status: "failed", error: { code: "cancelled", message: "Cancelled by request.", retryable: false } }));
  assert.equal(state.phase, "cancelled");
  assert.equal(state.terminal.error.code, "cancelled");
});

test("keeps mismatched calls and post-terminal events explicit", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = receive(state, event("tool_result", 2, { callId: "not-seen", tool: "sql", ok: false, error: { code: "timeout", message: "Timed out" }, elapsedMs: 1 }));
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.issues[0].kind, "unknown_call");

  let terminal = reducer.createRunState(identity);
  for (const incoming of [started(), call(), result(), done()]) terminal = receive(terminal, incoming);
  terminal = receive(terminal, event("text", 5, { delta: "must not append" }));
  assert.equal(terminal.text, "");
  assert.equal(terminal.issues[0].kind, "after_terminal");
});

test("surfaces unavailable as the supplied error and never converts it to a result", () => {
  let state = reducer.createRunState(identity, "unavailable");
  state = receive(state, started());
  state = receive(state, event("error", 2, { status: "failed", error: { code: "unavailable", message: "The source is unavailable.", retryable: true } }));
  assert.equal(state.sourceStatus, "unavailable");
  assert.equal(state.phase, "failed");
  assert.equal(reducer.terminalError(state).error.code, "unavailable");
});

test("keeps the supplied source truth label current without changing the trace", () => {
  let state = receive(reducer.createRunState(identity, "source_supported"), started());
  state = reduce(state, { type: "source_status", identity, sourceStatus: "hypothetical" });
  assert.equal(state.sourceStatus, "hypothetical");
  assert.equal(state.trace.length, 1);
  assert.equal(state.expectedSeq, 2);
});
