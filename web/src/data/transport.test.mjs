import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-transport-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  "./node_modules/.bin/tsc",
  ["src/data/transport.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { RequestTimeoutError, ResponseSizeError, fetchWithPolicy } = await import(
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
        setTimeout(() => controller.enqueue(new TextEncoder().encode(": ping\\n\\n")), 20);
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
