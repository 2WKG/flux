/**
 * The one rule this surface exists to enforce -- the browser renders the
 * server's signed delta and never computes one -- asserted where it is
 * rendered.
 *
 * `MinnesotaControlRoom.test.mjs` renders to static markup, which cannot reach
 * the comparison: the request is asynchronous, so the section is absent from
 * the first paint. That is why commenting the whole section out, and replacing
 * `delta_signed` with `candidate_value - baseline_value`, both left the suite
 * green. This file mounts the component in a real DOM with React attached,
 * hands it a stub transport, clicks the button, and asserts the DOM that
 * results.
 */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";
import { JSDOM } from "jsdom";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);

// React's scheduler posts through a MessageChannel, whose real node ports keep
// the event loop alive forever and hang the runner after the last test. Same
// shim as `test/chat-dock.test.mjs`, for the same reason.
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
export { MinnesotaControlRoom } from ${JSON.stringify(path.join(webRoot, "src/minnesota/MinnesotaControlRoom.tsx"))};
`;

let probePromise;
function probe() {
  probePromise ??= (async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "flux-mn-comparison-probe-"));
    const entry = path.join(dir, "probe.tsx");
    const outfile = path.join(dir, "probe.mjs");
    await writeFile(entry, PROBE, "utf8");
    await build({
      entryPoints: [entry],
      outfile,
      bundle: true,
      format: "esm",
      platform: "browser",
      target: "es2020",
      absWorkingDir: webRoot,
      tsconfig: path.join(webRoot, "tsconfig.json"),
      nodePaths: [path.join(webRoot, "node_modules")],
      loader: { ".css": "empty" },
      define: { "process.env.NODE_ENV": '"development"' },
      logLevel: "silent",
    });
    return outfile;
  })();
  return probePromise;
}

/** The persisted response `copilot/routes/mn_comparisons.py` returns, field for field. */
function readyBody(overrides = {}) {
  return {
    status: "ready",
    comparison_id: "artifact:mn:baseline:v1..artifact:mn:candidate:v1",
    baseline: { context_id: "mn:baseline:v1", label: "Baseline" },
    candidate: { context_id: "mn:candidate:v1", label: "Candidate" },
    metrics: [{
      metric_id: "customers_at_risk",
      label: "customers_at_risk",
      baseline_value: 12,
      candidate_value: 9,
      delta_signed: -3,
      unit: "customers",
      provenance: [{ source_id: "record", artifact_id: "artifact:mn:baseline:v1", version: "v1", kind: "persisted_aggregate_model" }],
    }],
    highlight_ids: ["scene:mn:baseline:v1", "scene:mn:candidate:v1"],
    limitations: ["aggregate only"],
    ...overrides,
  };
}

function stubTransport(body, status = 200) {
  return async () => new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Mount the control room in a real DOM, run `body`, then tear everything down. */
async function mounted(props, body) {
  const outfile = await probe();
  const dom = new JSDOM("<!doctype html><div id='root'></div>", { url: "http://localhost/minnesota" });
  const globals = {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  const previous = {};
  for (const [key, value] of Object.entries(globals)) {
    previous[key] = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  const api = await import(pathToFileURL(outfile).href);
  const container = dom.window.document.getElementById("root");
  const root = api.createRoot(container);
  try {
    await api.act(async () => {
      root.render(api.createElement(api.MinnesotaControlRoom, {
        search: "",
        location: { pathname: "/minnesota", hash: "" },
        ...props,
      }));
    });
    const button = [...container.querySelectorAll("button")].find((element) => /Compare baseline/.test(element.textContent));
    assert.ok(button, "the Compare baseline button is not rendered");
    await api.act(async () => {
      button.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    // Let the transport promise and React's state update settle.
    await api.act(async () => { await new Promise((resolve) => setImmediate(resolve)); });
    return await body({ container, dom });
  } finally {
    await api.act(() => { root.unmount(); });
    for (const key of Object.keys(globals)) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    dom.window.close();
  }
}

const comparisonSection = (container) => container.querySelector('section[aria-label="Aggregate comparison"]');

test("the comparison section renders, and renders the server's signed delta", async () => {
  await mounted({ comparisonTransport: stubTransport(readyBody()) }, ({ container }) => {
    const section = comparisonSection(container);
    assert.ok(section, "the comparison section never rendered");
    assert.equal(section.getAttribute("data-comparison-state"), "ready");
    const text = section.textContent.replace(/\s+/g, " ");
    assert.match(text, /Server-signed delta: -3 customers/, `the signed delta is not rendered: ${text}`);
    assert.match(text, /artifact:mn:baseline:v1\.\.artifact:mn:candidate:v1/);
    assert.match(text, /scene:mn:baseline:v1/);
    assert.match(text, /aggregate only/);
    // Provenance is rendered in full, so a dropped field is visible.
    assert.match(text, /persisted_aggregate_model: record \/ artifact:mn:baseline:v1 \/ v1/);
    assert.doesNotMatch(text, /undefined/);
  });
});

test("the delta on screen is the server's field, not candidate minus baseline", async () => {
  // The decisive case: a server whose signed delta disagrees with the
  // arithmetic. A browser that recomputes renders -3; this one must render the
  // 41 the server signed. Both numbers are present in the fixture, so the
  // assertion can only be satisfied by reading `delta_signed`.
  const body = readyBody();
  const disagreeing = {
    ...body,
    metrics: [{ ...body.metrics[0], delta_signed: 41 }],
  };
  await mounted({ comparisonTransport: stubTransport(disagreeing) }, ({ container }) => {
    const text = comparisonSection(container).textContent.replace(/\s+/g, " ");
    assert.match(text, /Server-signed delta: 41 customers/, `the browser recomputed the delta: ${text}`);
    assert.doesNotMatch(text, /Server-signed delta: -3/);
  });
});

test("a ready body missing a provenance artifact id is refused, not rendered as undefined", async () => {
  const body = readyBody();
  const withoutArtifact = {
    ...body,
    metrics: [{
      ...body.metrics[0],
      provenance: [{ source_id: "record", version: "v1", kind: "persisted_aggregate_model" }],
    }],
  };
  await mounted({ comparisonTransport: stubTransport(withoutArtifact) }, ({ container }) => {
    const section = comparisonSection(container);
    assert.ok(section, "the comparison section never rendered");
    assert.notEqual(section.getAttribute("data-comparison-state"), "ready", "an incomplete provenance row was accepted");
    const text = section.textContent.replace(/\s+/g, " ");
    assert.doesNotMatch(text, /undefined/, "a missing artifact id reached the page");
    assert.doesNotMatch(text, /Server-signed delta/);
  });
});

test("a 503 unavailable envelope reaches the shared failure surface, not the ready view", async () => {
  const envelope = {
    status: "unavailable",
    data: null,
    error: {
      code: "unavailable",
      message: "The Minnesota comparison artifact is unavailable.",
      retryable: true,
      details: { artifact: "mn_comparison", reason: "no_qualified_result" },
    },
    meta: { api_version: "v1" },
  };
  await mounted({ comparisonTransport: stubTransport(envelope, 503) }, ({ container }) => {
    const section = comparisonSection(container);
    assert.ok(section, "the comparison section never rendered");
    assert.notEqual(section.getAttribute("data-comparison-state"), "ready");
    assert.ok(section.querySelector("[data-request-state]"), "the failure state is not rendered");
    assert.doesNotMatch(section.textContent, /Server-signed delta/);
  });
});
