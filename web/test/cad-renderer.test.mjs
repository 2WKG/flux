import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

const webRoot = new URL("../", import.meta.url);
// Keep compiled modules under this package's node_modules so their external
// React/deck imports resolve exactly as the production bundle resolves them.
const folder = await mkdtemp(new URL("../node_modules/.flux-cad-renderer-", import.meta.url).pathname);
test.after(() => rm(folder, { recursive: true, force: true }));

async function moduleAt(relative, name) {
  const result = await build({
    entryPoints: [new URL(relative, webRoot).pathname],
    bundle: true,
    packages: "external",
    platform: "node",
    format: "esm",
    write: false,
  });
  const target = path.join(folder, name);
  await writeFile(target, result.outputFiles[0].text);
  return import(pathToFileURL(target).href);
}

const pack = await moduleAt("src/renderer/asset-pack.ts", "asset-pack.mjs");
const layer = await moduleAt("src/renderer/FluxAssetLayer.tsx", "asset-layer.mjs");

test("missing CAD files are an install prerequisite, without attempting to parse the SPA HTML fallback", () => {
  const fallback = new Response("<!doctype html><title>Flux</title>", {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
  assert.throws(
    () => pack.assertAssetResponse(fallback, "manifest", "/assets/flux-grid/manifest.json"),
    (error) => error instanceof pack.AssetPackError && error.state === "install_required",
  );
  const notice = pack.assetPackNotice("install_required", "The optional 3D asset pack is not installed.");
  assert.equal(notice.heading, "3D asset pack install required");
  assert.match(notice.action, /install_flux_grid_pack\.mjs/);
  assert.match(notice.action, /not published/i);
});

test("manifest and GLB responses require their declared HTTP media types", () => {
  assert.doesNotThrow(() => pack.assertAssetResponse(
    new Response("{}", { headers: { "content-type": "application/json; charset=utf-8" } }),
    "manifest",
    "manifest.json",
  ));
  assert.throws(
    () => pack.assertAssetResponse(
      new Response("{}", { headers: { "content-type": "application/json" } }),
      "model",
      "substation.lod2.glb",
    ),
    (error) => error instanceof pack.AssetPackError && error.state === "request_failed" && /model\/gltf-binary/.test(error.message),
  );
  assert.throws(
    () => pack.assertAssetResponse(new Response(null, { status: 404 }), "model", "substation.lod2.glb"),
    (error) => error instanceof pack.AssetPackError && error.state === "install_required",
  );
});

test("the CAD LOD follows MapLibre camera zoom instead of a fixed renderer zoom", async () => {
  assert.deepEqual([11.9, 12, 15, 17].map(layer.assetLodForZoom), ["symbol", "lod2", "lod1", "lod0"]);
  const [gridMap, foundation] = await Promise.all([
    readFile(new URL("src/renderer/GridMap.tsx", webRoot), "utf8"),
    readFile(new URL("src/renderer/MapLibreDeckFoundation.tsx", webRoot), "utf8"),
  ]);
  assert.doesNotMatch(gridMap, /<FluxAssetLayer[\s\S]*zoom=\{12\}/);
  assert.match(gridMap, /zoom=\{zoom\}/);
  assert.match(gridMap, /onZoomChange=\{setZoom\}/);
  assert.match(foundation, /onLoad=\{\(event\) => onZoomChange\?\.\(event\.target\.getZoom\(\)\)\}/);
  assert.match(foundation, /onMove=\{\(event\) => onZoomChange\?\.\(event\.viewState\.zoom\)\}/);
});
