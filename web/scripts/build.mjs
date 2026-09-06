import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertBrowserBundle } from "./assert-browser-bundle.mjs";

const webRoot = path.dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
// Test seams only: FLUX_WEB_ENTRY / FLUX_WEB_DIST let the bundle-boundary test build a
// probe entry into a scratch directory without touching src/ or dist/.
const entry = process.env.FLUX_WEB_ENTRY ? path.resolve(process.env.FLUX_WEB_ENTRY) : path.join(webRoot, "src", "main.tsx");
const dist = process.env.FLUX_WEB_DIST ? path.resolve(process.env.FLUX_WEB_DIST) : path.join(webRoot, "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(path.join(dist, "assets"), { recursive: true });
await cp(path.join(webRoot, "index.html"), path.join(dist, "index.html"));
// MapLibre's ESM bundle resolves this worker from the absolute assets path.
// Keep the installed, version-locked artifact with the browser bundle rather than
// falling back to a CDN or allowing a missing worker to degrade map rendering.
await cp(
  path.join(webRoot, "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs"),
  path.join(dist, "assets", "maplibre-gl-worker.mjs"),
);
await cp(
  path.join(webRoot, "node_modules", "maplibre-gl", "dist", "maplibre-gl-shared.mjs"),
  path.join(dist, "assets", "maplibre-gl-shared.mjs"),
);

const result = await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2020",
  outfile: path.join(dist, "assets", "app.js"),
  sourcemap: true,
  metafile: true,
  // Metafile input keys are relative to absWorkingDir; pin it to web/ so the boundary
  // check does not depend on the caller's cwd (running from the repo root used to bypass it).
  absWorkingDir: webRoot,
});

try {
  assertBrowserBundle(result.metafile, webRoot);
} catch (error) {
  // Do not leave a bundle that crossed the boundary where server.mjs would serve it.
  await rm(dist, { recursive: true, force: true });
  throw error;
}
