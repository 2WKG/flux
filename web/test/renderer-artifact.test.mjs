import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { build } from "esbuild";

/**
 * What must be true of the *built* renderer for it to exist at all.
 *
 * The renderer is now mounted in the one App: 2WKG-355 composed the
 * physical-inventory map into `main.tsx` behind a browser-only dynamic import,
 * so the shipped `dist/` bundle contains MapLibre and must carry its two
 * runtime files. It also still ships behind its own harness entry
 * (`npm run build:renderer-harness`), which is what this file builds and
 * asserts -- the artifact, not the source.
 *
 * The control for the conditional copy is therefore no longer the demo build
 * (which now does bundle MapLibre); it is a probe entry built here that does
 * not, so an unconditional `cp()` in `scripts/build.mjs` still fails.
 *
 * Three mutations that previously left the whole suite green fail here: dropping
 * the renderer from the harness entry, dropping either MapLibre runtime copy
 * from `scripts/build.mjs`, and reintroducing a remote basemap.
 */
const run = promisify(execFile);
const webRoot = fileURLToPath(new URL("../", import.meta.url));
const harnessDist = new URL("../dist-renderer-harness/", import.meta.url);
const read = (name) => readFile(new URL(name, harnessDist), "utf8");

// Built once for the whole file; `npm run build:renderer-harness` runs the same
// scripts/build.mjs the app build runs, with the renderer entry.
await run("npm", ["run", "build:renderer-harness"], { cwd: webRoot });

test("the renderer ships in the built harness bundle", async () => {
  const app = await read("assets/app.js");
  // The component's own aria-label. Present only when the module is in the
  // bundle graph, which requires the entry to import and render it.
  assert.ok(app.includes("Map and renderer status"), "the renderer is absent from the built bundle");
  assert.ok(app.includes("accepted-scene-nodes"), "the accepted-node layer id is absent from the bundle");
});

test("a bundle that needs the MapLibre worker gets both runtime files beside it", async () => {
  // maplibre-gl-worker.mjs is fetched from /assets by the bundled getWorkerUrl
  // path, and the worker itself imports ./maplibre-gl-shared.mjs from the same
  // directory. Neither is inlined into app.js, so dropping either cp() breaks
  // map rendering with a 404 the UI cannot recover from.
  for (const name of ["assets/maplibre-gl-worker.mjs", "assets/maplibre-gl-shared.mjs"]) {
    const info = await stat(new URL(name, harnessDist)).catch(() => null);
    assert.ok(info !== null, `${name} is missing from dist-renderer-harness/`);
    assert.ok(info.size > 1024, `${name} is present but empty (${info?.size} bytes)`);
  }
  const worker = await read("assets/maplibre-gl-worker.mjs");
  assert.match(worker, /["'`]\.\/maplibre-gl-shared\.mjs["'`]/, "the worker no longer resolves the shared module from ./");
});

test("a bundle that does not use MapLibre carries neither runtime file", { timeout: 120000 }, async () => {
  // The control for the conditional copy: an entry with no MapLibre in its
  // graph at all. An unconditional cp() in scripts/build.mjs fails here.
  const dir = await mkdtemp(path.join(os.tmpdir(), "flux-nomap-dist-"));
  const entry = path.join(dir, "probe.tsx");
  try {
    await writeFile(entry, 'export const probe = "no maplibre in this graph";\n');
    await run("node", ["scripts/build.mjs"], {
      cwd: webRoot,
      env: { ...process.env, FLUX_WEB_ENTRY: entry, FLUX_WEB_DIST: path.join(dir, "dist") },
    });
    const probeApp = await readFile(path.join(dir, "dist", "assets", "app.js"), "utf8");
    assert.ok(!probeApp.includes("maplibre-gl-worker.mjs"), "the probe entry unexpectedly bundled MapLibre");
    for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
      const info = await stat(path.join(dir, "dist", "assets", name)).catch(() => null);
      assert.equal(info, null, `${name} was copied into a build that does not bundle MapLibre`);
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("the shipped app build carries both MapLibre runtime files", async () => {
  // The one App mounts the map, so the demo bundle needs them beside app.js.
  const app = await readFile(new URL("../dist/assets/app.js", import.meta.url), "utf8");
  assert.ok(app.includes("maplibre-gl-worker.mjs"), "the app bundle no longer resolves the MapLibre worker");
  for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
    const info = await stat(new URL(`../dist/assets/${name}`, import.meta.url)).catch(() => null);
    assert.ok(info !== null && info.size > 1024, `${name} is missing from the shipped dist/`);
  }
});

/** The style module, compiled and evaluated, so the object itself is asserted. */
let basemapPromise;
function basemapModule() {
  basemapPromise ??= (async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "flux-basemap-"));
    const outfile = path.join(dir, "basemap.mjs");
    await build({
      entryPoints: [path.join(webRoot, "src/renderer/basemap.ts")],
      outfile, bundle: true, format: "esm", platform: "neutral",
      absWorkingDir: webRoot, nodePaths: [path.join(webRoot, "node_modules")], logLevel: "silent",
    });
    return import(pathToFileURL(outfile).href);
  })();
  return basemapPromise;
}

test("the shipped basemap reaches no origin but this one", async () => {
  // An allowlist over the style, not a denylist over vendors. This assertion
  // used to name four hosts (`tiles.openfreemap.org`, `demotiles.maplibre.org`,
  // `api.maptiler.com`, `api.mapbox.com`), and a live
  // `https://tile.openstreetmap.org/{z}/{x}/{y}.png` raster source shipped
  // through it with the whole suite green -- a denylist can only see the
  // vendors somebody already thought of, and "self-hosted" is a claim about
  // *every* origin, not four of them.
  //
  // What is actually claimed -- "no API required", "issues no network request"
  // -- is a property of the style object: every URL it names must be
  // same-origin, and `data:`/`blob:` are the only other schemes a style may
  // carry, because neither leaves the document.
  const style = (await basemapModule()).OFFLINE_BASEMAP_STYLE;
  assert.deepEqual(Object.keys(style.sources ?? {}), [], "the offline style declares a tile source");
  for (const absent of ["glyphs", "sprite"]) {
    assert.equal(style[absent], undefined, `the offline style names a remote ${absent} endpoint`);
  }
  const offOrigin = [];
  const walk = (value, at) => {
    if (typeof value === "string") {
      if (/^([a-z][a-z0-9+.-]*:)?\/\//i.test(value) && !/^(data|blob):/i.test(value)) offOrigin.push(`${at} = ${value}`);
      return;
    }
    if (Array.isArray(value)) return value.forEach((entry, index) => walk(entry, `${at}[${index}]`));
    if (value && typeof value === "object") for (const [key, entry] of Object.entries(value)) walk(entry, `${at}.${key}`);
  };
  walk(style, "style");
  assert.deepEqual(offOrigin, [], `the offline style names off-origin URLs: ${offOrigin.join(", ")}`);

  // And the same property over the built artifact, which is what ships: an
  // XYZ tile template is how every raster and vector tile vendor addresses
  // tiles, so its absence is vendor-independent in a way a host list is not.
  const app = await read("assets/app.js");
  assert.doesNotMatch(app, /\{z\}\/\{x\}\/\{y\}/, "the bundle carries an XYZ tile template, so a remote basemap ships in it");
  assert.ok(app.includes("Flux offline geometry-free basemap"), "the offline style is not in the bundle");
});

test("the served shell carries a CSP that blocks every off-origin request", async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  const csp = /content="([^"]*)"/.exec(
    /<meta http-equiv="Content-Security-Policy"[^>]*>/.exec(html)?.[0] ?? "",
  )?.[1];
  assert.ok(csp, "dist/index.html carries no Content-Security-Policy meta tag");

  const directives = Object.fromEntries(
    csp.split(";").map((part) => part.trim().split(/\s+/)).filter((parts) => parts[0]).map(([name, ...values]) => [name, values]),
  );
  // connect-src is what a tile/style/glyph request travels on; img-src is what a
  // raster tile would arrive as. Neither may name a host or a wildcard.
  for (const directive of ["default-src", "connect-src", "img-src", "script-src", "font-src"]) {
    assert.ok(directives[directive], `CSP has no ${directive}`);
    for (const value of directives[directive]) {
      assert.ok(
      ["'self'", "'none'", "data:", "blob:", "'unsafe-inline'", "'wasm-unsafe-eval'"].includes(value),
        `${directive} allows ${value}, which can reach an off-origin server`,
      );
    }
  }
  assert.ok(directives["connect-src"].includes("'self'"));
  assert.ok(!directives["connect-src"].includes("*"));
});

test("the overlay's initialized signal comes from deck's own load event, not from mount", async () => {
  // Structural, not behavioural, and labelled as such: deck's onLoad fires in every
  // runtime state that could be produced (WebGL denied, worker 404, rAF disabled,
  // extensions denied, shader/program failure, CSP-blocked style), so no browser
  // probe separates it from a mount effect. What is checkable is where the signal
  // is wired from.
  const source = await readFile(new URL("../src/renderer/DeckOverlay.tsx", import.meta.url), "utf8");
  const construction = /new MapboxOverlay\(\{[\s\S]*?\}\)/.exec(source)?.[0];
  assert.ok(construction, "DeckOverlay no longer constructs a MapboxOverlay");
  assert.match(construction, /onLoad:/, "deck's onLoad must carry the initialized signal");
  assert.match(construction, /onError:/, "deck's onError must carry the failure signal");
  for (const effect of source.matchAll(/useEffect\(\(\) => \{[\s\S]*?\}, \[[^\]]*\]\)/g)) {
    assert.doesNotMatch(
      effect[0],
      /initialized\.current|onInitialized/,
      "an effect must not report initialization; only deck's onLoad may",
    );
  }
});
