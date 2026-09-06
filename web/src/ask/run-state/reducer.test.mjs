import assert from "node:assert/strict";
import { build } from "esbuild";
import test from "node:test";

const entry = new URL("./reducer.ts", import.meta.url).pathname;
const bundle = await build({ entryPoints: [entry], bundle: true, format: "esm", platform: "node", write: false });
const reducer = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString("base64")}`);

const identity = { attemptId: "attempt-current", contextRevision: "rev-current" };
const event = (type, seq, fields = {}) => ({ id: String(seq), v: 1, seq, type, ...fields });
const started = () => event("lifecycle", 1, { status: "started" });
const call = () => event("tool_call", 2, { call_id: "opaque-call", tool: "score_site", input: { site_id: "site-1" } });
const result = () => event("tool_result", 3, { call_id: "opaque-call", tool: "score_site", ok: true, result: { site_id: "site-1" }, elapsed_ms: 12 });
const done = () => event("done", 4, { status: "completed", verified: true, unverified_numbers: [] });
const reduce = (state, action) => reducer.runReducer(state, action);
const receive = (state, incoming, run = identity) => reduce(state, { type: "event", identity: run, event: incoming });

test("preserves the serialized tool trace and only completes on done", () => {
  let state = reducer.createRunState(identity);
  for (const incoming of [started(), call(), result(), done()]) state = receive(state, incoming);
  assert.equal(state.phase, "completed");
  assert.equal(state.trace.length, 4);
  assert.equal(state.tools["opaque-call"].result.elapsed_ms, 12);
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
  state = receive(state, event("tool_result", 2, { call_id: "not-seen", tool: "sql", ok: false, error: { code: "timeout", message: "Timed out" }, elapsed_ms: 1 }));
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

/**
 * Payloads copied verbatim from docs/research/sse-event-schema.md v1 (the
 * `lifecycle`, `text`, `tool_call`, `tool_result`, `citation`, and `done`
 * examples). Only `seq` is renumbered so the excerpts form one contiguous
 * attempt, `id` is added because the parser supplies it from the SSE frame,
 * and the second tool pair carries a distinct `call_id` — every other key and
 * value is the document's own. This is the reality contract: if the reducer
 * reads names the document does not emit, the tools map keys on `undefined`
 * and two real calls collide into one entry.
 */
const specStream = [
  { v: 1, seq: 1, status: "started" },
  { v: 1, seq: 2, delta: "A county-level outage model " },
  { v: 1, seq: 3, call_id: "call_01J8...", tool: "score_site", input: { site_id: "site_tx_0007", unit_mw: 300, scenario_id: "uri_2021" } },
  { v: 1, seq: 4, call_id: "call_01J8...", tool: "score_site", ok: true, result: { site_id: "site_tx_0007", grid_value_score: 82.1 }, elapsed_ms: 124 },
  { v: 1, seq: 5, call_id: "call_02K9...", tool: "score_site", input: { site_id: "site_tx_0008", unit_mw: 300, scenario_id: "uri_2021" } },
  { v: 1, seq: 6, call_id: "call_02K9...", tool: "score_site", ok: false, error: { code: "timeout", message: "The site scoring tool did not finish in time." }, elapsed_ms: 20000 },
  { v: 1, seq: 7, citation_id: "cite_01J8...", doc: "10-cfr-part-100.pdf", title: "10 CFR Part 100", page: 12, chunk_id: "10cfr100-p12-c2", locator: "§ 100.10", excerpt: "…", url: null },
  { v: 1, seq: 8, status: "completed", verified: true, unverified_numbers: [], usage: { input_tokens: 1320, output_tokens: 241 } },
].map((payload, index) => ({
  id: String(payload.seq),
  type: ["lifecycle", "text", "tool_call", "tool_result", "tool_call", "tool_result", "citation", "done"][index],
  ...payload,
}));

test("applies the schema document's own payload keys: two documented tool calls stay two entries", () => {
  let state = reducer.createRunState(identity);
  for (const incoming of specStream) state = receive(state, incoming);
  assert.deepEqual(state.issues, []);
  assert.equal(state.phase, "completed");
  assert.equal(state.trace.length, specStream.length);
  assert.equal(Object.keys(state.tools).length, 2);
  assert.deepEqual(Object.keys(state.tools).sort(), ["call_01J8...", "call_02K9..."]);
  assert.equal(state.tools["call_01J8..."].result.ok, true);
  assert.equal(state.tools["call_01J8..."].result.elapsed_ms, 124);
  assert.equal(state.tools["call_02K9..."].result.ok, false);
  assert.equal(state.tools["call_02K9..."].result.error.code, "timeout");
  assert.equal(state.terminal.unverified_numbers.length, 0);
  assert.equal(state.text, "A county-level outage model ");
});

test("treats a text event with no delta as malformed instead of appending \"undefined\"", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = receive(state, event("text", 2, {}));
  assert.equal(state.text, "");
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.expectedSeq, 2);
  assert.equal(state.trace.length, 1);
  assert.equal(state.issues[0].kind, "malformed");
  assert.match(state.issues[0].message, /without a string delta/);
});

test("rejects a schema version this client does not read", () => {
  let state = reducer.createRunState(identity);
  state = receive(state, { ...started(), v: 2 });
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.trace.length, 0);
  assert.equal(state.expectedSeq, 1);
  assert.equal(state.issues[0].kind, "unsupported_version");
});

test("rejects a terminal error code outside the closed v1 set", () => {
  let state = receive(reducer.createRunState(identity), started());
  state = receive(state, event("error", 2, { status: "failed", error: { code: "totally_made_up", message: "Invented.", retryable: false } }));
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.terminal, undefined);
  assert.equal(state.trace.length, 1);
  assert.equal(state.issues[0].kind, "invalid_error_code");
});

test("rejects a text delta over the 4 KiB v1 limit without appending it", () => {
  let state = receive(reducer.createRunState(identity), started());
  const oversize = "x".repeat(4 * 1024 + 1);
  state = receive(state, event("text", 2, { delta: oversize }));
  assert.equal(state.text, "");
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.issues[0].kind, "limit_exceeded");

  let atLimit = receive(reducer.createRunState(identity), started());
  atLimit = receive(atLimit, event("text", 2, { delta: "y".repeat(4 * 1024) }));
  assert.equal(atLimit.text.length, 4 * 1024);
  assert.equal(atLimit.phase, "active");
});

test("rejects an attempt that runs past the 1,000-event v1 limit", () => {
  let state = receive(reducer.createRunState(identity), started());
  for (let seq = 2; seq <= 1000; seq += 1) state = receive(state, event("text", seq, { delta: "." }));
  assert.equal(state.trace.length, 1000);
  assert.equal(state.phase, "active");
  assert.deepEqual(state.issues, []);

  state = receive(state, event("text", 1001, { delta: "over" }));
  assert.equal(state.trace.length, 1000);
  assert.equal(state.text.length, 999);
  assert.equal(state.phase, "protocol_error");
  assert.equal(state.issues[0].kind, "limit_exceeded");
});
