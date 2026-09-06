import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

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
  // "The bundle" is the entry *and* its chunks: 2WKG-478 split the pages into
  // dynamic imports, so the worker URL now survives into whichever chunk the map
  // code landed in, which is exactly the set `scripts/build.mjs` itself scans
  // before copying. Reading only `app.js` here would have failed on a build
  // that ships the worker correctly.
  const assets = await readdir(new URL("../dist/assets/", import.meta.url));
  const app = (
    await Promise.all(
      assets
        .filter((name) => name.endsWith(".js"))
        .map((name) => readFile(new URL(`../dist/assets/${name}`, import.meta.url), "utf8")),
    )
  ).join("\n");
  assert.ok(app.includes("maplibre-gl-worker.mjs"), "the app bundle no longer resolves the MapLibre worker");
  for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
    const info = await stat(new URL(`../dist/assets/${name}`, import.meta.url)).catch(() => null);
    assert.ok(info !== null && info.size > 1024, `${name} is missing from the shipped dist/`);
  }
});

test("no remote basemap origin ships in the renderer bundle", async () => {
  const app = await read("assets/app.js");
  for (const host of ["tiles.openfreemap.org", "demotiles.maplibre.org", "api.maptiler.com", "api.mapbox.com"]) {
    assert.ok(!app.includes(host), `the bundle references the remote basemap host ${host}`);
  }
  // The offline style is the one the renderer actually mounts.
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
  // script-src is excluded here and pinned exactly below: it is the one
  // directive that legitimately carries a non-origin token.
  for (const directive of ["default-src", "connect-src", "img-src", "font-src"]) {
    assert.ok(directives[directive], `CSP has no ${directive}`);
    for (const value of directives[directive]) {
      assert.ok(
        ["'self'", "'none'", "data:", "blob:", "'unsafe-inline'"].includes(value),
        `${directive} allows ${value}, which can reach an off-origin server`,
      );
    }
  }
  assert.ok(directives["connect-src"].includes("'self'"));
  assert.ok(!directives["connect-src"].includes("*"));

  // script-src is pinned EXACTLY, not merely drawn from the allowlist above.
  // An allowlist cannot fail for any token already on it, so
  // `script-src 'self' 'unsafe-inline'` -- or a third token appended after
  // 'wasm-unsafe-eval' -- would have stayed green. Any further widening of this
  // directive now goes red and has to be argued for here.
  //
  // 'wasm-unsafe-eval' is required, and the consumer is named by the assertion
  // below it: deck.gl's GLB path pulls @loaders.gl's draco and basis decoders,
  // which compile WebAssembly at runtime. `server.mjs`'s served
  // CONTENT_SECURITY_POLICY header must carry the same token, because a browser
  // enforces the intersection of the header and this meta tag -- relaxing only
  // one of the two is inert, which is how the first version of this change
  // shipped a directive that never took effect.
  assert.deepEqual(directives["script-src"], ["'self'", "'wasm-unsafe-eval'"],
    "script-src must stay exactly 'self' plus the WebAssembly allowance the 3D asset decoders need");
  assert.deepEqual(directives["object-src"], ["'none'"]);
  assert.deepEqual(directives["base-uri"], ["'none'"]);

  // The two policies must agree, or the weaker one silently wins.
  const { CONTENT_SECURITY_POLICY } = await import("../server.mjs");
  const served = Object.fromEntries(
    CONTENT_SECURITY_POLICY.split(";").map((part) => part.trim().split(/\s+/)).filter((parts) => parts[0]).map(([name, ...values]) => [name, values]),
  );
  assert.deepEqual(served["script-src"], directives["script-src"],
    "the served header and the shell's meta tag must name the same script-src, or the relaxation is inert");
});

test("the CSP's WebAssembly allowance is required by code the bundle actually ships", async () => {
  // The justification for 'wasm-unsafe-eval', asserted rather than asserted-in-prose.
  // If the WASM decoders ever leave the bundle this goes red, and the directive
  // must be removed with it rather than lingering as an unexplained relaxation.
  const files = (await readdir(new URL("../dist/assets/", import.meta.url))).filter((name) => name.endsWith(".js"));
  const bundle = (await Promise.all(files.map((name) => readFile(new URL(`../dist/assets/${name}`, import.meta.url), "utf8")))).join("\n");
  assert.match(bundle, /WebAssembly\.(?:instantiate|compile)/,
    "no shipped chunk compiles WebAssembly, so script-src must not carry 'wasm-unsafe-eval'");
  assert.match(bundle, /draco_decoder\.wasm|basis_transcoder\.wasm/,
    "the named consumers of the WebAssembly allowance (loaders.gl draco/basis) are not in the bundle");
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
