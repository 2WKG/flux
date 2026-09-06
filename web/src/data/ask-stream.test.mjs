import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-ask-stream-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
writeFileSync(join(outputDirectory, "package.json"), '{"type":"commonjs"}');
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/data/ask-stream.ts", "--target", "ES2022", "--module", "commonjs", "--moduleResolution", "node", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const askStreamModule = await import(pathToFileURL(join(outputDirectory, "data", "ask-stream.js")).href);
const reducerModule = await import(pathToFileURL(join(outputDirectory, "ask", "run-state", "reducer.js")).href);
const askStream = askStreamModule.default ?? askStreamModule;
const reducer = reducerModule.default ?? reducerModule;

const identity = { attemptId: "attempt-current", contextRevision: "revision-current" };
const body = { attempt_id: identity.attemptId, question: "What changed?", context: {}, history: [] };
const lifecycle = new TextEncoder().encode('data: {"id":"1","v":1,"seq":1,"type":"lifecycle","status":"started"}\n\n');

function clientFor(read) {
  let closed = 0;
  return {
    client: {
      async connect() {
        return {
          kind: "ready",
          data: {
            reader: { read, cancel: async () => undefined },
            decode: askStream.decodeFrame,
            close() { closed += 1; },
          },
        };
      },
    },
    closeCount: () => closed,
  };
}

test("a thrown idle or network read after lifecycle dispatches exactly one stream_closed outcome", async () => {
  let reads = 0;
  const connection = clientFor(async () => {
    reads += 1;
    if (reads === 1) return { done: false, value: lifecycle };
    throw new Error("socket closed while waiting for the next frame");
  });
  const observed = [];

  const outcome = await askStream.runAsk(body, identity, reducer.createRunState(identity), {
    client: connection.client,
    onState: (state) => observed.push(state),
  });

  assert.equal(outcome.state.phase, "failed");
  assert.equal(outcome.state.failureCode, "stream_ended_without_terminal");
  assert.equal(outcome.state.terminal, undefined);
  assert.equal(outcome.state.trace.length, 1);
  assert.equal(outcome.state.issues.at(-1).kind, "stream_ended_without_terminal");
  assert.equal(
    outcome.state.issues.filter((item) => item.kind === "stream_ended_without_terminal").length,
    1,
    "one failed reader produces one stream_closed outcome",
  );
  assert.equal(observed.at(-1), outcome.state, "the rendered closure state is published before runAsk resolves");
  assert.equal(connection.closeCount(), 1);
});
