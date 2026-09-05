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
const { RequestTimeoutError, fetchWithPolicy } = await import(
  pathToFileURL(join(outputDirectory, "transport.js")).href,
);

test("retries a transient GET response up to the bounded retry count", async () => {
  let calls = 0;
  const response = await fetchWithPolicy("https://example.test/layers", {
    retries: 2,
    fetchImplementation: async () => {
      calls += 1;
      return new Response("", { status: calls < 3 ? 503 : 200 });
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
      return new Response("", { status: 503 });
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
