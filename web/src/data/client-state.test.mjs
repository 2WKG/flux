import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-client-state-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  "./node_modules/.bin/tsc",
  [
    "src/data/transport.ts",
    "src/data/validation.ts",
    "src/data/client-state.ts",
    "--target", "ES2022", "--module", "CommonJS", "--moduleResolution", "Node", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  API_VERSION,
  MALFORMED_RESPONSE_MESSAGE,
  NETWORK_FAILURE_MESSAGE,
  VERSION_MISMATCH_MESSAGE,
  createReadApiClient,
  createSseClient,
} = await import(pathToFileURL(join(outputDirectory, "client-state.js")).href);

const isScenarioList = (value) => Array.isArray(value) && value.every((item) =>
  typeof item === "object" && item !== null && typeof item.scenario_id === "string",
);
const notEmpty = (value) => value.length === 0;

function failureEnvelope(overrides = {}) {
  return {
    status: "unavailable",
    data: null,
    error: {
      code: "unavailable",
      message: "Scenario artifacts have not been built.",
      retryable: true,
      retry_after_s: 30,
      details: {},
    },
    meta: {
      api_version: API_VERSION,
      request_id: "request-123",
      generated_at: "2026-09-05T18:04:11Z",
    },
    ...overrides,
  };
}

test("read client distinguishes ready and empty guarded payloads", async () => {
  const responses = [
    new Response(JSON.stringify([{ scenario_id: "uri_2021" }])),
    new Response(JSON.stringify([])),
  ];
  const client = createReadApiClient(async () => responses.shift());

  assert.deepEqual(await client.get("/scenarios", isScenarioList, notEmpty), {
    kind: "ready", data: [{ scenario_id: "uri_2021" }],
  });
  assert.deepEqual(await client.get("/scenarios", isScenarioList, notEmpty), { kind: "empty" });
});

test("read client maps a documented unavailable envelope separately from server failure", async () => {
  const unavailable = createReadApiClient(async () =>
    new Response(JSON.stringify(failureEnvelope()), { status: 503 }),
  );
  const failed = createReadApiClient(async () =>
    new Response(JSON.stringify(failureEnvelope({
      status: "error",
      error: { code: "not_found", message: "Not found.", retryable: false, retry_after_s: null, details: {} },
    })), { status: 404 }),
  );

  assert.deepEqual(await unavailable.get("/layers/cascade", isScenarioList, notEmpty), {
    kind: "unavailable",
    source: "server",
    message: "Scenario artifacts have not been built.",
    retryAfterSeconds: 30,
    requestId: "request-123",
  });
  assert.deepEqual(await failed.get("/layers/missing", isScenarioList, notEmpty), {
    kind: "failed", source: "server", message: "Not found.", requestId: "request-123",
  });
});

test("read client keeps incompatible and malformed payloads in distinct invalid states", async () => {
  const mismatch = createReadApiClient(async () =>
    new Response(JSON.stringify(failureEnvelope({ meta: { api_version: "v2" } })), { status: 503 }),
  );
  const malformed = createReadApiClient(async () => new Response("not json"));

  assert.deepEqual(await mismatch.get("/layers/cascade", isScenarioList, notEmpty), {
    kind: "invalid", reason: "version_mismatch", message: VERSION_MISMATCH_MESSAGE,
  });
  assert.deepEqual(await malformed.get("/scenarios", isScenarioList, notEmpty), {
    kind: "invalid", reason: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE,
  });
});

test("read client maps network rejection without pretending that the server is unavailable", async () => {
  const client = createReadApiClient(async () => { throw new TypeError("offline"); });

  assert.deepEqual(await client.get("/scenarios", isScenarioList, notEmpty), {
    kind: "failed", source: "network", message: NETWORK_FAILURE_MESSAGE,
  });
});

test("SSE client exposes a typed ready stream and closes its transport signal", async () => {
  let requestSignal;
  let bodyCancelled = false;
  const client = createSseClient(async (_input, init) => {
    requestSignal = init.signal;
    return new Response(new ReadableStream({
      cancel() {
        bodyCancelled = true;
      },
    }), { headers: { "content-type": "text/event-stream" } });
  });
  const decoder = (frame) => frame === "event: done" ? { type: "done" } : null;
  const state = await client.connect("/ask", decoder);

  assert.equal(state.kind, "ready");
  assert.deepEqual(state.data.decode("event: done"), { type: "done" });
  state.data.close();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(requestSignal.aborted, true);
  assert.equal(bodyCancelled, true);
});
