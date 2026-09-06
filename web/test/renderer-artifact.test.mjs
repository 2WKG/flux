import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

/**
 * What must be true of the *built* renderer for it to exist at all.
 *
 * The renderer is not mounted in the frozen static demo: `main.tsx` is master's
 * shell, and two landed gates forbid mounting a MapLibre surface there —
 * `test/static-demo.test.mjs` asserts the demo bundle contains no `fetch(` at
 * all, and `test/viewport-shell.test.mjs` asserts no class reaches the DOM
 * without a rule in `src/styles.css`. Whether the demo shows a map is a product
 * decision, not a merge decision. So the renderer ships behind its own build
 * entry (`npm run build:renderer-harness`), and this file builds that entry and
 * asserts the artifact, not the source.
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

test("a bundle that does not use MapLibre carries neither runtime file", async () => {
  // The demo build is the control: the copy is conditional on the bundle, so an
  // unconditional cp() (half a megabyte of dead weight in the demo) fails here.
  for (const name of ["assets/maplibre-gl-worker.mjs", "assets/maplibre-gl-shared.mjs"]) {
    const info = await stat(new URL(`../dist/${name}`, import.meta.url)).catch(() => null);
    assert.equal(info, null, `${name} was copied into the demo build, which does not bundle MapLibre`);
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
