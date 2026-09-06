import { expect, test, type Page } from "@playwright/test";
import http from "node:http";
import type { AddressInfo } from "node:net";
// The real origin, not a stand-in: the forward allowlist under test is the one
// `web/server.mjs` ships, and the artifact under test is the one `dist/` holds.
import { createApp } from "../server.mjs";

/**
 * The browser proof for the primary simulation scene (2WKG-479).
 *
 * Two states, both driven for real:
 *
 *  1. **API up.** A stub upstream answers the versioned layer route with a page
 *     whose provenance derives the synthetic ACTIVSg2000 topology, forwarded by
 *     the real `server.mjs` allowlist onto the page's own origin (the page's CSP
 *     is `connect-src 'self'`, so nothing else could reach it). The deck.gl
 *     canvas must mount and every rendered node must carry its topology label.
 *  2. **API down.** The default origin -- a fresh clone's state, with no
 *     `FLUX_API_ORIGIN` -- must show the scene's *named* unavailable state with
 *     the server's own reason and a retry, and must draw no node at all.
 *
 * Both assert the same no-third-party rule `static-explorer.spec.ts` does:
 * every request is same-origin and the page's own CSP reported no violation.
 */

const TOPOLOGY = "synthetic (ACTIVSg2000)";

const recorded = new WeakMap<Page, string[]>();
const violations = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  recorded.set(page, requests);
  page.on("request", (request) => requests.push(request.url()));
  page.on("requestfailed", (request) => requests.push(request.url()));

  const reported: string[] = [];
  violations.set(page, reported);
  await page.exposeFunction("__fluxSceneCspViolation", (uri: string) => { reported.push(uri); });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { __fluxSceneCspViolation: (uri: string) => void })
        .__fluxSceneCspViolation(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
});

async function expectSameOriginOnly(page: Page): Promise<void> {
  const baseOrigin = new URL(page.url()).origin;
  const offOrigin = (recorded.get(page) ?? []).filter((url) => new URL(url).origin !== baseOrigin);
  expect(offOrigin).toEqual([]);
  expect(violations.get(page) ?? []).toEqual([]);
}

/** A record in the shape `GET /api/v1/grid/layers/{layer}` publishes. */
function syntheticItem(id: string, lon: number, lat: number) {
  return {
    asset_id: id, asset_class: "generation", asset_kind: "bus", availability: "available",
    display_geometry: { type: "Point", coordinates: [lon, lat] }, display_crs: "EPSG:4326",
    native_geometry: null, native_crs: null, geometry_status: "source",
    geometry_accuracy_basis: null, geometry_precision_m: null, transform_provenance: null,
    provenance: {
      source_id: "activsg2000_case", source_record_id: id, authority: "Texas A&M synthetic grid",
      source_ref: "data/raw/activsg2000_current/case.m", source_version: "current",
      retrieved_at: "2026-09-06T00:00:00Z",
    },
  };
}

const SYNTHETIC_NODES = [
  syntheticItem("bus-0001", -99.1, 31.2),
  syntheticItem("bus-0002", -97.4, 30.1),
  syntheticItem("bus-0003", -95.8, 29.4),
];

/** A stub upstream Copilot API: the layer route only, everything else unavailable. */
function upstream() {
  return http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const layer = url.pathname.replace("/api/v1/grid/layers/", "");
    if (!url.pathname.startsWith("/api/v1/grid/layers/")) {
      response.writeHead(503, { "content-type": "application/json" });
      response.end(JSON.stringify({
        status: "unavailable", data: null,
        error: { code: "unavailable", message: "The stub upstream serves the layer route only.", retryable: true, retry_after_s: 30, details: { reason: "stub" } },
        meta: { api_version: "v1", request_id: "stub-1", generated_at: new Date().toISOString() },
      }));
      return;
    }
    const items = layer === "generation" ? SYNTHETIC_NODES : [];
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({
      api_version: "v1", state: url.searchParams.get("state") ?? "tx",
      artifact_version: url.searchParams.get("version") ?? "1.1.0",
      artifact_id: "us-tx:physical-inventory:1.1.0", release_sha256: "a".repeat(64),
      layer, inventory_mode: "physical_observed", electrical_model_mode: "none", items,
      page: { limit: Number(url.searchParams.get("limit") ?? 100), cursor: url.searchParams.get("cursor"), next_cursor: null, total: items.length },
      coverage: [],
    }));
  });
}

const listen = (server: http.Server) =>
  new Promise<string>((resolve) => server.listen(0, "127.0.0.1", () =>
    resolve(`http://127.0.0.1:${(server.address() as AddressInfo).port}`)));
const close = (server: http.Server) =>
  new Promise<void>((resolve) => { server.closeAllConnections(); server.close(() => resolve()); });

test("with the layer API up the deck.gl scene mounts and every node carries its topology label", async ({ page }) => {
  const api = upstream();
  const apiOrigin = await listen(api);
  // The real forward allowlist, in front of the real built artifact.
  const origin = http.createServer(createApp({ apiOrigin }));
  const base = await listen(origin);
  try {
    await page.goto(`${base}/`);
    const scene = page.getByLabel("Primary simulation scene");
    await expect(scene).toBeVisible();
    // The canvas is deck.gl's own, loaded lazily in the browser.
    await expect(scene.locator("canvas")).toBeVisible({ timeout: 20_000 });
    // And every rendered node carries the label derived from its own provenance.
    const labels = scene.locator("li.primary-scene-node span.primary-scene-label");
    await expect(labels).toHaveCount(SYNTHETIC_NODES.length);
    for (const label of await labels.all()) await expect(label).toContainText(TOPOLOGY);
    await expect(scene).toContainText(`${SYNTHETIC_NODES.length} nodes drawn`);
    await expect(scene).toContainText("us-tx:physical-inventory:1.1.0");
    // The panels it was mounted beside are still there.
    await expect(page.getByLabel("Source-backed physical inventory")).toBeVisible();
    await expect(page.locator("section.chat-dock")).toBeVisible();
    await expect(page.locator("section.layer-controls")).toBeVisible();
    await expect(page.locator("aside.inspector")).toBeVisible();
    await expectSameOriginOnly(page);
  } finally {
    await close(origin);
    await close(api);
  }
});

test("with no API origin the scene names its unavailable state and draws nothing", async ({ page }) => {
  // The default `server.mjs` webServer: a fresh clone's state.
  await page.goto("/");
  const scene = page.getByLabel("Primary simulation scene");
  await expect(scene).toBeVisible();
  // The server's own named reason, not an empty canvas presented as an empty state.
  await expect(scene.locator(".primary-scene-note")).toContainText(/Unavailable|Request failed/);
  await expect(scene.locator(".primary-scene-note")).toContainText(/no Copilot API origin is configured|no_synthetic_topology_nodes|did not answer/);
  await expect(scene.getByRole("button", { name: /Retry the simulation request/i })).toBeVisible();
  // No node, and above all no borrowed topology claim.
  await expect(scene.locator("li.primary-scene-node")).toHaveCount(0);
  await expect(scene.getByText(TOPOLOGY, { exact: false })).toHaveCount(0);
  await expect(scene.locator("canvas")).toHaveCount(0);
  await expectSameOriginOnly(page);
});
