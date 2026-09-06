import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-aggregate-client.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: { contents: 'export * from "./minnesota/aggregate-client";', resolveDir: fileURLToPath(root), loader: "ts" },
  bundle: true, format: "esm", platform: "node", packages: "external", outfile: fileURLToPath(compiled),
});
const aggregate = await import(compiled.href);

const response = {
  artifact_id: "mn:model_result:665b5ac415912f3f", artifact_contract_version: "2.0.0-mn", artifact_identity: { artifact_id: "mn:model_result:665b5ac415912f3f", artifact_kind: "model_result", geography_id: "mn", model_mode: "aggregate", source_identity: "minnesota_aggregate_manifest_v1", source_version: "v1", content_sha256: "f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05" }, model_mode: "aggregate", availability: "available",
  aggregate_manifest: { format: "flux-minnesota-aggregate-v1", model_mode: "aggregate", allocation_status: "unavailable", allocation_limit: "No allocation.", sources: [{ id: "eia930", url: "https://example.invalid/eia930", file_sha256: { "context.csv": "a".repeat(64) } }] },
  stress_metric: { metric_name: "miso_ba_peak_demand_mw", metric_value: 109244, unit: "MW", formula: "MAX(`Demand (MW)`) across the committed EIA-930 MISO balancing-authority context rows for 2024 H1; this is MISO BA context, not Minnesota demand.", source_label: "MISO balancing authority (not Minnesota demand)", time_basis: "UTC end of hour", window_start_utc: "2024-01-01T06:00:00Z", window_end_utc: "2024-07-01T05:00:00Z", window_peak_demand_mw: 109244, window_peak_hour_utc: "2024-06-24T23:00:00Z", scored_hours: 4368, min_index: 0.1, mean_index: 0.6, p95_index: 0.9 },
  provenance: [{ source_name: "eia-930", source_ref: "fixture://context", source_version: "2024-h1", retrieved_at: "2026-09-06T00:00:00Z", license_or_terms: "unknown", source_record_id: "mn:ba_context:miso:2024-h1", content_sha256: "b".repeat(64), is_derived: false }],
  limitations: ["Aggregate only."], prohibited_claims: ["No topology."], base_mva: null, solver_version: null, converter_version: null,
};

test("aggregate client accepts only a complete persisted aggregate response", () => {
  assert.equal(aggregate.isMinnesotaAggregateResponse(response), true);
  assert.equal(aggregate.isMinnesotaAggregateResponse({
    ...response,
    aggregate_manifest: { ...response.aggregate_manifest, sources: [{ id: "tiger", url: "https://example.invalid/tiger" }] },
  }), true, "provenance may carry a source digest when the manifest source has none");
  assert.equal(aggregate.isMinnesotaAggregateResponse({ ...response, model_mode: "topology" }), false);
  assert.equal(aggregate.isMinnesotaAggregateResponse({ ...response, provenance: [] }), false);
  assert.equal(aggregate.isMinnesotaAggregateResponse({ ...response, base_mva: 100 }), false);
});

test("aggregate client uses the same-origin GET projection", async () => {
  let requested = null;
  const state = await aggregate.requestMinnesotaAggregate(async (input, init) => {
    requested = { input, method: init.method };
    return new Response(JSON.stringify(response), { status: 200, headers: { "content-type": "application/json" } });
  });
  assert.deepEqual(requested, { input: "/minnesota/aggregate", method: "GET" });
  assert.equal(state.kind, "ready");
  assert.equal(state.data.artifact_id, response.artifact_id);
});
