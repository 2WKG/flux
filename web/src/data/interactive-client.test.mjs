// The fixtures in this file are not written by hand: they are read from
// `src/contracts/interactive-payloads.json`, which
// `scripts/ci/export_interactive_contracts.py` produces by *running* the real
// producers (`twin/balance.py`, `siting/redundancy.py`). The previous version
// of this file invented a camelCase contract no producer emits, so the guards
// were green against a shape that would have rejected 100% of real responses.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = new URL("../../", import.meta.url);
const outputDirectory = mkdtempSync(join(tmpdir(), "flux-interactive-client-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/data/transport.ts", "src/data/validation.ts", "src/data/client-state.ts", "src/data/interactive-client.ts",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--outDir", outputDirectory,
], { cwd: fileURLToPath(webRoot), stdio: "inherit" });

const {
  INTERACTIVE_ROOTS, createInteractiveClient, isBalanceWirePayload, isRedundancyWirePayload,
  toBalanceView, toRedundancyView,
} = await import(pathToFileURL(join(outputDirectory, "data", "interactive-client.js")).href);
const { API_VERSION, MALFORMED_RESPONSE_MESSAGE } = await import(
  pathToFileURL(join(outputDirectory, "data", "validation.js")).href,
);
const { SYNTHETIC_TOPOLOGY_LABEL } = await import(
  pathToFileURL(join(outputDirectory, "scene", "minnesota-adapter.js")).href,
);

/** Captured from the producers; regenerate with scripts/ci/export_interactive_contracts.py. */
export const CAPTURED = JSON.parse(
  readFileSync(new URL("../contracts/interactive-payloads.json", import.meta.url), "utf8"),
);
const balance = CAPTURED.routes["/interactive/balance"].response;
const redundancy = CAPTURED.routes["/interactive/redundancy"].response;

function unavailableEnvelope() {
  return {
    status: "unavailable", data: null,
    error: { code: "unavailable", message: "Balance service has not been mounted.", retryable: true, retry_after_s: 30, details: {} },
    meta: { api_version: API_VERSION, request_id: "balance-req-1", generated_at: "2026-09-06T12:00:00Z" },
  };
}

test("the captured payloads are the snake_case shapes the Python producers emit", () => {
  // Guards against the invented camelCase contract coming back: the capture is
  // the producer's own dict, so a renamed field here is a real drift.
  assert.equal(CAPTURED.routes["/interactive/balance"].producer, "twin.balance.balance_report");
  assert.equal(CAPTURED.routes["/interactive/redundancy"].producer, "siting.redundancy.score_redundancy");
  for (const key of ["draw_mw", "capability_mw", "dispatch_mw", "headroom_mw", "capability_basis", "limitations"]) {
    assert.ok(key in balance, `captured balance payload is missing ${key}`);
  }
  for (const key of ["bus_id", "score", "components", "worst_contingency", "synthetic_topology", "evidence"]) {
    assert.ok(key in redundancy, `captured redundancy payload is missing ${key}`);
  }
  // The basis is free text, not an enum. The old guard demanded an enum and so
  // rejected every real response.
  assert.equal(typeof balance.capability_basis, "string");
  assert.ok(balance.capability_basis.includes(";"), "capability_basis is a sentence, not a token");
  assert.equal(typeof redundancy.components.n_minus_one_survivability, "number");
});

test("every root carries the /interactive prefix", () => {
  assert.deepEqual(Object.values(INTERACTIVE_ROOTS).filter((root) => !root.startsWith("/interactive/")), []);
  assert.equal(INTERACTIVE_ROOTS.balance, "/interactive/balance");
  assert.equal(INTERACTIVE_ROOTS.redundancy, "/interactive/redundancy");
  assert.equal(INTERACTIVE_ROOTS.sitingSearch, "/interactive/siting/search");
});

test("the guards accept the captured payloads and reject the invented camelCase one", () => {
  assert.equal(isBalanceWirePayload(balance), true);
  assert.equal(isRedundancyWirePayload(redundancy), true);
  // The shape this client used to declare.
  assert.equal(isBalanceWirePayload({
    scenarioId: "mn_peak", editHash: "edit-001", scope: "state",
    servedLoadMw: 150, generationMw: 145, slackMw: 5, residualMw: 0,
    evidence: { artifactTruth: "synthetic", capabilityBasis: "nameplate", topology: null, provenance: [] },
    assumptions: [], limitations: [],
  }), false);
  const { headroom_mw: _dropped, ...missingHeadroom } = balance;
  assert.equal(isBalanceWirePayload(missingHeadroom), false);
  assert.equal(isRedundancyWirePayload({ ...redundancy, synthetic_topology: "yes" }), false);
});

test("balance uses a guarded GET under /interactive and adapts to the view shape", async () => {
  const calls = [];
  const client = createInteractiveClient({ baseUrl: "https://api.flux.test/", transport: async (url, init) => {
    calls.push([String(url), init]);
    return new Response(JSON.stringify(balance));
  } });

  const state = await client.getBalance({ scenarioId: "mn_peak", editHash: "edit-001", scope: "state" });
  assert.equal(state.kind, "ready");
  assert.equal(state.data.drawMw, balance.draw_mw);
  assert.equal(state.data.headroomMw, balance.headroom_mw);
  assert.equal(state.data.capabilityBasis, balance.capability_basis);
  assert.deepEqual(calls, [[
    "https://api.flux.test/interactive/balance?scenario_id=mn_peak&edit_hash=edit-001&scope=state",
    { method: "GET", headers: undefined, body: undefined },
  ]]);
});

test("balance preserves server unavailable separately from a malformed success", async () => {
  const unavailable = createInteractiveClient({ transport: async () => new Response(JSON.stringify(unavailableEnvelope()), { status: 503 }) });
  assert.deepEqual(await unavailable.getBalance({ scenarioId: "mn_peak" }), {
    kind: "unavailable", source: "server", message: "Balance service has not been mounted.", retryAfterSeconds: 30, requestId: "balance-req-1",
  });

  const malformed = createInteractiveClient({ transport: async () => new Response(JSON.stringify({ ...balance, capability_basis: "" })) });
  assert.deepEqual(await malformed.getBalance({ scenarioId: "mn_peak" }), {
    kind: "invalid", reason: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE,
  });
});

test("redundancy is fetched under /interactive and its topology token comes from the server flag", async () => {
  const calls = [];
  const client = createInteractiveClient({ baseUrl: "https://api.flux.test", transport: async (url, init) => {
    calls.push([String(url), init]);
    return new Response(JSON.stringify(redundancy));
  } });
  const state = await client.getRedundancy({ busId: "load" });
  assert.equal(state.kind, "ready");
  assert.equal(calls[0][0], "https://api.flux.test/interactive/redundancy?bus_id=load");
  assert.equal(state.data.score, redundancy.score);
  assert.equal(state.data.topology, SYNTHETIC_TOPOLOGY_LABEL);

  // A server that does not assert synthetic topology gets no topology claim.
  const notSynthetic = toRedundancyView({
    ...redundancy,
    synthetic_topology: false,
    evidence: { ...redundancy.evidence, synthetic_topology: false },
  });
  assert.equal(notSynthetic.topology, null);
});

test("siting search is issued as a POST to /interactive/siting/search", async () => {
  const calls = [];
  const client = createInteractiveClient({ baseUrl: "https://api.flux.test", transport: async (url, init) => {
    calls.push([String(url), init]);
    return new Response(JSON.stringify({ selection: { method: "synthetic", limitations: [] }, candidates: [] }));
  } });
  assert.equal((await client.searchSiting({ scenarioId: "mn_peak", query: "west" })).kind, "ready");
  assert.equal(calls[0][0], "https://api.flux.test/interactive/siting/search");
  assert.equal(calls[0][1].method, "POST");
  assert.deepEqual(JSON.parse(calls[0][1].body), { scenario_id: "mn_peak", edit_hash: null, query: "west" });
});

test("the adapters rename fields and derive no value of their own", () => {
  const view = toBalanceView(balance);
  assert.equal(view.drawMw, balance.draw_mw);
  assert.equal(view.capabilityMw, balance.capability_mw);
  assert.equal(view.dispatchMw, balance.dispatch_mw);
  assert.equal(view.headroomMw, balance.headroom_mw);
  assert.deepEqual(view.limitations, balance.limitations);

  // A payload whose headroom is NOT capability - draw must survive the adapter
  // untouched; the browser has no licence to correct the server's accounting.
  const inconsistent = toBalanceView({ ...balance, headroom_mw: -2 });
  assert.equal(inconsistent.headroomMw, -2);
  assert.notEqual(inconsistent.headroomMw, balance.capability_mw - balance.draw_mw);
});
