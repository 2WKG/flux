import { expect, test } from "@playwright/test";

/**
 * The gate's proof that a real API is behind this origin.
 *
 * `playwright.config.ts` used to run `node server.mjs` alone, with no
 * `FLUX_API_ORIGIN`. `web/server.mjs` registers its read allowlist either way,
 * so every allowlisted path then answered 503 `no_api_origin_configured` from
 * the forward itself -- including `/assets/flux-grid/...`, which shadowed the
 * runtime model pack committed under `web/public/assets/flux-grid/` and left
 * the Asset Lab with no manifest to read. `scripts/e2e-stack.mjs` now boots
 * `copilot.app` beside the static origin and points the forward at it.
 *
 * These assertions are request-level on purpose: they need no page, so they
 * state the API's presence independently of anything the browser does with it.
 * Kill the API and both fail.
 */

test("the origin forwards the runtime asset pack from the real API", async ({ request }) => {
  const response = await request.get("/assets/flux-grid/manifest.json");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  const manifest = await response.json();
  // The pack `copilot/config.py` serves by default. 18 archetypes, 3 LODs each.
  expect(manifest.assets).toHaveLength(18);
  expect(manifest.assets.flatMap((asset: { lods: Record<string, unknown> }) => Object.values(asset.lods))).toHaveLength(54);

  // And a model itself crosses the forward, not just its index.
  const glb = manifest.assets[0].lods.lod0.path as string;
  const model = await request.get(`/assets/flux-grid/${glb}`);
  expect(model.status()).toBe(200);
  expect(model.headers()["content-type"]).toBe("model/gltf-binary");
  expect((await model.body()).byteLength).toBeGreaterThan(1024);
});

test("a read the API cannot serve is refused by the API, in its own words", async ({ request }) => {
  // A clean clone has no `data/duck/grid.duckdb` (docs/runbooks: expected
  // first-run state, not a fault), so the API answers its own named envelope.
  // That is the whole point of this assertion: with no API running, the same
  // path answers 503 `no_api_origin_configured` from `web/server.mjs`, and the
  // difference between "the API refused" and "there was no API" is exactly what
  // a browser proof of a server-backed App must be able to see.
  const response = await request.get("/layers/buses");
  expect(response.status()).toBe(503);
  const envelope = await response.json();
  expect(envelope.status).toBe("unavailable");
  expect(envelope.error.code).toBe("unavailable");
  expect(envelope.error.details).toEqual({ artifact: "database", reason: "missing" });
  expect(envelope.error.details.reason).not.toBe("no_api_origin_configured");
});
