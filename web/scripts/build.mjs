import { build } from "esbuild";
import { cp, mkdir, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertBrowserBundle } from "./assert-browser-bundle.mjs";

const webRoot = path.dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
// Test seams only: FLUX_WEB_ENTRY / FLUX_WEB_DIST let the bundle-boundary test build a
// probe entry into a scratch directory without touching src/ or dist/.
const entry = process.env.FLUX_WEB_ENTRY ? path.resolve(process.env.FLUX_WEB_ENTRY) : path.join(webRoot, "src", "main.tsx");
const dist = process.env.FLUX_WEB_DIST ? path.resolve(process.env.FLUX_WEB_DIST) : path.join(webRoot, "dist");
// FLUX_WEB_HTML picks the page copied in as dist/index.html, so a harness entry can ship
// its own page instead of silently borrowing the app's and its stylesheet link.
const html = process.env.FLUX_WEB_HTML ? path.resolve(process.env.FLUX_WEB_HTML) : path.join(webRoot, "index.html");

await rm(dist, { recursive: true, force: true });
await mkdir(path.join(dist, "assets"), { recursive: true });
await cp(html, path.join(dist, "index.html"));

const result = await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2020",
  // Code splitting, not a single file: each page is a dynamic import in
  // src/shell/SiteShell.tsx, and esbuild emits one chunk per page so a visitor
  // downloads the entry plus their own page. `entryNames` keeps the entry at the
  // `assets/app.js` path index.html, the harness pages, and the runbooks name.
  outdir: path.join(dist, "assets"),
  entryNames: "app",
  chunkNames: "chunk-[hash]",
  splitting: true,
  sourcemap: true,
  metafile: true,
  // Metafile input keys are relative to absWorkingDir; pin it to web/ so the boundary
  // check does not depend on the caller's cwd (running from the repo root used to bypass it).
  absWorkingDir: webRoot,
});

// MapLibre's ESM bundle resolves its worker from the absolute /assets path at
// runtime, and that worker imports ./maplibre-gl-shared.mjs from the same
// directory. Neither is inlined by esbuild, so an entry that bundles MapLibre
// needs both files beside app.js -- and an entry that does not must not carry
// half a megabyte of dead weight. The bundle itself decides, by whether the
// worker URL survived into it.
// The entry and every chunk beside it are one bundle for this purpose: the
// worker URL may survive into whichever chunk the map code landed in.
const built = await readdir(path.join(dist, "assets"));
const bundledApp = (
  await Promise.all(
    built
      .filter((name) => name.endsWith(".js"))
      .map((name) => readFile(path.join(dist, "assets", name), "utf8")),
  )
).join("\n");
if (bundledApp.includes("maplibre-gl-worker.mjs")) {
  for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
    await cp(
      path.join(webRoot, "node_modules", "maplibre-gl", "dist", name),
      path.join(dist, "assets", name),
    );
  }
}

try {
  assertBrowserBundle(result.metafile, webRoot);
} catch (error) {
  // Do not leave a bundle that crossed the boundary where server.mjs would serve it.
  await rm(dist, { recursive: true, force: true });
  throw error;
}
