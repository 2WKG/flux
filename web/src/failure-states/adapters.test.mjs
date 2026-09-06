import assert from "node:assert/strict";
import { build } from "esbuild";
import test from "node:test";

const root = new URL("../..", import.meta.url).pathname;
const bundle = await build({ entryPoints: [new URL("./adapters.ts", import.meta.url).pathname], bundle: true, format: "esm", platform: "node", write: false, absWorkingDir: root });
const { fromClientState } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString("base64")}`);

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
