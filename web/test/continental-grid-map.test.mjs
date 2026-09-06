/**
 * The continental map's failure arm, driven in a real DOM.
 *
 * `loadGridLayer` reduces a transport failure to a `refused` *outcome*, so the
 * only thing that can reject the `Promise.all` over the layer reads is the
 * reader itself throwing. That arm had no `.catch`: a rejection became an
 * unhandled promise rejection and the map kept painting an empty asset set with
 * no disclosure at all, which is precisely the "fake-fine" state the recovery
 * walk forbids. These two tests pin that a rejected read reaches the component's
 * own named `error` state, and that the harness can tell the two arms apart.
 */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";
import { JSDOM } from "jsdom";

const webRoot = path.dirname(new URL("../package.json", import.meta.url).pathname);

// React's scheduler posts through a MessageChannel, whose real node ports keep
// the event loop alive and hang the runner after the last test. Same shim as
// `test/chat-dock.test.mjs`; same contract, settled on the macrotask queue.
globalThis.MessageChannel = class {
  constructor() {
    let handler = null;
    this.port1 = { set onmessage(value) { handler = value; }, get onmessage() { return handler; }, close() { handler = null; } };
    this.port2 = { postMessage: (data) => { setImmediate(() => handler?.({ data })); }, close() {} };
  }
};

const PROBE = `
export { act } from "react";
export { createElement } from "react";
export { createRoot } from "react-dom/client";
export { ContinentalGridMap } from ${JSON.stringify(path.join(webRoot, "src/renderer/ContinentalGridMap.tsx"))};
`;

let probePromise;
function probe() {
  probePromise ??= (async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "flux-continental-probe-"));
    const entry = path.join(dir, "probe.tsx");
    const outfile = path.join(dir, "probe.mjs");
    await writeFile(entry, PROBE, "utf8");
    await build({
      entryPoints: [entry], outfile, bundle: true, format: "esm", platform: "browser",
      target: "es2020", absWorkingDir: webRoot, tsconfig: path.join(webRoot, "tsconfig.json"),
      nodePaths: [path.join(webRoot, "node_modules")], loader: { ".css": "empty" },
      define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    });
    return outfile;
  })();
  return probePromise;
}

const BOUNDARY_URL = "/assets/boundaries/conus-states-2024-5m.geojson";

/** Mount the map with both of its two reads under the test's control. */
async function mounted({ boundary, loadLayer }, assertions) {
  const outfile = await probe();
  const dom = new JSDOM("<!doctype html><div id='root'></div>", { url: "http://localhost/" });
  const previous = {};
  const globals = {
    window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true,
    // MapLibre reads it while the first (pre-effect) render still paints the map.
    devicePixelRatio: 1,
    // The boundary arm is the *other* read; a test names what it does so the
    // arm under test is the only one that can produce the state asserted.
    fetch: async (url) => {
      assert.equal(String(url), BOUNDARY_URL, `the component fetched an unexpected url: ${url}`);
      return boundary();
    },
  };
  for (const [key, value] of Object.entries(globals)) {
    previous[key] = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  const api = await import(pathToFileURL(outfile).href);
  const container = dom.window.document.getElementById("root");
  const root = api.createRoot(container);
  try {
    await api.act(async () => {
      root.render(api.createElement(api.ContinentalGridMap, {
        selectedRegion: "texas", onRegionSelect: () => {}, loadLayer,
      }));
    });
    // Both reads settle on the microtask queue; `act` flushes the renders they schedule.
    await api.act(async () => { await new Promise((resolve) => setImmediate(resolve)); });
    return await assertions({ container, api });
  } finally {
    await api.act(() => { root.unmount(); });
    for (const key of Object.keys(globals)) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    dom.window.close();
  }
}

const okBoundary = () => Promise.resolve({ ok: true, status: 200, json: async () => ({ type: "FeatureCollection", features: [] }) });

test("a rejected layer read becomes the map's named error state, not an unhandled rejection", async () => {
  // The boundary read succeeds, so nothing but the layer arm can produce a
  // failure here. Remove the `.catch` on the layer `Promise.all` and this goes
  // red: the component renders its map with an empty asset set and no reason.
  const rejections = [];
  const onRejection = (reason) => rejections.push(reason);
  process.on("unhandledRejection", onRejection);
  try {
    await mounted({
      boundary: okBoundary,
      loadLayer: () => Promise.reject(new Error("layer read exploded")),
    }, async ({ container }) => {
      assert.match(container.textContent, /National map unavailable: layer read exploded/);
      // The recovery walk: the region controls stay operable in the failed state.
      assert.equal(container.querySelectorAll("button").length, 2);
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(rejections.map(String), [], "the failed read must be a named state, never an unhandled rejection");
  } finally {
    process.off("unhandledRejection", onRejection);
  }
});

test("the boundary arm is the other read, and it names its own failure", async () => {
  // The control for the test above: this harness can observe the error state
  // produced by the *boundary* arm too, so a green above is not the harness
  // simply failing to see anything.
  await mounted({
    boundary: () => Promise.resolve({ ok: false, status: 503, json: async () => ({}) }),
    loadLayer: async () => ({ kind: "refused", status: "unavailable", code: "unavailable", message: "no upstream" }),
  }, async ({ container }) => {
    assert.match(container.textContent, /National map unavailable: boundary request 503/);
  });
});
