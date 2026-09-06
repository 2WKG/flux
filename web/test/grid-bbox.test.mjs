/**
 * The physical-inventory read is bbox-bounded at the call site, not merely
 * bbox-capable in `gridLayerUrl`.
 *
 * `grid-client.ts`'s rule 2 says "the viewport bounds the request", but the
 * page's effect never passed a `bbox`, so the whole property was carried by a
 * parameter nothing supplied. These tests drive the shipped path --
 * `loadGridInventory`, which the page's effect calls -- against a recording
 * transport and read the URL the request actually carried.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-grid-bbox.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      export * from "./src/data/grid-client";
      export { createReadApiClient } from "./src/data/client-state";
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "ts",
    sourcefile: "grid-bbox-entry.ts",
  },
  bundle: true, format: "esm", platform: "node", packages: "external",
  loader: { ".css": "empty" }, outfile: fileURLToPath(compiled),
});
const grid = await import(compiled.href);

/** A transport that records every URL and answers one empty terminal page. */
function recorder() {
  const urls = [];
  const fetchImpl = async (url) => {
    urls.push(String(url));
    return new Response(JSON.stringify({
      status: "ok",
      data: { items: [], next_cursor: null, layer: "line", release: { artifact_id: "a", artifact_version: "1.1.0" } },
      meta: { api_version: "v1" },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  return { urls, fetchImpl };
}

test("Minnesota reads carry the documented extent as bbox", async () => {
  const { urls, fetchImpl } = recorder();
  await grid.loadGridInventory({ state: "mn", layers: ["line"] }, grid.createReadApiClient(fetchImpl));
  assert.equal(urls.length >= 1, true, "the read must have issued a request");
  const query = new URL(urls[0], "http://localhost").searchParams;
  assert.equal(query.get("bbox"), grid.GRID_STATE_BBOX.mn.join(","), "the request must carry the state's bbox");
  // And the bbox is the documented one, not a rectangle invented here.
  assert.deepEqual([...grid.GRID_STATE_BBOX.mn], [-97.3, 43.4, -89.4, 49.5]);
});

test("every layer of a view is bounded, not just the first", () => {
  const requests = grid.gridLayerRequestsFor("mn", grid.GRID_LAYERS.mn);
  assert.equal(requests.length, grid.GRID_LAYERS.mn.length);
  for (const request of requests) {
    assert.deepEqual(request.bbox, grid.GRID_STATE_BBOX.mn, `${request.layer} must be bounded`);
    assert.match(grid.gridLayerUrl(request, null), /[?&]bbox=/);
  }
});

test("Texas sends no bbox, because this repository documents no Texas extent", async () => {
  // The honest half of the same rule: an invented rectangle would be fabricated
  // geography. `null` means the whole release, and the URL says so.
  assert.equal(grid.GRID_STATE_BBOX.tx, null);
  const { urls, fetchImpl } = recorder();
  await grid.loadGridInventory({ state: "tx", layers: ["line"] }, grid.createReadApiClient(fetchImpl));
  assert.equal(new URL(urls[0], "http://localhost").searchParams.get("bbox"), null);
});
