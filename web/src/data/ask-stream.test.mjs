import assert from "node:assert/strict";
import test from "node:test";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = new URL("../../", import.meta.url);
const probe = new URL("../../node_modules/.cache/flux-ask-stream-interruption.mjs", import.meta.url);
await mkdir(new URL(".", probe), { recursive: true });
await build({
  stdin: {
    contents: `
      export { runAsk, decodeFrame, INTERRUPTED_STREAM_MESSAGE } from "./src/data/ask-stream";
      export { createRunState } from "./src/ask/run-state/reducer";
    `,
    resolveDir: fileURLToPath(root),
    loader: "tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  packages: "external",
  outfile: fileURLToPath(probe),
});
const api = await import(probe.href);

test("the SSE event line supplies the v1 frame discriminant", () => {
  const frame = `id: 3\nevent: tool_result\ndata: {"v":1,"seq":3,"call_id":"cascade:a","tool":"cascade","ok":true,"elapsed_ms":7,"result":{}}`;
  const decoded = api.decodeFrame(frame);
  assert.equal(decoded?.type, "tool_result");
  assert.equal(decoded?.tool, "cascade");
  const done = api.decodeFrame(`id: 5\nevent: done\ndata: {"v":1,"seq":5,"status":"completed","verified":true,"unverified_numbers":[]}`);
  assert.equal(done?.type, "done");
  assert.equal(done?.id, "5");
  const conflicting = api.decodeFrame(`id: 5\nevent: done\ndata: {"v":1,"seq":5,"type":"error","status":"completed","verified":true,"unverified_numbers":[]}`);
  assert.equal(conflicting, undefined);
});

test("a complete header-identified v1 wire transcript reaches done", async () => {
  const wire = [
    ["lifecycle", { v: 1, seq: 1, status: "started" }],
    ["tool_call", { v: 1, seq: 2, call_id: "cascade:wire", tool: "cascade", input: { element_ids: ["line:973"] } }],
    ["tool_result", { v: 1, seq: 3, call_id: "cascade:wire", tool: "cascade", ok: true, elapsed_ms: 7, result: { scene_action: { kind: "synthetic_cascade_current" } } }],
    ["text", { v: 1, seq: 4, delta: "Completed." }],
    ["done", { v: 1, seq: 5, status: "completed", verified: true, unverified_numbers: [] }],
  ].map(([event, data], index) => `id: ${index + 1}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(wire)); controller.close(); } });
  const client = {
    async connect() {
      return { kind: "ready", data: { reader: stream.getReader(), decode: api.decodeFrame, close() {} } };
    },
  };
  const identity = { attemptId: "attempt-wire-transcript-01", contextRevision: "current" };
  const outcome = await api.runAsk(
    { attempt_id: identity.attemptId, question: "run this", history: [] }, identity,
    api.createRunState(identity, "synthetic"), { client },
  );
  assert.equal(outcome.state.terminal?.type, "done");
  assert.equal(outcome.state.tools["cascade:wire"]?.result?.ok, true);
  assert.equal(outcome.state.text, "Completed.");
});

test("a production reader interruption becomes an explicit non-success terminal state", async () => {
  let closed = false;
  const client = {
    async connect() {
      return {
        kind: "ready",
        data: {
          reader: { async read() { throw new Error("socket reset"); } },
          decode() { return null; },
          close() { closed = true; },
        },
      };
    },
  };
  const identity = { attemptId: "attempt-interrupted-0001", contextRevision: "current" };
  const updates = [];
  const outcome = await api.runAsk(
    { attempt_id: identity.attemptId, question: "run this", history: [] },
    identity,
    api.createRunState(identity, "synthetic"),
    { client, onState: (state) => updates.push(state) },
  );

  assert.equal(closed, true);
  assert.equal(outcome.state.phase, "protocol_error");
  assert.equal(outcome.state.terminal, undefined);
  assert.match(outcome.state.issues.at(-1)?.message ?? "", /interrupted before a terminal/i);
  assert.equal(updates.at(-1)?.phase, "protocol_error");
  assert.match(api.INTERRUPTED_STREAM_MESSAGE, /partial/i);
});
