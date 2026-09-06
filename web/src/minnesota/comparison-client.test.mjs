import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-comparison-client.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: { contents: 'export * from "./minnesota/comparison-client";', resolveDir: fileURLToPath(root), loader: "ts" },
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const comparison = await import(compiled.href);

const ready = {
  status: "ready",
  comparison_id: "artifact:mn:baseline:v1..artifact:mn:candidate:v1",
  baseline: { context_id: "mn:baseline:v1", label: "Baseline evidence" },
  candidate: { context_id: "mn:candidate:v1", label: "Candidate evidence" },
  metrics: [{
    metric_id: "customers_at_risk",
    label: "Customers at risk",
    baseline_value: 12,
    candidate_value: 9,
    delta_signed: -3,
    unit: "customers",
    provenance: [{ source_id: "record", artifact_id: "artifact:mn:baseline:v1", version: "v1", kind: "persisted_aggregate_model" }],
  }],
  highlight_ids: ["scene:mn:baseline:v1", "scene:mn:candidate:v1"],
  limitations: ["aggregate only"],
};

test("comparison client posts the v1 context pair and retains server-signed metrics verbatim", async () => {
  let received;
  const result = await comparison.requestMinnesotaComparison(
    { baselineContextId: "mn:baseline:v1", candidateContextId: "mn:candidate:v1" },
    async (input, init) => {
      received = { input, init };
      return new Response(JSON.stringify(ready), { status: 200, headers: { "content-type": "application/json" } });
    },
  );
  assert.equal(received.input, "/mn/comparisons");
  assert.equal(received.init.method, "POST");
  assert.deepEqual(JSON.parse(received.init.body), {
    baseline_context_id: "mn:baseline:v1",
    candidate_context_id: "mn:candidate:v1",
  });
  assert.equal(received.init.retries, 0);
  assert.equal(result.kind, "ready");
  assert.equal(result.data.metrics[0].delta_signed, -3);
  assert.equal(result.data.metrics[0].unit, "customers");
  assert.deepEqual(result.data.highlight_ids, ready.highlight_ids);
});

test("comparison client maps the standard unavailable envelope without inventing a metric", async () => {
  const unavailable = {
    status: "unavailable", data: null,
    error: { code: "unavailable", message: "The Minnesota comparison artifact is unavailable.", retryable: false, retry_after_s: null, details: { reason: "no_qualified_result" } },
    meta: { api_version: "v1", request_id: "mn-test", generated_at: "2026-01-01T00:00:00Z" },
  };
  const result = await comparison.requestMinnesotaComparison(
    { baselineContextId: "mn:baseline:v1", candidateContextId: "mn:candidate:v1" },
    async () => new Response(JSON.stringify(unavailable), { status: 503, headers: { "content-type": "application/json" } }),
  );
  assert.deepEqual(result, {
    kind: "unavailable",
    source: "server",
    message: "The Minnesota comparison artifact is unavailable.",
    retryAfterSeconds: null,
    requestId: "mn-test",
  });
});

test("comparison client rejects incomplete ready data before rendering it", () => {
  assert.equal(comparison.isMinnesotaComparisonResponse(ready), true, "the control fixture must validate");
  assert.equal(comparison.isMinnesotaComparisonResponse({ ...ready, metrics: [] }), false);
  assert.equal(comparison.isMinnesotaComparisonResponse({ ...ready, highlight_ids: [] }), false);
  assert.equal(comparison.isMinnesotaComparisonResponse({ ...ready, metrics: [{ ...ready.metrics[0], delta_signed: "-3" }] }), false);

  // The guard must require every field the page renders. A provenance row
  // without an artifact id or a version validated and rendered `undefined`.
  const provenance = ready.metrics[0].provenance[0];
  for (const field of ["source_id", "artifact_id", "version", "kind"]) {
    const { [field]: _dropped, ...missing } = provenance;
    assert.equal(
      comparison.isMinnesotaComparisonResponse({
        ...ready,
        metrics: [{ ...ready.metrics[0], provenance: [missing] }],
      }),
      false,
      `a provenance row with no ${field} was accepted, and the page renders that field`,
    );
    assert.equal(
      comparison.isMinnesotaComparisonResponse({
        ...ready,
        metrics: [{ ...ready.metrics[0], provenance: [{ ...provenance, [field]: "" }] }],
      }),
      false,
      `a provenance row with an empty ${field} was accepted`,
    );
  }
  assert.equal(
    comparison.isMinnesotaComparisonResponse({ ...ready, metrics: [{ ...ready.metrics[0], provenance: [] }] }),
    false,
    "a metric with no provenance at all was accepted",
  );
});
