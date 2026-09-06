import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { mock } from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-transport-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/data/transport.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { DEFAULT_SSE_IDLE_TIMEOUT_MS, DEFAULT_TIMEOUT_MS, RequestTimeoutError, ResponseSizeError, fetchWithPolicy } = await import(
  pathToFileURL(join(outputDirectory, "transport.js")).href,
);

test("retries a transient GET response up to the bounded retry count", async () => {
  let calls = 0;
  const response = await fetchWithPolicy("https://example.test/layers", {
    retries: 2,
    fetchImplementation: async () => {
      calls += 1;
      return new Response(null, { status: calls < 3 ? 503 : 200 });
    },
  });

  assert.equal(response.status, 200);
  assert.equal(calls, 3);
});

test("does not retry unsafe methods even after a transient response", async () => {
  let calls = 0;
  const response = await fetchWithPolicy("https://example.test/cascade", {
    method: "POST",
    retries: 2,
    fetchImplementation: async () => {
      calls += 1;
      return new Response(null, { status: 503 });
    },
  });

  assert.equal(response.status, 503);
  assert.equal(calls, 1);
});

test("reports per-attempt timeouts and does not retry them when retries are disabled", async () => {
  await assert.rejects(
    fetchWithPolicy("https://example.test/slow", {
      timeoutMs: 10,
      retries: 0,
      fetchImplementation: (_input, init) => new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    }),
    RequestTimeoutError,
  );
});

test("propagates caller cancellation without a retry", async () => {
  const controller = new AbortController();
  let calls = 0;
  const request = fetchWithPolicy("https://example.test/layers", {
    signal: controller.signal,
    retries: 2,
    fetchImplementation: (_input, init) => new Promise((_resolve, reject) => {
      calls += 1;
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
  });
  controller.abort();

  await assert.rejects(request, /aborted/i);
  assert.equal(calls, 1);
});

test("does not start a fetch when its caller signal was already aborted", async () => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;

  await assert.rejects(
    fetchWithPolicy("https://example.test/layers", {
      signal: controller.signal,
      fetchImplementation: async () => {
        calls += 1;
        return new Response(null, { status: 200 });
      },
    }),
    /aborted/i,
  );
  assert.equal(calls, 0);
});

test("times out a response body that stalls after headers", async () => {
  const response = await fetchWithPolicy("https://example.test/slow-body", {
    timeoutMs: 10,
    retries: 0,
    fetchImplementation: async () => new Response(new ReadableStream()),
  });

  await assert.rejects(response.text(), RequestTimeoutError);
});

test("keeps an active SSE stream open beyond the JSON body deadline", async () => {
  const response = await fetchWithPolicy("https://example.test/ask", {
    timeoutMs: 10,
    retries: 0,
    fetchImplementation: async () => new Response(new ReadableStream({
      start(controller) {
        setTimeout(() => controller.enqueue(new TextEncoder().encode(": ping\n\n")), 20);
        setTimeout(() => controller.close(), 30);
      },
    }), { headers: { "content-type": "text/event-stream" } }),
  });

  assert.equal(await response.text(), ": ping\n\n");
});

test("rejects declared and streamed response bodies over the configured cap", async () => {
  let declaredBodyCancelled = false;
  let declaredBodyCalls = 0;
  await assert.rejects(
    fetchWithPolicy("https://example.test/too-large", {
      maxResponseBytes: 3,
      fetchImplementation: async () => {
        declaredBodyCalls += 1;
        return new Response(
          new ReadableStream({ cancel: () => { declaredBodyCancelled = true; } }),
          { headers: { "content-length": "4" } },
        );
      },
    }),
    ResponseSizeError,
  );
  assert.equal(declaredBodyCancelled, true);
  assert.equal(declaredBodyCalls, 1);

  const response = await fetchWithPolicy("https://example.test/chunked", {
    maxResponseBytes: 3,
    fetchImplementation: async () => new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.enqueue(new Uint8Array([3, 4]));
      },
    })),
  });
  await assert.rejects(response.arrayBuffer(), ResponseSizeError);
});

test("cancels discarded retry bodies before trying again", async () => {
  let calls = 0;
  let discardedBodyCancelled = false;
  const response = await fetchWithPolicy("https://example.test/retry", {
    retries: 1,
    fetchImplementation: async () => {
      calls += 1;
      if (calls === 1) {
        return new Response(
          new ReadableStream({ cancel: () => { discardedBodyCancelled = true; } }),
          { status: 503 },
        );
      }
      return new Response(null, { status: 200 });
    },
  });

  assert.equal(response.status, 200);
  assert.equal(calls, 2);
  assert.equal(discardedBodyCancelled, true);
});

const RETRIABLE_STATUSES = [408, 429, 500, 502, 503, 504];

for (const status of RETRIABLE_STATUSES) {
  test(`retries a transient GET ${status} response`, async () => {
    let calls = 0;
    const response = await fetchWithPolicy("https://example.test/layers", {
      retries: 1,
      fetchImplementation: async () => {
        calls += 1;
        return new Response(null, { status: calls === 1 ? status : 200 });
      },
    });

    assert.equal(response.status, 200);
    assert.equal(calls, 2);
  });
}

test("does not retry a non-transient GET response", async () => {
  let calls = 0;
  const response = await fetchWithPolicy("https://example.test/layers/missing", {
    retries: 2,
    fetchImplementation: async () => {
      calls += 1;
      return new Response(null, { status: 404 });
    },
  });

  assert.equal(response.status, 404);
  assert.equal(calls, 1);
});

test("never retries or schedules a retry delay after a cancellation error", async (t) => {
  const setTimeoutSpy = t.mock.method(globalThis, "setTimeout");

  // A fetch that reports AbortError on its own (e.g. a polyfill) with the caller signal untouched.
  const fetchAbort = new DOMException("aborted by fetch", "AbortError");
  let abortCalls = 0;
  await assert.rejects(
    fetchWithPolicy("https://example.test/layers", {
      retries: 2,
      fetchImplementation: async () => {
        abortCalls += 1;
        throw fetchAbort;
      },
    }),
    (error) => error === fetchAbort,
  );
  assert.equal(abortCalls, 1);
  // Exactly one timer: the per-attempt timeout. No retry back-off was scheduled.
  assert.equal(setTimeoutSpy.mock.callCount(), 1);

  // A caller abort whose fetch surfaces a non-AbortError failure must propagate that same error.
  setTimeoutSpy.mock.resetCalls();
  const controller = new AbortController();
  const fetchFailure = new Error("socket closed by caller abort");
  let callerCalls = 0;
  const request = fetchWithPolicy("https://example.test/layers", {
    signal: controller.signal,
    retries: 2,
    fetchImplementation: (_input, init) => new Promise((_resolve, reject) => {
      callerCalls += 1;
      init.signal.addEventListener("abort", () => reject(fetchFailure));
    }),
  });
  controller.abort();
  await assert.rejects(request, (error) => error === fetchFailure);
  assert.equal(callerCalls, 1);
  assert.equal(setTimeoutSpy.mock.callCount(), 1);
});

test("keeps a healthy SSE stream alive past the 10 s body deadline and cuts it after the idle window", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let upstream;
  let upstreamCancelled = false;
  const response = await fetchWithPolicy("https://example.test/ask", {
    method: "POST",
    fetchImplementation: async () => new Response(new ReadableStream({
      start(controller) { upstream = controller; },
      cancel() { upstreamCancelled = true; },
    }), { headers: { "content-type": "text/event-stream" } }),
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  // Past DEFAULT_TIMEOUT_MS with no data yet: the finite JSON deadline must not apply to SSE.
  t.mock.timers.tick(DEFAULT_TIMEOUT_MS + 1);
  upstream.enqueue(new TextEncoder().encode(": ping\n\n"));
  assert.equal(decoder.decode((await reader.read()).value), ": ping\n\n");
  assert.equal(upstreamCancelled, false);

  // Activity resets the idle window: 1 ms short of the idle timeout is still healthy.
  t.mock.timers.tick(DEFAULT_SSE_IDLE_TIMEOUT_MS - 1);
  upstream.enqueue(new TextEncoder().encode("event: token\ndata: {}\n\n"));
  assert.equal(decoder.decode((await reader.read()).value), "event: token\ndata: {}\n\n");
  assert.equal(upstreamCancelled, false);

  // Silence for the full idle window is a dead stream.
  t.mock.timers.tick(DEFAULT_SSE_IDLE_TIMEOUT_MS);
  await assert.rejects(reader.read(), RequestTimeoutError);
  assert.equal(upstreamCancelled, true);
});

test("a caller abort after headers cancels the established body", async () => {
  const controller = new AbortController();
  let upstreamCancelled = false;
  const response = await fetchWithPolicy("https://example.test/ask", {
    method: "POST",
    signal: controller.signal,
    fetchImplementation: async () => new Response(new ReadableStream({
      cancel() { upstreamCancelled = true; },
    }), { headers: { "content-type": "text/event-stream" } }),
  });
  const reader = response.body.getReader();
  const pendingRead = reader.read();

  controller.abort();

  await assert.rejects(
    Promise.race([
      pendingRead,
      new Promise((_resolve, reject) => setTimeout(() => reject(new Error("read never settled")), 1_000)),
    ]),
    (error) => error instanceof DOMException && error.name === "AbortError",
  );
  assert.equal(upstreamCancelled, true);
});

test("a caller abort after headers disconnects a real SSE server through the default fetch", async () => {
  let serverSawClose;
  const closed = new Promise((resolve) => { serverSawClose = resolve; });
  const server = createServer((request, response) => {
    response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    response.write(": ping\n\n");
    const heartbeat = setInterval(() => response.write(": ping\n\n"), 20);
    request.on("close", () => { clearInterval(heartbeat); serverSawClose(true); });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    const controller = new AbortController();
    const response = await fetchWithPolicy(`http://127.0.0.1:${port}/ask`, {
      method: "POST",
      signal: controller.signal,
    });
    const reader = response.body.getReader();
    assert.equal((await reader.read()).done, false);

    controller.abort();

    const outcome = await Promise.race([
      closed,
      new Promise((resolve) => setTimeout(() => resolve("server never saw the disconnect"), 2_000)),
    ]);
    assert.equal(outcome, true);
    await assert.rejects(reader.read(), (error) => error?.name === "AbortError");
  } finally {
    server.close();
  }
});
