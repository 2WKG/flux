/**
 * The physical-inventory surface's disclosures, rendered.
 *
 * PR #245's review found three type-clean mutations that hid the coverage
 * panel, reported zero unavailable-geometry records, and blanked the release id
 * and SHA-256 — and left its whole suite green, because only the three pure
 * functions were tested and nothing asserted the disclosures they feed. Each of
 * those three is a test here, over rendered markup. The response-contract half
 * (`src/data/grid-inventory.ts`) and the bounded page walk
 * (`src/data/grid-client.ts`) are asserted alongside them.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-grid-inventory.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { GridInventoryPanel } from "./src/renderer/GridInventoryPanel";
      export * from "./src/data/grid-inventory";
      export { loadGridLayer, gridLayerUrl, MAX_PAGES } from "./src/data/grid-client";
      export { createReadApiClient } from "./src/data/client-state";
      export { statusLabelForItem, sceneFor, acceptedPaths } from "./src/renderer/grid-scene";
      export { STATUS_COPY } from "./src/source-truth";
      const noop = () => {};
      export const renderPanel = (load, extra = {}) => renderToStaticMarkup(createElement(GridInventoryPanel, {
        load, state: "mn", layers: ["line"], query: "", selected: null,
        onStateChange: noop, onLayersChange: noop, onQueryChange: noop, onSelect: noop, onRetry: noop,
        ...extra,
      }));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "grid-inventory-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic",
  packages: "external", loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const grid = await import(compiled.href);

const provenance = {
  source_id: "hifld_transmission", source_record_id: "rec-1", authority: "HIFLD",
  source_ref: "hifld://transmission/2026", source_version: "2026-02", retrieved_at: "2026-02-01T00:00:00Z",
};

const availableItem = (id, coordinates = [[-94, 46], [-93, 45]]) => ({
  asset_id: id, asset_class: "line", asset_kind: "transmission_line", availability: "available",
  display_geometry: { type: "LineString", coordinates }, display_crs: "EPSG:4326",
  native_geometry: null, native_crs: "EPSG:3857", geometry_status: "source",
  geometry_accuracy_basis: "source coordinates", geometry_precision_m: 10,
  transform_provenance: { method: "reproject", source_crs: "EPSG:3857", display_crs: "EPSG:4326" },
  provenance,
});

const unavailableItem = (id) => ({
  asset_id: id, asset_class: "generation", asset_kind: "unit", availability: "unavailable",
  display_geometry: null, display_crs: null, native_geometry: null, native_crs: null,
  geometry_status: "unavailable", geometry_accuracy_basis: null, geometry_precision_m: null,
  transform_provenance: null, provenance,
});

/** The wire body, then through the real parser: the panel only ever sees parsed pages. */
const page = (items, coverage = [], overrides = {}) => {
  const parsed = grid.pageFrom(wirePage(items, coverage, overrides));
  assert.ok(parsed && !("status" in parsed), "the test fixture is not a valid page");
  return parsed;
};

const wirePage = (items, coverage = [], overrides = {}) => ({
  api_version: "v1", state: "mn", artifact_version: "1.1.0", artifact_id: "flux:mn-physical:v1",
  release_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  layer: "line", inventory_mode: "physical_observed", electrical_model_mode: "none",
  items, page: { limit: 100, cursor: null, next_cursor: null, total: items.length },
  coverage, ...overrides,
});

const coverageRow = {
  asset_class: "generation", status: "partial", scope_id: "eia-860", source_scope: "EIA-860 2024",
  reason: "Unit coordinates are absent for retired units.",
  observed_count: 1200, denominator_count: 1500, unknown_count: 44, unavailable_count: 256,
};

const loaded = (pages, extra = {}) => ({ kind: "loaded", pages, truncated: false, nextCursor: null, ...extra });

test("the coverage disclosure is rendered, one article per coverage row", () => {
  // #245 mutation: `hidden` on the coverage section. It left 266 tests green.
  const markup = grid.renderPanel(loaded([page([availableItem("a")], [coverageRow])]));
  assert.match(markup, /aria-label="Coverage and geometry availability"/);
  assert.doesNotMatch(markup, /class="grid-coverage"[^>]*hidden/);
  const articles = [...markup.matchAll(/<article>/g)];
  assert.equal(articles.length, 1, "one article per coverage row");
  assert.match(markup, /EIA-860 2024/);
  assert.match(markup, /Unit coordinates are absent for retired units\./);
  assert.match(markup, /Observed 1200 of 1500; unknown 44; unavailable 256\./);
});

test("the unavailable-geometry count is the whole loaded set, not the drawable subset", () => {
  // #245 mutation: count only the available records, always reporting 0.
  const items = [availableItem("a"), unavailableItem("b"), unavailableItem("c")];
  const markup = grid.renderPanel(loaded([page(items, [coverageRow])]));
  assert.match(markup, /1 rendered from 3 loaded records; 2 loaded records have unavailable geometry/);
  assert.deepEqual(grid.geometryAccounting(items), { totalLoaded: 3, renderable: 1, unavailableGeometry: 2 });
  // And the function cannot be talked out of it by being handed a filtered list:
  // a caller that pre-filters gets a different totalLoaded, which the sentence shows.
  assert.equal(grid.geometryAccounting(items.filter((item) => item.availability === "available")).totalLoaded, 1);
});

test("the release identity and its SHA-256 are disclosed", () => {
  // #245 mutation: blank the artifact id and version. It left 266 tests green.
  const release = page([availableItem("a")], [coverageRow]);
  const markup = grid.renderPanel(loaded([release]));
  assert.match(markup, new RegExp(`${release.artifact_id} · ${release.artifact_version}`));
  assert.match(markup, new RegExp(`Release SHA-256: ${release.release_sha256}`));
});

test("a truncated page walk is disclosed with the cursor it stopped on", () => {
  const markup = grid.renderPanel(loaded([page([availableItem("a")])], { truncated: true, nextCursor: "cursor-9" }));
  assert.match(markup, /The page walk stopped at its cap/);
  assert.match(markup, /cursor-9/);
});

test("every failure envelope keeps the server's own code and message", () => {
  // #245 recognised only `status: "unavailable"` and replaced 404/422/500 with
  // "Grid API returned <code>." The API sends `status: "error"` for all three.
  for (const status of ["unavailable", "error"]) {
    const parsed = grid.pageFrom({
      status, data: null,
      error: { code: "not_found", message: "No release 1.1.0 exists for state mn.", retryable: false, retry_after_s: null, details: {} },
      meta: { api_version: "v1", request_id: "req-7", generated_at: "2026-02-01T00:00:00Z" },
    });
    assert.ok(parsed && "status" in parsed, `${status} envelope was not recognised as a failure`);
    assert.equal(parsed.error.code, "not_found");
    assert.equal(parsed.error.message, "No release 1.1.0 exists for state mn.");
    assert.equal(parsed.error.requestId, "req-7");
  }
  const markup = grid.renderPanel({ kind: "refused", status: "request_failed", code: "not_found", message: "No release 1.1.0 exists for state mn.", requestId: "req-7" });
  assert.match(markup, new RegExp(grid.STATUS_COPY.request_failed));
  assert.match(markup, /No release 1\.1\.0 exists for state mn\./);
  assert.match(markup, /req-7/);
  assert.match(markup, /Retry the inventory request/);
});

test("the panel names no status word of its own", () => {
  // Every status word on this surface must be a `STATUS_COPY` value.
  const markup = grid.renderPanel({ kind: "refused", status: "unavailable", code: "unavailable", message: "The artifact is not built." });
  const text = markup.replace(/<[^>]*>/g, " ");
  assert.match(text, new RegExp(grid.STATUS_COPY.unavailable));
  for (const rival of [/Source supported/, /Source screened/, /Request-failed/]) assert.doesNotMatch(text, rival);
});

test("an unavailable record never becomes a marker, and a repaired one is rejected outright", () => {
  assert.equal(grid.renderableFeatures([unavailableItem("b")]).length, 0);
  // The server states geometry absence with a triple. A payload that fills any
  // part of it is not repaired; the whole item is refused.
  assert.equal(grid.spatialItem({ ...unavailableItem("b"), display_crs: "EPSG:4326" }), null);
  assert.equal(grid.spatialItem({ ...unavailableItem("b"), geometry_status: "derived" }), null);
  assert.notEqual(grid.spatialItem(unavailableItem("b")), null);
});

test("geometry provenance decides the status token, with no default", () => {
  assert.equal(grid.statusLabelForItem(availableItem("a")), "source_supported");
  assert.equal(grid.statusLabelForItem({ ...availableItem("a"), geometry_status: "derived" }), "source_screened");
  assert.equal(grid.statusLabelForItem(unavailableItem("b")), "unavailable");
  // A path whose label is not placeable suppresses the whole set.
  const scene = grid.sceneFor([availableItem("a")]);
  assert.equal(grid.acceptedPaths(scene.paths, scene.view).length, 1);
  assert.equal(grid.acceptedPaths([{ ...scene.paths[0], statusLabel: "synthetic" }], scene.view).length, 0);
});

test("the page walk is bounded, viewport-scoped, and stops at the first refusal", async () => {
  const seen = [];
  // A server that always offers another cursor: an unbounded walk never returns.
  const endless = async (input) => {
    seen.push(String(input));
    return new Response(JSON.stringify(wirePage([availableItem(`a${seen.length}`)], [], {
      page: { limit: 100, cursor: null, next_cursor: `c${seen.length}`, total: 10_000 },
    })), { status: 200, headers: { "content-type": "application/json" } });
  };
  const outcome = await grid.loadGridLayer(
    { state: "mn", layer: "line", bbox: [-97.3, 43.4, -89.4, 49.5], maxPages: 3 },
    grid.createReadApiClient(endless),
  );
  assert.equal(outcome.kind, "loaded");
  assert.equal(outcome.pages.length, 3, "the walk must stop at its cap");
  assert.equal(outcome.truncated, true);
  assert.equal(outcome.nextCursor, "c3");
  for (const url of seen) assert.match(url, /bbox=-97\.3%2C43\.4%2C-89\.4%2C49\.5/, "every request must carry the viewport");
  assert.match(grid.gridLayerUrl({ state: "tx", layer: "line" }, "c1"), /^\/api\/v1\/grid\/layers\/line\?/);

  const refusing = async () => new Response(JSON.stringify({
    status: "error", data: null,
    error: { code: "invalid_input", message: "bbox is malformed.", retryable: false, retry_after_s: null, details: {} },
    meta: { api_version: "v1", request_id: "req-2", generated_at: "2026-02-01T00:00:00Z" },
  }), { status: 422, headers: { "content-type": "application/json" } });
  const refused = await grid.loadGridLayer({ state: "mn", layer: "line" }, grid.createReadApiClient(refusing));
  assert.equal(refused.kind, "refused");
  assert.equal(refused.status, "request_failed");
  assert.equal(refused.message, "bbox is malformed.");
});
