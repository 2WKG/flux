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
      export { runAsk, INTERRUPTED_STREAM_MESSAGE } from "./src/data/ask-stream";
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
