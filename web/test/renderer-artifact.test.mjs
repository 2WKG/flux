import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";

/**
 * What the built artifact must be true of for the renderer to exist at all.
 *
 * `npm run build` runs before these (gate/web and `npm run test:static-demo`
 * both build first), so `dist/` is the thing under test, not a mock. Three
 * mutations that previously left the whole suite green now fail here:
 * unwiring `<MapLibreDeckFoundation/>` from the app shell, dropping either
 * MapLibre runtime copy from `scripts/build.mjs`, and reintroducing a remote
 * basemap into the static demo.
 */
const read = (name) => readFile(new URL(`../dist/${name}`, import.meta.url), "utf8");

test("the renderer is wired into the app shell, in source and in the bundle", async () => {
  const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.match(source, /<MapLibreDeckFoundation\b/, "main.tsx must mount the renderer");
  assert.match(source, /from "\.\/renderer\/MapLibreDeckFoundation"/);

  const app = await read("assets/app.js");
  // The component's own aria-label. Present only when the module is in the
  // bundle graph, which requires main.tsx to import and render it.
  assert.ok(app.includes("Map and renderer status"), "the renderer is absent from the built bundle");
  assert.ok(app.includes("accepted-scene-nodes"), "the accepted-node layer id is absent from the bundle");
});

test("the build packages both MapLibre runtime files the worker resolves at runtime", async () => {
  // maplibre-gl-worker.mjs is fetched from /assets by the bundled Gi2()/getWorkerUrl
  // path, and the worker itself imports ./maplibre-gl-shared.mjs from the same
  // directory (verified: `grep maplibre-gl-shared.mjs dist/assets/maplibre-gl-worker.mjs`).
  // Neither is inlined into app.js, so dropping either cp() breaks map rendering.
  for (const name of ["assets/maplibre-gl-worker.mjs", "assets/maplibre-gl-shared.mjs"]) {
    const info = await stat(new URL(`../dist/${name}`, import.meta.url)).catch(() => null);
    assert.ok(info !== null, `${name} is missing from dist/`);
    assert.ok(info.size > 1024, `${name} is present but empty (${info?.size} bytes)`);
  }
  const worker = await read("assets/maplibre-gl-worker.mjs");
  assert.match(worker, /["'`]\.\/maplibre-gl-shared\.mjs["'`]/, "the worker no longer resolves the shared module from ./");
});

test("the static demo fetches no basemap: no remote style, tile, glyph, or sprite origin ships in it", async () => {
  const app = await read("assets/app.js");
  for (const host of ["tiles.openfreemap.org", "demotiles.maplibre.org", "api.maptiler.com", "api.mapbox.com"]) {
    assert.ok(!app.includes(host), `the bundle references the remote basemap host ${host}`);
  }
  // The offline style is the one the demo actually mounts.
  assert.ok(app.includes("Flux offline geometry-free basemap"), "the offline style is not in the bundle");
});

test("the shipped source makes no fetch call of its own", async () => {
  // Restores the invariant the app's own source must satisfy: the static demo
  // originates no request. (The bundle-level form of this grep cannot be used
  // while any library is bundled; `connect-src 'self'` plus the Playwright
  // origin monitor in e2e/static-explorer.spec.ts cover the runtime side.)
  const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\bfetch\s*\(/);
});

test("the served shell carries a CSP that blocks every off-origin request", async () => {
  const html = await read("index.html");
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
        ["'self'", "'none'", "data:", "blob:", "'unsafe-inline'"].includes(value),
        `${directive} allows ${value}, which can reach an off-origin server`,
      );
    }
  }
  assert.ok(directives["connect-src"].includes("'self'"));
  assert.ok(!directives["connect-src"].includes("*"));
});

test("the overlay's initialized signal comes from deck's own load event, not from mount", async () => {
  // Structural, not behavioural, and labelled as such: deck's onLoad fires in every
  // runtime state I could produce (WebGL denied, worker 404, rAF disabled, extensions
  // denied, shader/program failure, CSP-blocked style), so no browser probe separates
  // it from a mount effect. What is checkable is where the signal is wired from.
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
