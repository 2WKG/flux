/**
 * The interactive client against the body `copilot/interactive_routes.py`
 * actually returns. `_result()` documents it in as many words: the labelled
 * payload is returned UNWRAPPED, so the solver's own keys sit at the top level
 * beside `model_fidelity`, `network_provenance` and `limitations` — there is
 * no `data` member on the wire. A client that insisted on one would reject
 * every real response as invalid, which is why this file asserts the flat
 * shape rather than the shape an earlier draft of that route had.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import test from "node:test";

const here = new URL(".", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-interactive-client.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: 'export * from "./interactive-client";',
    resolveDir: here.pathname,
    loader: "ts",
    sourcefile: "interactive-client-test-entry.ts",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  packages: "external",
  outfile: compiled.pathname,
});
const {
  createInteractiveClient,
  INTERACTIVE_CASCADE_ROUTE,
  INTERACTIVE_SCENARIO_EDIT_ROUTE,
  toEnvelope,
} = await import(compiled.href);

/** `interactive_labels()` in `copilot/interactive_routes.py`, verbatim. */
const LABELS = {
  model_fidelity: "dc_screening",
  network_provenance: "synthetic (ACTIVSg2000)",
  limitations: ["a", "b", "c"],
};

function jsonResponse(body, ok = true) {
  return { ok, status: ok ? 200 : 500, headers: { get: () => null }, json: async () => body };
}

function transportReturning(body, ok = true) {
  const calls = [];
  return {
    calls,
    transport: async (route, options) => {
      calls.push({ route, options });
      return jsonResponse(body, ok);
    },
  };
}

test("the route's flat body is re-nested without inventing or dropping a field", () => {
  const envelope = toEnvelope({ ...LABELS, run_id: "run-1", tripped_element_ids: [], steps: 2 });
  assert.deepEqual(envelope.data, { run_id: "run-1", tripped_element_ids: [], steps: 2 });
  assert.equal(envelope.model_fidelity, "dc_screening");
  assert.equal(envelope.network_provenance, "synthetic (ACTIVSg2000)");
  assert.deepEqual(envelope.limitations, ["a", "b", "c"]);
  // The labels are lifted out of the payload, never left in it as data.
  assert.equal("model_fidelity" in envelope.data, false);
});

test("runCascade accepts the shipped route's unwrapped body", async () => {
  const cascade = { run_id: "run-9", lost_load_mw: 12, steps: 3, tripped_element_ids: [], counties_dark: [], critical_loads_lost: [] };
  const { transport, calls } = transportReturning({ ...LABELS, ...cascade });
  const client = createInteractiveClient(transport);
  const result = await client.runCascade(
    { element_ids: ["line:7"], scenario_id: "interactive", hour: 0, seed: 0 },
    AbortSignal.timeout(5_000),
  );
  assert.equal(calls[0].route, INTERACTIVE_CASCADE_ROUTE);
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(result.data, cascade);
  assert.equal(result.network_provenance, "synthetic (ACTIVSg2000)");
});

test("prepareEdit reads the edit hash out of the same unwrapped body", async () => {
  const { transport, calls } = transportReturning({ ...LABELS, edit_hash: "a".repeat(32), element_ids: ["line:7"], feasibility: [] });
  const client = createInteractiveClient(transport);
  const result = await client.prepareEdit(
    { base_scenario_id: "interactive", hour: 0, seed: 0, ops: [{ op: "outage", element_id: "line:7" }] },
    AbortSignal.timeout(5_000),
  );
  assert.equal(calls[0].route, INTERACTIVE_SCENARIO_EDIT_ROUTE);
  assert.equal(result.data.edit_hash, "a".repeat(32));
});

test("a body missing one of the three labels is refused by name, never rendered", async () => {
  const { transport } = transportReturning({ model_fidelity: "dc_screening", run_id: "run-9" });
  const client = createInteractiveClient(transport);
  await assert.rejects(
    () => client.runCascade({ element_ids: ["line:7"], scenario_id: "interactive", hour: 0, seed: 0 }, AbortSignal.timeout(5_000)),
    (error) => {
      assert.equal(error.name, "InteractiveRequestError");
      assert.equal(error.kind, "failed");
      return true;
    },
  );
});

test.after(async () => {
  await rm(compiled.pathname, { force: true });
});
