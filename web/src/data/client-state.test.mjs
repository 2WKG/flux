import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-client-state-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
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
const { fetchWithPolicy } = await import(pathToFileURL(join(outputDirectory, "transport.js")).href);

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
    kind: "failed", source: "network", reason: "unreachable", message: NETWORK_FAILURE_MESSAGE,
  });
});

test("SSE client close() cancels the body through the real fetchWithPolicy path", async () => {
  let bodyCancelled = false;
  const fetchImplementation = async () => {
    return new Response(new ReadableStream({
      cancel() {
        bodyCancelled = true;
      },
    }), { headers: { "content-type": "text/event-stream" } });
  };
  // The mock is the *fetch*, not the transport: the client still goes through fetchWithPolicy.
  const client = createSseClient((input, options) => fetchWithPolicy(input, { ...options, fetchImplementation }));
  const decoder = (frame) => frame === "event: done" ? { type: "done" } : null;
  const state = await client.connect("/ask", decoder);

  assert.equal(state.kind, "ready");
  assert.deepEqual(state.data.decode("event: done"), { type: "done" });
  const pendingRead = state.data.reader.read();
  state.data.close();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(bodyCancelled, true);
  assert.deepEqual(await pendingRead, { done: true, value: undefined });
  state.data.close(); // idempotent
});

test("SSE client close() disconnects a real SSE server through the default transport", async () => {
  let serverSawClose;
  const closed = new Promise((resolve) => { serverSawClose = resolve; });
  let requests = 0;
  const server = createServer((request, response) => {
    requests += 1;
    assert.equal(request.method, "POST");
    response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    response.write(": ping\n\n");
    const heartbeat = setInterval(() => response.write(": ping\n\n"), 20);
    request.on("close", () => { clearInterval(heartbeat); serverSawClose(true); });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    const client = createSseClient();
    const state = await client.connect(`http://127.0.0.1:${port}/ask`, () => null);
    assert.equal(state.kind, "ready");
    const first = await state.data.reader.read();
    assert.equal(first.done, false);
    assert.match(new TextDecoder().decode(first.value), /: ping/);

    state.data.close();

    const outcome = await Promise.race([
      closed,
      new Promise((resolve) => setTimeout(() => resolve("server never saw the disconnect"), 2_000)),
    ]);
    assert.equal(outcome, true);
    const afterClose = await Promise.race([
      state.data.reader.read().then((result) => result, (error) => ({ rejected: error?.name })),
      new Promise((resolve) => setTimeout(() => resolve("read never settled"), 1_000)),
    ]);
    assert.ok(afterClose.done === true || afterClose.rejected !== undefined, JSON.stringify(afterClose));
    assert.equal(requests, 1);
  } finally {
    // Drop any socket the client failed to release so a regression fails instead of hanging the runner.
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});

// The read client used to wrap every throw in `networkFailure()`, so a user who
// cancelled a request was told the service could not be reached. These assert
// each real cause survives the catch.
const { RequestTimeoutError, ResponseSizeError } = await import(
  pathToFileURL(join(outputDirectory, "transport.js")).href
);
const {
  CANCELLED_MESSAGE,
  TIMEOUT_MESSAGE,
  RESPONSE_TOO_LARGE_MESSAGE,
  INVALID_OPTIONS_MESSAGE,
} = await import(pathToFileURL(join(outputDirectory, "client-state.js")).href);

async function failWith(error) {
  const client = createReadApiClient(async () => { throw error; });
  return client.get("https://example.test/scenarios", isScenarioList, notEmpty);
}

test("a cancelled request is reported as cancelled, not as an unreachable service", async () => {
  const state = await failWith(new DOMException("Request aborted", "AbortError"));
  assert.equal(state.kind, "failed");
  assert.equal(state.source, "network");
  assert.equal(state.reason, "cancelled");
  assert.equal(state.message, CANCELLED_MESSAGE);
  assert.notEqual(state.message, NETWORK_FAILURE_MESSAGE);
});

test("an expired deadline is reported as a timeout, not as an unreachable service", async () => {
  const state = await failWith(new RequestTimeoutError(10_000));
  assert.equal(state.reason, "timeout");
  assert.equal(state.message, TIMEOUT_MESSAGE);
  assert.notEqual(state.message, NETWORK_FAILURE_MESSAGE);
});

test("a discarded oversized body is reported as oversized, not as an unreachable service", async () => {
  const state = await failWith(new ResponseSizeError(5 * 1024 * 1024));
  assert.equal(state.reason, "response_too_large");
  assert.equal(state.message, RESPONSE_TOO_LARGE_MESSAGE);
  assert.notEqual(state.message, NETWORK_FAILURE_MESSAGE);
});

test("invalid request options are reported as such, not as an unreachable service", async () => {
  const state = await failWith(new RangeError("timeoutMs must be a positive, finite number"));
  assert.equal(state.reason, "invalid_options");
  assert.equal(state.message, INVALID_OPTIONS_MESSAGE);
  assert.notEqual(state.message, NETWORK_FAILURE_MESSAGE);
});

test("a genuine transport error is still the unreachable network failure", async () => {
  const state = await failWith(new TypeError("offline"));
  assert.equal(state.reason, "unreachable");
  assert.equal(state.message, NETWORK_FAILURE_MESSAGE);
});

test("the four client-side causes do not collapse onto one another", async () => {
  const reasons = await Promise.all([
    failWith(new DOMException("Request aborted", "AbortError")),
    failWith(new RequestTimeoutError(1)),
    failWith(new ResponseSizeError(1)),
    failWith(new RangeError("bad options")),
    failWith(new TypeError("offline")),
  ]);
  assert.equal(new Set(reasons.map((state) => state.reason)).size, 5);
  assert.equal(new Set(reasons.map((state) => state.message)).size, 5);
});

test("the SSE client keeps the same distinctions on connect", async () => {
  const sse = createSseClient(async () => { throw new DOMException("Request aborted", "AbortError"); });
  const state = await sse.connect("https://example.test/ask", () => null);
  assert.equal(state.kind, "failed");
  assert.equal(state.reason, "cancelled");
  assert.equal(state.message, CANCELLED_MESSAGE);
});
