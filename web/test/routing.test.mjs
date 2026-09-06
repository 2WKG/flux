/**
 * The routing split (2WKG-478).
 *
 * Two claims are worth pinning and neither can be read off source text: that a
 * path resolves to the page it names, and that each page is actually a separate
 * download. The second is asserted on the built artifact -- the entry chunk must
 * carry neither page's payload, and the two pages must not land in one chunk --
 * because that is the only thing that makes "split the entries" different from
 * "put both pages in one bundle behind an if".
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { builtScriptNames } from "./built-assets.mjs";

const webRoot = new URL("../", import.meta.url);
const assets = new URL("dist/assets/", webRoot);
const compiled = new URL("../node_modules/.cache/flux-routing.mjs", import.meta.url);

await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ROUTES, routeForPath } from "./src/router";
      import { SiteNav } from "./src/shell/SiteNav";
      import { TruthLegend } from "./src/shell/TruthLegend";
      export { ROUTES, routeForPath };
      export { STATUS_COPY } from "./src/source-truth";
      export const renderNav = (route) =>
        renderToStaticMarkup(createElement(SiteNav, { current: route, onNavigate: () => {} }));
      export const renderLegend = (route) =>
        renderToStaticMarkup(createElement(TruthLegend, { statuses: route.truthLabels, note: route.truthNote }));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "routing-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const site = await import(compiled.href);

const route = (id) => site.ROUTES.find((entry) => entry.id === id);

test("each page has its own path, and an unmatched path falls back to the explorer", () => {
  assert.deepEqual(site.ROUTES.map((entry) => entry.path), ["/", "/explainer", "/minnesota"]);
  assert.equal(site.routeForPath("/").id, "main");
  assert.equal(site.routeForPath("/explainer").id, "explainer");
  assert.equal(site.routeForPath("/minnesota").id, "minnesota");
  // A deep link with a trailing slash is the same page, not a miss.
  assert.equal(site.routeForPath("/explainer/").id, "explainer");
  assert.equal(site.routeForPath("/minnesota/").id, "minnesota");
  // Page paths outside the route table are the explorer rather than a blank screen.
  // `web/server.mjs` intercepts API-shaped requests before they reach this matcher.
  assert.equal(site.routeForPath("/nothing-here").id, "main");
});

test("the shared navigation reaches every page and marks the current one", () => {
  for (const current of site.ROUTES) {
    const markup = site.renderNav(current);
    for (const entry of site.ROUTES) {
      // A real href, so a deep link can be copied, opened in a new tab, or bookmarked.
      assert.ok(markup.includes(`href="${entry.path}"`), `${current.id} nav does not link ${entry.path}`);
      assert.ok(markup.includes(entry.label), `${current.id} nav does not name ${entry.label}`);
    }
    const currentLinks = [...markup.matchAll(/aria-current="page"/g)];
    assert.equal(currentLinks.length, 1, `${current.id} nav marks ${currentLinks.length} links as current`);
    const marked = /<a[^>]*aria-current="page"[^>]*href="([^"]*)"|<a[^>]*href="([^"]*)"[^>]*aria-current="page"/.exec(markup);
    assert.equal(marked?.[1] ?? marked?.[2], current.path);
  }
});

test("the truth-label legend renders the owner's copy, identically on both pages", () => {
  const rendered = new Map();
  for (const current of site.ROUTES) {
    const markup = site.renderLegend(current);
    for (const status of current.truthLabels) {
      const item = `<li data-truth-label="${status}">${site.STATUS_COPY[status]}</li>`;
      assert.ok(markup.includes(item), `${current.id} does not render ${status} as its owner spells it`);
      const seen = rendered.get(status);
      assert.ok(seen === undefined || seen === item, `${status} renders differently on ${current.id}`);
      rendered.set(status, item);
    }
    // A page never displays a label its own data does not carry.
    for (const status of ["source_supported", "source_screened"]) {
      assert.ok(!markup.includes(site.STATUS_COPY[status]), `${current.id} claims ${status}`);
    }
  }
  // The one token both pages assert, so "identically on both" is a real check.
  assert.ok(rendered.has("synthetic"));
});

test("each page is its own chunk: the entry carries neither, and no chunk carries both", async () => {
  const names = await builtScriptNames();
  assert.equal(names[0], "app.js", "the entry must still be served at assets/app.js");
  assert.ok(names.length > 1, "the build emitted no chunks, so the pages were not split");

  const fixture = JSON.parse(await readFile(new URL("../../data/demo/bundle.json", import.meta.url), "utf8"));
  // One marker per page, each unique to that page's module graph.
  const scenarioMarker = fixture.fixtureHash;
  const explainerMarker = "How the math works: follow a five-bus cascade, one equation at a time.";

  const chunks = new Map();
  for (const name of names) chunks.set(name, await readFile(new URL(name, assets), "utf8"));

  const entry = chunks.get("app.js");
  assert.ok(!entry.includes(scenarioMarker), "the scenario page is in the entry chunk, so the explainer downloads it");
  assert.ok(!entry.includes(explainerMarker), "the explainer is in the entry chunk, so the scenario page downloads it");

  const carrying = (marker) => names.filter((name) => chunks.get(name).includes(marker));
  const scenarioChunks = carrying(scenarioMarker);
  const explainerChunks = carrying(explainerMarker);
  assert.equal(scenarioChunks.length, 1, `the scenario page ships in ${scenarioChunks.length} chunks`);
  assert.equal(explainerChunks.length, 1, `the explainer ships in ${explainerChunks.length} chunks`);
  assert.notEqual(scenarioChunks[0], explainerChunks[0], "both pages ship in the same chunk");
});
