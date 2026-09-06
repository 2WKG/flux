// The component's whole claim is that a failure renders as an explicit, named,
// recoverable surface. These tests server-render the real TSX with
// react-dom/server (no browser, no new dependency) and assert the markup, so
// blanking the component -- or dropping Retry, the retained context, or the
// frozen status token -- fails here instead of passing silently.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const componentPath = path.join(webRoot, "src/failure-states/FailureState.tsx");
const typesPath = path.join(webRoot, "src/failure-states/types.ts");
const labelsPath = path.join(webRoot, "src/labels.ts");

/** Bundle a TSX entry for node and import it, so the server render exercises the real source. */
async function serverRender(source) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "flux-351-ssr-"));
  const entry = path.join(dir, "entry.tsx");
  const outfile = path.join(dir, "entry.mjs");
  await writeFile(entry, source, "utf8");
  await build({
    entryPoints: [entry],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    absWorkingDir: webRoot,
    nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"),
    loader: { ".css": "empty" },
    // react-dom/server is CJS and dynamically requires node builtins; give the
    // ESM output a real `require` so those resolve instead of throwing.
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
    logLevel: "silent",
  });
  const module = await import(pathToFileURL(outfile).href);
  await rm(dir, { recursive: true, force: true });
  return module;
}

const RENDER_ENTRY = `
import { renderToStaticMarkup } from "react-dom/server";
import { FailureState } from ${JSON.stringify(componentPath)};
import { FAILURE_STATUS_BY_KIND } from ${JSON.stringify(typesPath)};
import { ASSET_STATUS_TOKENS } from ${JSON.stringify(labelsPath)};
export const frozenTokens = ASSET_STATUS_TOKENS;

export const kinds = Object.keys(FAILURE_STATUS_BY_KIND);
export const statusByKind = FAILURE_STATUS_BY_KIND;
export function render(state, { retry = true, reset = true } = {}) {
  return renderToStaticMarkup(
    <FailureState
      state={{ ...state, retainedContext: state.retainedContext === undefined ? undefined : <p>{state.retainedContext}</p> }}
      onRetry={retry ? () => {} : undefined}
      onReset={reset ? () => {} : undefined}
    />,
  );
}
`;

const rendered = await serverRender(RENDER_ENTRY);
const { kinds, statusByKind, render, frozenTokens } = rendered;

// The frozen Gate-0 UI status set, read from its single definition
// (src/labels.ts) rather than restated, so a drift there fails here too.
const FROZEN_UI_STATUS = new Set(frozenTokens);
assert.equal(FROZEN_UI_STATUS.size, 6, "the Gate-0 UI status set is frozen at six tokens");
assert.ok(FROZEN_UI_STATUS.has("request_failed"));

const RETRYABLE = new Set([
  "unavailable",
  "malformed",
  "version_mismatch",
  "network_failure",
  "cancelled",
  "timeout",
  "oversized",
  "failed",
]);

test("every kind renders a non-empty, named, correctly-roled surface", () => {
  assert.ok(kinds.length >= 9, `expected the full kind set, got ${kinds.length}`);
  for (const kind of kinds) {
    const html = render({ kind });
    assert.match(html, /^<section /, `${kind} must render a section, not nothing`);
    assert.match(
      html,
      new RegExp(`data-request-state="${kind}"`),
      `${kind} must name itself in the markup`,
    );
    const heading = html.match(/<h2>([^<]*)<\/h2>/);
    assert.ok(heading && heading[1].trim().length > 0, `${kind} must render a non-empty heading`);
    const body = html.match(/<p>([^<]*)<\/p>/);
    assert.ok(body && body[1].trim().length > 0, `${kind} must render a non-empty message`);
    const expectedRole = RETRYABLE.has(kind) ? "alert" : "status";
    assert.match(html, new RegExp(`role="${expectedRole}"`), `${kind} must use role=${expectedRole}`);
  }
});

test("the emitted machine token stays inside the frozen Gate-0 status set", () => {
  let sawRequestFailed = false;
  for (const kind of kinds) {
    const html = render({ kind });
    const emitted = html.match(/data-request-status="([^"]*)"/);
    const expected = statusByKind[kind];
    if (expected === null) {
      assert.equal(emitted, null, `${kind} asserts no request status, so none may be rendered`);
      continue;
    }
    assert.ok(emitted, `${kind} must render its frozen status token`);
    assert.ok(
      FROZEN_UI_STATUS.has(emitted[1]),
      `${kind} emitted "${emitted[1]}", which is not in the frozen Gate-0 UI status set`,
    );
    assert.equal(emitted[1], expected);
    sawRequestFailed ||= emitted[1] === "request_failed";
  }
  assert.ok(sawRequestFailed, "a request failure must emit the frozen token request_failed");
});

test("the frozen token is emitted alongside, not instead of, the finer cause", () => {
  const html = render({ kind: "version_mismatch" });
  assert.match(html, /data-request-status="request_failed"/);
  assert.match(html, /data-request-state="version_mismatch"/);
  assert.match(html, /Version mismatch/);
});

test("a supplied source message and retained context are both rendered", () => {
  const html = render({
    kind: "network_failure",
    message: "Offline. No source result was created.",
    retainedContext: "Retained scene: Minnesota overview",
  });
  assert.match(html, /Offline\. No source result was created\./);
  assert.match(html, /aria-label="Retained context"/);
  assert.match(html, /Retained scene: Minnesota overview/);
  // Absent context must not be invented.
  assert.doesNotMatch(render({ kind: "network_failure" }), /aria-label="Retained context"/);
});

test("Retry appears for exactly the recoverable kinds, and only when a handler exists", () => {
  for (const kind of kinds) {
    const html = render({ kind });
    const hasRetry = html.includes(">Retry</button>");
    assert.equal(hasRetry, RETRYABLE.has(kind), `${kind}: Retry button presence is wrong`);
  }
  assert.ok(!render({ kind: "failed" }, { retry: false }).includes(">Retry</button>"));
  assert.ok(render({ kind: "failed" }).includes(">Reset view</button>"));
  assert.ok(!render({ kind: "loading" }).includes(">Reset view</button>"));
});

test("the retry-after delay is stated only where the source supplied one", () => {
  assert.match(
    render({ kind: "unavailable", retryAfterSeconds: 30 }),
    /Retry after 30 seconds/,
  );
  assert.doesNotMatch(render({ kind: "unavailable" }), /Retry after/);
  // A delay on a kind that has no retry-after contract must not be narrated.
  assert.doesNotMatch(render({ kind: "cancelled", retryAfterSeconds: 30 }), /Retry after/);
});

test("an unrecognised producer code is preserved verbatim in the markup", () => {
  const html = render({ kind: "failed", code: "quota_exhausted" });
  assert.match(html, /data-request-code="quota_exhausted"/);
  assert.match(html, /data-request-status="request_failed"/);
});
