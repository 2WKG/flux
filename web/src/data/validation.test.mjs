import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-validation-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/data/validation.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  API_VERSION,
  MALFORMED_RESPONSE_MESSAGE,
  VERSION_MISMATCH_MESSAGE,
  validateJsonResponse,
} = await import(pathToFileURL(join(outputDirectory, "validation.js")).href);

const isScenario = (value) => typeof value === "object" && value !== null &&
  typeof value.scenario_id === "string" && Number.isInteger(value.hours);

function failureEnvelope(overrides = {}) {
  return {
    status: "unavailable",
    data: null,
    error: {
      code: "unavailable",
      message: "The requested artifact has not been built.",
      retryable: true,
      retry_after_s: 30,
      details: { scenario_id: "uri_2021" },
    },
    meta: {
      api_version: API_VERSION,
      request_id: "request-123",
      generated_at: "2026-09-05T18:04:11Z",
    },
    ...overrides,
  };
}

test("accepts a guarded unwrapped success payload and preserves the request id", async () => {
  const result = await validateJsonResponse(
    new Response(JSON.stringify({ scenario_id: "uri_2021", hours: 168 }), {
      headers: { "X-Request-ID": "request-123" },
    }),
    isScenario,
  );

  assert.deepEqual(result, {
    kind: "ok",
    data: { scenario_id: "uri_2021", hours: 168 },
    requestId: "request-123",
  });
});

test("accepts the documented failure envelope", async () => {
  const result = await validateJsonResponse(
    new Response(JSON.stringify(failureEnvelope()), { status: 503 }),
    isScenario,
  );

  assert.equal(result.kind, "failure");
  assert.equal(result.failure.error.code, "unavailable");
});

test("tolerates additive fields on a failure envelope (root, error, meta)", async () => {
  const envelope = failureEnvelope({
    meta: { ...failureEnvelope().meta, region: "us-east-1" },
    error: { ...failureEnvelope().error, hint: "rebuild the artifact" },
    trace: { span_id: "abc" },
  });
  const result = await validateJsonResponse(
    new Response(JSON.stringify(envelope), { status: 503 }),
    isScenario,
  );

  assert.equal(result.kind, "failure");
  assert.equal(result.failure.error.code, "unavailable");
  assert.equal(result.failure.error.retry_after_s, 30);
  assert.equal(result.failure.meta.request_id, "request-123");
});

test("still rejects a failure envelope that omits a required field", async () => {
  const { retryable: _dropped, ...errorWithoutRetryable } = failureEnvelope().error;
  const { request_id: _droppedId, ...metaWithoutRequestId } = failureEnvelope().meta;
  for (const overrides of [
    { error: errorWithoutRetryable },
    { meta: metaWithoutRequestId },
  ]) {
    const result = await validateJsonResponse(
      new Response(JSON.stringify(failureEnvelope(overrides)), { status: 503 }),
      isScenario,
    );
    assert.deepEqual(result, { kind: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE });
  }
});

test("maps a different envelope version to a dedicated safe state", async () => {
  const envelope = failureEnvelope({ meta: { api_version: "v2" } });
  const result = await validateJsonResponse(
    new Response(JSON.stringify(envelope), { status: 503 }),
    isScenario,
  );

  assert.deepEqual(result, {
    kind: "version_mismatch",
    expectedVersion: API_VERSION,
    receivedVersion: "v2",
    message: VERSION_MISMATCH_MESSAGE,
  });
});

test("maps malformed server data to a generic state without leaking it", async () => {
  const result = await validateJsonResponse(
    new Response(JSON.stringify({ status: "error", raw_error: "postgres://secret" }), { status: 500 }),
    isScenario,
  );

  assert.deepEqual(result, {
    kind: "malformed_response",
    message: MALFORMED_RESPONSE_MESSAGE,
  });
});

test("rejects a successful payload that does not satisfy its route guard", async () => {
  const result = await validateJsonResponse(
    new Response(JSON.stringify({ scenario_id: 3, hours: "168" })),
    isScenario,
  );

  assert.equal(result.kind, "malformed_response");
});
