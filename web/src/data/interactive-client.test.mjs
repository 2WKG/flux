import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-interactive-client-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(process.execPath, [
  "./node_modules/typescript/bin/tsc",
  "src/data/transport.ts", "src/data/validation.ts", "src/data/client-state.ts", "src/data/interactive-client.ts",
  "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--outDir", outputDirectory,
], { cwd: new URL("../..", import.meta.url), stdio: "inherit" });

const { createInteractiveClient, isBalanceResponse, isRedundancyResponse } = await import(
  pathToFileURL(join(outputDirectory, "interactive-client.js")).href,
);
const { API_VERSION, MALFORMED_RESPONSE_MESSAGE } = await import(
  pathToFileURL(join(outputDirectory, "validation.js")).href,
);

const balance = {
  scenarioId: "mn_peak", editHash: "edit-001", scope: "state",
  servedLoadMw: 150, generationMw: 145, slackMw: 5, residualMw: 0,
  fuelSplitMw: { wind: 35, gas: 110 },
  editDelta: [{ metric: "served_load_mw", valueMw: -10 }],
  evidence: {
    artifactTruth: "synthetic", topology: "synthetic (ACTIVSg2000)", capabilityBasis: "nameplate",
    provenance: [{ sourceId: "fixture:balance", sourceRef: "checked-in contract fixture", version: "v1" }],
  },
  assumptions: ["Input is a declared scenario."],
  limitations: ["Not an operating-grid result."],
};

function unavailableEnvelope() {
  return {
    status: "unavailable", data: null,
    error: { code: "unavailable", message: "Balance service has not been mounted.", retryable: true, retry_after_s: 30, details: {} },
    meta: { api_version: API_VERSION, request_id: "balance-req-1", generated_at: "2026-09-06T12:00:00Z" },
  };
}

test("the planned roots stay inside one client and balance uses a guarded GET", async () => {
  const calls = [];
  const client = createInteractiveClient({ baseUrl: "https://api.flux.test/", transport: async (url, init) => {
    calls.push([String(url), init]);
    return new Response(JSON.stringify(balance));
  } });

  const state = await client.getBalance({ scenarioId: "mn_peak", editHash: "edit-001", scope: "state" });
  assert.equal(state.kind, "ready");
  assert.deepEqual(calls, [[
    "https://api.flux.test/balance?scenario_id=mn_peak&edit_hash=edit-001&scope=state",
    { method: "GET", headers: undefined, body: undefined },
  ]]);
});

test("balance preserves server unavailable separately from a malformed success", async () => {
  const unavailable = createInteractiveClient({ transport: async () => new Response(JSON.stringify(unavailableEnvelope()), { status: 503 }) });
  assert.deepEqual(await unavailable.getBalance({ scenarioId: "mn_peak" }), {
    kind: "unavailable", source: "server", message: "Balance service has not been mounted.", retryAfterSeconds: 30, requestId: "balance-req-1",
  });

  const malformed = createInteractiveClient({ transport: async () => new Response(JSON.stringify({ ...balance, evidence: { ...balance.evidence, provenance: [] } })) });
  assert.deepEqual(await malformed.getBalance({ scenarioId: "mn_peak" }), {
    kind: "invalid", reason: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE,
  });
});

test("balance evidence rejects unavailable truth and missing served metrics", () => {
  assert.equal(isBalanceResponse(balance), true);
  assert.equal(isBalanceResponse({ ...balance, evidence: { ...balance.evidence, artifactTruth: "unavailable" } }), false);
  const { residualMw: _removed, ...missingResidual } = balance;
  assert.equal(isBalanceResponse(missingResidual), false);
});

test("redundancy is typed by bus and rejects unproven or unavailable scores", async () => {
  const redundancy = {
    busId: "bus-7", score: 75, components: { nMinusOneSurvivability: 80, edgeDisjointPaths: 2, alternativeSourceHops: 3 },
    worstContingency: { branchId: "line:7", sourceReachable: true },
    evidence: { artifactTruth: "synthetic", topology: "synthetic (ACTIVSg2000)", provenance: [{ sourceId: "fixture:redundancy", sourceRef: "contract fixture" }] },
    assumptions: ["Topology screen only."], limitations: ["No operating conclusion."],
  };
  const calls = [];
  const client = createInteractiveClient({ baseUrl: "https://api.flux.test", transport: async (url, init) => {
    calls.push([String(url), init]);
    return new Response(JSON.stringify(redundancy));
  } });
  assert.equal((await client.getRedundancy({ busId: "bus-7" })).kind, "ready");
  assert.equal(calls[0][0], "https://api.flux.test/redundancy?bus_id=bus-7");
  assert.equal(isRedundancyResponse({ ...redundancy, evidence: { ...redundancy.evidence, artifactTruth: "unavailable" } }), false);
  assert.equal(isRedundancyResponse({ ...redundancy, evidence: { ...redundancy.evidence, provenance: [] } }), false);
});
