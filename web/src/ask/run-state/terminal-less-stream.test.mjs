/** OQ-1, decided: a stream that ends without a terminal `done` XOR `error` is
 * `request_failed`.
 *
 * `docs/research/sse-event-schema.md` guarantees exactly one terminal event per
 * attempt -- never both, never neither -- so a silent close is the server
 * breaking its own contract. Without this rule the browser has no token for
 * that case: the run sits in `active` forever and `ChatDock` renders a bare
 * sentence. The rule and its reducer land here; no transport dispatches
 * `stream_closed` yet (FU-4, PR #252), so these assertions pin the whole chain the decision names, from the
 * reducer through the failure adapter to the frozen display copy, so that
 * dropping the rule, re-pointing it at `unavailable`, or losing the named code
 * each turns a specific row red rather than quietly degrading the screen.
 */
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = new URL("../../../", import.meta.url);
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-terminal-less-stream-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));

// One bundle over the three owners the rule crosses, compiled under the project
// tsconfig: the reducer that observes the close, the adapter that binds a cause
// to the frozen token, and the single owner of the display strings. Reading the
// copy from its owner means a divergence is a failure here, not a second
// spelling on the screen.
const bundle = join(outputDirectory, "entry.mjs");
await build({
  stdin: {
    contents: [
      'export * from "./src/ask/run-state/reducer";',
      'export { STREAM_ENDED_WITHOUT_TERMINAL } from "./src/ask/run-state/types";',
      'export { fromStreamClose, fromSseTerminalError, statusOf } from "./src/failure-states/adapters";',
      'export { STATUS_COPY } from "./src/source-truth";',
    ].join("\n"),
    resolveDir: fileURLToPath(webRoot),
    loader: "ts",
    sourcefile: "terminal-less-stream-test-entry.ts",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  absWorkingDir: fileURLToPath(webRoot),
  tsconfig: join(fileURLToPath(webRoot), "tsconfig.json"),
  outfile: bundle,
  logLevel: "silent",
});

const {
  createRunState,
  runReducer,
  streamFailureCode,
  STREAM_ENDED_WITHOUT_TERMINAL,
  fromStreamClose,
  fromSseTerminalError,
  statusOf,
  STATUS_COPY,
} = await import(pathToFileURL(bundle).href);

const identity = { attemptId: "attempt-current", contextRevision: "rev-current" };
const event = (type, seq, fields = {}) => ({ id: String(seq), v: 1, seq, type, ...fields });
const receive = (state, incoming) => runReducer(state, { type: "event", identity, event: incoming });
const close = (state, reason) => runReducer(state, { type: "stream_closed", identity, ...(reason ? { reason } : {}) });

/** A run that streamed real answer text and then simply stopped arriving. */
function streamedThenClosed(reason) {
  let state = receive(createRunState(identity), event("lifecycle", 1, { status: "started" }));
  state = receive(state, event("text", 2, { delta: "Site 4 scores " }));
  state = receive(state, event("text", 3, { delta: "highest on winter peak." }));
  assert.equal(state.phase, "active", "precondition: the run is mid-stream before the close");
  return close(state, reason);
}

test("a stream that closes after text frames with no terminal event is request_failed, with the named code", () => {
  const state = streamedThenClosed();

  // The rule itself: the run must not be left mid-stream.
  assert.equal(state.phase, "failed");
  assert.notEqual(state.phase, "active");
  assert.notEqual(state.phase, "idle");

  // The named code is preserved on the state, not thrown away.
  assert.equal(state.failureCode, STREAM_ENDED_WITHOUT_TERMINAL);
  assert.equal(state.failureCode, "stream_ended_without_terminal");
  assert.equal(streamFailureCode(state), "stream_ended_without_terminal");

  // The frozen machine token, via the same adapter every other failure uses.
  const surface = fromStreamClose({ reason: "eof" });
  assert.equal(statusOf(surface), "request_failed");
  assert.notEqual(statusOf(surface), "unavailable");
  assert.equal(surface.code, "stream_ended_without_terminal");

  // ... rendered as the Request-failed status copy, from its single owner.
  assert.equal(STATUS_COPY[statusOf(surface)], "Request failed");

  // The text already delivered is retained, not discarded or invented upon.
  assert.equal(state.text, "Site 4 scores highest on winter peak.");
  assert.equal(state.terminal, undefined, "the client must not fabricate a terminal event it never received");
});

test("every close reason -- eof, abort, network -- lands on the same frozen token and code", () => {
  for (const reason of ["eof", "abort", "network"]) {
    const state = streamedThenClosed(reason);
    assert.equal(state.phase, "failed", `${reason} must fail the run`);
    assert.equal(state.failureCode, STREAM_ENDED_WITHOUT_TERMINAL, `${reason} must keep the named code`);
    const surface = fromStreamClose({ reason });
    assert.equal(statusOf(surface), "request_failed", `${reason} must be request_failed`);
    assert.equal(surface.code, "stream_ended_without_terminal");
    assert.match(state.issues.at(-1).message, /terminal done or error/);
    // The reducer and the adapter must read the SAME copy, not two copies that
    // happen to contain the same five words: a regex cannot tell those apart,
    // so drifting one owner's string has to fail here.
    assert.equal(
      state.issues.at(-1).message,
      surface.message,
      `${reason}: the reducer and the failure adapter must report one string from one owner`,
    );
    assert.equal(state.issues.at(-1).kind, "stream_ended_without_terminal");
  }
  // The three reasons are distinguishable in prose without changing the token.
  const messages = new Set(["eof", "abort", "network"].map((reason) => fromStreamClose({ reason }).message));
  assert.equal(messages.size, 3);
});

test("a close after a real terminal event changes nothing -- the rule fires only on the contract break", () => {
  let completed = receive(createRunState(identity), event("lifecycle", 1, { status: "started" }));
  completed = receive(completed, event("done", 2, { status: "completed", verified: true, unverified_numbers: [] }));
  const afterDone = close(completed, "eof");
  assert.equal(afterDone.phase, "completed");
  assert.equal(afterDone.failureCode, undefined);
  assert.deepEqual(afterDone.issues, []);

  let failed = receive(createRunState(identity), event("lifecycle", 1, { status: "started" }));
  failed = receive(failed, event("error", 2, { status: "failed", error: { code: "unavailable", message: "Artifact missing.", retryable: true } }));
  const afterError = close(failed, "network");
  assert.equal(afterError.phase, "failed");
  assert.equal(afterError.terminal.error.code, "unavailable");
  // A server-declared `unavailable` keeps its own token; the silent-close rule
  // must not overwrite a cause the server did supply.
  assert.equal(afterError.failureCode, undefined);
  assert.equal(statusOf(fromSseTerminalError(afterError.terminal.error)), "unavailable");
});

test("a close while a cancel is only requested is still request_failed, because no terminal event confirmed it", () => {
  let state = receive(createRunState(identity), event("lifecycle", 1, { status: "started" }));
  state = runReducer(state, { type: "cancel_requested", identity });
  assert.equal(state.phase, "cancelling");
  state = close(state, "abort");
  assert.equal(state.phase, "failed");
  assert.notEqual(state.phase, "cancelled", "only a terminal error with code cancelled may report a confirmed cancellation");
  assert.equal(state.failureCode, STREAM_ENDED_WITHOUT_TERMINAL);
});

test("a close belonging to an older attempt cannot fail the current run", () => {
  const active = receive(createRunState(identity), event("lifecycle", 1, { status: "started" }));
  const state = runReducer(active, {
    type: "stream_closed",
    identity: { attemptId: "attempt-old", contextRevision: "rev-old" },
  });
  assert.equal(state.phase, "active");
  assert.equal(state.failureCode, undefined);
  assert.equal(state.issues[0].kind, "stale");
});
