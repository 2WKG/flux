// Decide whether the copilot API is actually up by reading `/health`'s body.
//
// A bare `curl --fail` only proves that *something* answered 2xx on the port; it
// is satisfied by an unrelated server and by a proxy's own page. Readiness here
// means the response parses as JSON and is one of the two shapes
// `copilot/routes/health.py` can produce:
//
//   * the success body `{ok: bool, duckdb_path, tables, ...}`; or
//   * the versioned unavailable envelope `{status, data, error, meta}` from
//     `copilot/api/envelope.py` (a fresh checkout with no database).
//
// Both mean "our uvicorn is serving". Prints the observed state word on stdout
// so the caller can report it honestly. Exit 0 ready, 1 not ready.
const url = process.argv[2];
if (!url) {
  console.error("usage: node scripts/dev/health_ready.mjs URL");
  process.exit(2);
}

let response;
let text;
try {
  response = await fetch(url, { signal: AbortSignal.timeout(2000) });
  text = await response.text();
} catch (error) {
  console.error(`health_ready: no response from ${url}: ${error.message}`);
  process.exit(1);
}

let body;
try {
  body = JSON.parse(text);
} catch {
  console.error(`health_ready: ${url} answered HTTP ${response.status} with a non-JSON body`);
  process.exit(1);
}

if (body && typeof body === "object" && typeof body.ok === "boolean") {
  console.log(body.ok ? "ok" : "not_ok");
  process.exit(0);
}
if (
  body && typeof body === "object"
  && typeof body.status === "string" && "error" in body && body.meta
  && typeof body.meta === "object" && typeof body.meta.api_version === "string"
) {
  console.log(body.status);
  process.exit(0);
}
console.error(`health_ready: ${url} answered HTTP ${response.status} with JSON that is not a Flux health body`);
process.exit(1);
