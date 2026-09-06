import assert from "node:assert/strict";
import { build } from "esbuild";
import test from "node:test";

const root = new URL("../..", import.meta.url).pathname;
const bundle = await build({ entryPoints: [new URL("./adapters.ts", import.meta.url).pathname], bundle: true, format: "esm", platform: "node", write: false, absWorkingDir: root });
const { fromClientState, fromSseTerminalError, fromStreamClose, statusOf } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString("base64")}`);

test("maps client outcomes without converting them to ready data", () => {
  assert.deepEqual(fromClientState({ kind: "loading" }), { kind: "loading", retainedContext: undefined });
  assert.deepEqual(fromClientState({ kind: "empty" }, "Scene A"), { kind: "empty", retainedContext: "Scene A" });
  assert.deepEqual(fromClientState({ kind: "unavailable", source: "server", message: "Artifact is unavailable.", retryAfterSeconds: 30, requestId: "opaque" }), { kind: "unavailable", message: "Artifact is unavailable.", retryAfterSeconds: 30, retainedContext: undefined });
  assert.deepEqual(fromClientState({ kind: "invalid", reason: "malformed_response", message: "Response invalid." }), { kind: "malformed", message: "Response invalid.", retainedContext: undefined });
  assert.deepEqual(fromClientState({ kind: "invalid", reason: "version_mismatch", message: "Version unsupported." }), { kind: "version_mismatch", message: "Version unsupported.", retainedContext: undefined });
  assert.deepEqual(fromClientState({ kind: "failed", source: "network", message: "Offline" }), { kind: "network_failure", message: "Offline", retainedContext: undefined });
});

test("returns no failure surface for source-ready data", () => {
  assert.equal(fromClientState({ kind: "ready", data: { source: "real" } }), null);
});

test("client-side failure causes stay distinct instead of all reading 'connection failed'", () => {
  const cases = {
    unreachable: "network_failure",
    cancelled: "cancelled",
    timeout: "timeout",
    response_too_large: "oversized",
    invalid_options: "failed",
  };
  for (const [reason, kind] of Object.entries(cases)) {
    assert.equal(
      fromClientState({ kind: "failed", source: "network", reason, message: reason }).kind,
      kind,
      `network failure reason ${reason} must not be rendered as ${kind === "network_failure" ? "something else" : "network_failure"}`,
    );
  }
  // An unclassified network failure keeps the historical behaviour.
  assert.equal(fromClientState({ kind: "failed", source: "network", message: "Offline" }).kind, "network_failure");
  // Server failures are never reclassified by a client-side reason.
  assert.equal(fromClientState({ kind: "failed", source: "server", reason: "cancelled", message: "x" }).kind, "failed");
});

const SSE_V1_CODES = ["invalid_request", "unavailable", "deadline", "upstream_error", "tool_error", "refusal", "cancelled", "protocol_error"];
const labelsBundle = await build({ entryPoints: [new URL("../labels.ts", import.meta.url).pathname], bundle: true, format: "esm", platform: "node", write: false, absWorkingDir: root });
const { ASSET_STATUS_TOKENS } = await import(`data:text/javascript;base64,${Buffer.from(labelsBundle.outputFiles[0].contents).toString("base64")}`);
// Read the frozen set from its single definition, not a restatement.
const FROZEN_UI_STATUS = new Set(ASSET_STATUS_TOKENS);
assert.equal(FROZEN_UI_STATUS.size, 6);

test("every closed v1 SSE terminal code maps to a rendered failure with a frozen token", () => {
  for (const code of SSE_V1_CODES) {
    const mapped = fromSseTerminalError({ code, message: `m:${code}` });
    assert.ok(mapped, `${code} must map to a failure state`);
    assert.equal(mapped.code, code, `${code} must be preserved verbatim`);
    assert.equal(mapped.message, `m:${code}`);
    const status = statusOf(mapped);
    assert.ok(status !== null, `${code} is a terminal error and must assert a status`);
    assert.ok(FROZEN_UI_STATUS.has(status), `${code} emitted non-frozen token "${status}"`);
  }
  assert.equal(statusOf(fromSseTerminalError({ code: "unavailable" })), "unavailable");
  assert.equal(statusOf(fromSseTerminalError({ code: "deadline" })), "request_failed");
  assert.equal(fromSseTerminalError({ code: "deadline" }).kind, "timeout");
  assert.equal(fromSseTerminalError({ code: "cancelled" }).kind, "cancelled");
  assert.equal(fromSseTerminalError({ code: "protocol_error" }).kind, "malformed");
});

test("the eight v1 codes map to distinct-enough causes, not one collapsed bucket", () => {
  const kinds = new Set(SSE_V1_CODES.map((code) => fromSseTerminalError({ code }).kind));
  assert.ok(kinds.size >= 4, `expected the code set to preserve its distinctions, got ${[...kinds].join(",")}`);
});

test("an unlisted SSE code becomes request_failed with the raw code kept, never a plausible default", () => {
  const mapped = fromSseTerminalError({ code: "quota_exhausted", message: "Quota exhausted." });
  assert.equal(mapped.code, "quota_exhausted");
  assert.equal(statusOf(mapped), "request_failed");
  assert.equal(mapped.kind, "failed");
  // It must not be silently absorbed into any of the known causes.
  for (const code of SSE_V1_CODES) {
    if (code === "invalid_request" || code === "upstream_error" || code === "tool_error" || code === "refusal") continue;
    assert.notEqual(mapped.kind, fromSseTerminalError({ code }).kind, `unknown code must not become ${code}`);
  }
  assert.equal(fromSseTerminalError({ code: "unavailable" }).code, "unavailable");
});

test("a stream that closed without a terminal event is request_failed with the named code, never unavailable", () => {
  // OQ-1, decided (docs/specs/spec-code-reconciliation.md): the schema promises
  // exactly one terminal event, so a silent close is a broken contract and the
  // request is what failed -- nothing said a dependency was missing.
  for (const reason of ["eof", "abort", "network"]) {
    const mapped = fromStreamClose({ reason });
    assert.equal(statusOf(mapped), "request_failed", `${reason} must be request_failed`);
    assert.notEqual(statusOf(mapped), "unavailable", `${reason} must not be reported as unavailable`);
    assert.equal(mapped.code, "stream_ended_without_terminal", `${reason} must carry the named code`);
    assert.ok(mapped.message, `${reason} must carry a cause the screen can show`);
  }
  // A default close is still a named failure, not an unlabelled one.
  const fallback = fromStreamClose();
  assert.equal(statusOf(fallback), "request_failed");
  assert.equal(fallback.code, "stream_ended_without_terminal");
  // The server supplied no retry advice, so the adapter invents none.
  assert.equal(fallback.retryAfterSeconds, undefined);
  // It must not be confused with the server's own `unavailable` terminal error.
  assert.notEqual(fallback.code, fromSseTerminalError({ code: "unavailable" }).code);
});

test("no adapter output can emit a status token outside the frozen Gate-0 set", () => {
  const inputs = [
    fromClientState({ kind: "unavailable", source: "server", message: "u", retryAfterSeconds: null, requestId: "r" }),
    fromClientState({ kind: "invalid", reason: "version_mismatch", message: "v" }),
    fromClientState({ kind: "invalid", reason: "malformed_response", message: "m" }),
    ...["unreachable", "cancelled", "timeout", "response_too_large", "invalid_options"].map((reason) =>
      fromClientState({ kind: "failed", source: "network", reason, message: reason })),
    fromClientState({ kind: "failed", source: "server", message: "s" }),
    ...SSE_V1_CODES.map((code) => fromSseTerminalError({ code })),
    fromSseTerminalError({ code: "not_a_v1_code" }),
    ...["eof", "abort", "network"].map((reason) => fromStreamClose({ reason })),
  ];
  for (const input of inputs) {
    const status = statusOf(input);
    assert.ok(status !== null, `${input.kind} is a failure and must assert a frozen token`);
    assert.ok(FROZEN_UI_STATUS.has(status), `${input.kind} emitted non-frozen token "${status}"`);
  }
  // The non-outcome states assert no request status at all.
  for (const state of [{ kind: "loading" }, { kind: "empty" }]) {
    assert.equal(statusOf(fromClientState(state)), null);
  }
});
