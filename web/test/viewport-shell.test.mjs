// Behavioural test for the viewport-first shell.
//
// The previous version of this file asserted regexes over the raw text of
// main.tsx and styles.css. That could not fail for any layout regression:
// gutting the 1180px block, moving the workspace grid into a selector that
// matches no element, and disabling the chat toggle all left it green. So
// nothing here reads source text.
//
// Structure and labels are asserted on rendered markup, using the same seam as
// src/inspector/browser-harness.test.mjs and src/ask/run-state/reducer.test.mjs:
// compile the TSX with esbuild and import it, then render with react-dom/server.
// CSS is asserted on a parsed selector -> declaration map, so an assertion
// cannot be satisfied by a comment or by text that lives in another rule.
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { readBuiltScripts } from "./built-assets.mjs";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-viewport-shell-render.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { App, ChatDockView, chatReducer } from "./src/pages/MainPage";
      export { deriveSourceTruth, STATUS_COPY } from "./src/source-truth";
      export { ASSET_STATUS_TOKENS } from "./src/labels";
      export { SYNTHETIC_TOPOLOGY_LABEL } from "./src/scene/minnesota-adapter";
      export { ChatDockView, chatReducer };
      export const renderApp = () => renderToStaticMarkup(createElement(App));
      export const renderDock = (props) => renderToStaticMarkup(createElement(ChatDockView, props));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "viewport-shell-render-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  // The shell imports its stylesheet for the browser build; this entry asserts
  // the stylesheet separately, by parsing it.
  loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const shell = await import(compiled.href);

const markup = shell.renderApp();
/** Rendered text only: tag names are not the claim under test. */
const text = markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

const styles = await readFile(new URL("src/styles.css", webRoot), "utf8");
const bundle = JSON.parse(await readFile(new URL("../data/demo/bundle.json", webRoot), "utf8"));

/**
 * Parse the stylesheet into `{ context, selector, declarations }` records.
 * `context` is "" for a top-level rule and the at-rule prelude (for example
 * `@media (max-width: 1180px)`) for a nested one. Comments are stripped first,
 * so a declaration that has been commented out is simply not present.
 */
function parseRules(css) {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  const walk = (body, context) => {
    let index = 0;
    while (index < body.length) {
      const open = body.indexOf("{", index);
      if (open === -1) break;
      let depth = 1;
      let close = open + 1;
      while (close < body.length && depth > 0) {
        if (body[close] === "{") depth += 1;
        else if (body[close] === "}") depth -= 1;
        close += 1;
      }
      const prelude = body.slice(index, open).trim();
      const inner = body.slice(open + 1, close - 1);
      if (prelude.startsWith("@") && inner.includes("{")) walk(inner, prelude.replace(/\s+/g, " "));
      else if (!prelude.startsWith("@")) {
        const declarations = inner
          .split(";")
          .map((entry) => entry.trim().replace(/\s+/g, " "))
          .filter(Boolean);
        for (const selector of prelude.split(",")) {
          rules.push({ context, selector: selector.trim().replace(/\s+/g, " "), declarations });
        }
      }
      index = close;
    }
  };
  walk(source, "");
  return rules;
}

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const rules = parseRules(styles);

/** Every declaration the given selector carries in the given at-rule context. */
function declarations(selector, context = "") {
  return rules
    .filter((rule) => rule.context === context && rule.selector === selector)
    .flatMap((rule) => rule.declarations);
}

const declared = (selector, declaration, context = "") =>
  declarations(selector, context).some((entry) => entry.replace(/:\s*/, ": ") === declaration);

test("the workspace renders as a grid whose scene column is the primary surface", () => {
  assert.match(markup, /<section class="workspace" aria-label="Viewport-first scenario workspace">/);
  const workspace = markup.slice(markup.indexOf('class="workspace"'));
  assert.match(workspace, /<article class="map scene-viewport">/);
  assert.match(workspace, /<aside class="inspector" aria-label="Scenario inspector">/);

  // The layout itself, read off the cascade rather than off the file's text.
  assert.ok(declared(".workspace", "display: grid"), ".workspace must be a grid");
  assert.ok(
    declared(".workspace", "grid-template-columns: minmax(0, 1fr) minmax(280px, 360px)"),
    ".workspace must give the scene the flexible column and the inspector a bounded one",
  );
  assert.ok(
    declared(".scene-viewport", "min-height: clamp(500px, 64vh, 700px)"),
    ".scene-viewport must hold a viewport-first height",
  );
});

test("the compact and stacked breakpoints carry real declarations, not just a prelude", () => {
  const compact = "@media (max-width: 1180px)";
  assert.ok(rules.some((rule) => rule.context === compact), "the 1180px tier must contain rules");
  assert.ok(
    declared(".workspace", "grid-template-columns: minmax(0, 1fr) minmax(280px, 320px)", compact),
    "the compact tier must narrow the inspector column",
  );
  assert.ok(declarations(".timeline", compact).length > 0, "the compact tier must restate the timeline strip");
  assert.ok(declarations("main", compact).length > 0, "the compact tier must tighten the page padding");

  const stacked = "@media (max-width: 980px)";
  assert.ok(declared(".workspace", "grid-template-columns: 1fr", stacked), "the 980px tier must stack the workspace");
  assert.ok(declared(".scene-viewport", "min-height: auto", stacked), "a stacked scene must release its min-height");
});

test("the timeline strip renders inside the scene and states that playback is not available", () => {
  const scene = markup.slice(markup.indexOf('class="map scene-viewport"'), markup.indexOf('class="inspector"'));
  assert.match(scene, /<section class="timeline" aria-label="Scenario timeline">/);
  assert.match(scene, /class="timeline-track"/);
  assert.match(text, /Bundled output · playback unavailable/);
  assert.ok(declarations(".timeline").length > 0, ".timeline must be styled");
});

test("no class reaches the DOM without a rule that can style it", () => {
  const styled = new Set(rules.flatMap((rule) => [...rule.selector.matchAll(/\.([A-Za-z0-9_-]+)/g)].map((m) => m[1])));
  const rendered = new Set(
    [...markup.matchAll(/class="([^"]*)"/g)].flatMap((match) => match[1].split(/\s+/)).filter(Boolean),
  );
  const dead = [...rendered].filter((name) => !styled.has(name));
  assert.deepEqual(dead, [], `classes rendered with no CSS rule: ${dead.join(", ")}`);
  // The three the previous test file invented are gone by name, too.
  for (const name of ["app-shell", "viewport-shell", "compact-panel"]) {
    assert.ok(!rendered.has(name), `${name} is a dead class`);
    assert.ok(!styled.has(name), `${name} has no markup to style`);
  }
});

test("the chat dock stays in flow and nothing but the overlay covers the page", () => {
  // Regression guard carried over from 1b097ed: as `position: fixed; right; bottom`
  // the dock parked over the inspector column and hid the headline unmet-demand
  // figure while the page was scrolled. Read off the parsed rules, so a rule in a
  // media query cannot smuggle the offsets back in.
  for (const selector of [".chat-dock", ".chat-dock.collapsed", ".chat-dock.expanded"]) {
    const owned = rules.filter((rule) => rule.selector === selector);
    assert.ok(owned.length > 0, `${selector} rule is missing`);
    for (const rule of owned) {
      for (const entry of rule.declarations) {
        const property = entry.split(":")[0].trim();
        assert.ok(
          !["position", "top", "bottom", "left", "right"].includes(property),
          `${selector}${rule.context ? ` in ${rule.context}` : ""} still offsets a floating dock: ${entry}`,
        );
      }
    }
  }
  const fixed = rules
    .filter((rule) => rule.declarations.some((entry) => entry.replace(/:\s*/, ": ") === "position: fixed"))
    .map((rule) => rule.selector);
  assert.deepEqual(fixed, [".overlay"], "only the overlay may cover the page");
});

test("the chat dock starts collapsed and its aria-controls target always exists", () => {
  const collapsed = shell.renderDock({ open: false, onToggle: () => {} });
  assert.match(collapsed, /class="chat-dock collapsed"/);
  assert.match(collapsed, /aria-expanded="false"/);
  assert.match(collapsed, /aria-controls="chat-dock-body"/);
  assert.match(collapsed, /id="chat-dock-body"[^>]*hidden/, "the aria-controls target must exist while collapsed");
  // The App composes the dock in its collapsed state.
  assert.match(markup, /class="chat-dock collapsed"/);
});

test("clicking the collapsed dock expands it to the explicit unavailable state", () => {
  // Drive the real state transition: the reducer the dock is wired to, plus the
  // handler the rendered button carries. No source text is read.
  let open = false;
  const onToggle = () => {
    open = shell.chatReducer(open, "toggle");
  };
  const element = shell.ChatDockView({ open, onToggle });
  const button = findByProp(element, "className", "chat-toggle");
  assert.ok(button, "the collapsed dock must render a toggle button");
  assert.equal(typeof button.props.onClick, "function");
  button.props.onClick();
  assert.equal(open, true, "clicking the toggle must open the dock");

  const expanded = shell.renderDock({ open, onToggle });
  assert.match(expanded, /class="chat-dock expanded"/);
  assert.match(expanded, /aria-expanded="true"/);
  assert.doesNotMatch(expanded, /id="chat-dock-body"[^>]*hidden/);
  const expandedText = expanded.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");
  assert.match(expandedText, /no Copilot endpoint, model result, or Minnesota artifact to query/);
  // "Unavailable" is a reserved truth label; the dock must not borrow it as chrome.
  assert.doesNotMatch(expandedText, /\bUnavailable\b/);

  onToggle();
  assert.equal(open, false, "clicking again must collapse the dock");
});

/** Depth-first search for a rendered element carrying `prop === value`. */
function findByProp(node, prop, value) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findByProp(child, prop, value);
      if (found) return found;
    }
    return null;
  }
  if (node.props?.[prop] === value) return node;
  return findByProp(node.props?.children, prop, value);
}

test("the five-bus screen labels itself synthetic, derived from the bundle's provenance", () => {
  assert.match(text, new RegExp(shell.STATUS_COPY.synthetic));
  assert.match(text, /fixture source/);
  assert.match(text, /no asserted topology/);
  assert.match(text, /not Minnesota data/);
  assert.match(text, /no API required/);

  // The relabelling this screen must never survive.
  for (const forbidden of [/Source supported/i, /source-supported/i, /Minnesota coverage/i, /source_backed/]) {
    assert.doesNotMatch(text, forbidden, `the synthetic fixture must not render ${forbidden}`);
  }
});

test("source truth is derived by explicit rule, and never defaults to a plausible label", () => {
  assert.deepEqual(shell.deriveSourceTruth(bundle.execution.provenance), {
    status: "synthetic",
    sourceKind: "fixture",
    topology: null,
  });
  // The five-bus preview is not the Texas synthetic case and must not claim it.
  assert.doesNotMatch(text, new RegExp(escapeRegExp(shell.SYNTHETIC_TOPOLOGY_LABEL)));

  // An ACTIVSg-derived source is the one topology this repository can assert.
  assert.deepEqual(
    shell.deriveSourceTruth({ sourceId: "ercot_case", sourceRef: "data/raw/activsg2000_current/case.m" }),
    { status: "synthetic", sourceKind: "simulated", topology: shell.SYNTHETIC_TOPOLOGY_LABEL },
  );
  assert.equal(shell.SYNTHETIC_TOPOLOGY_LABEL, "synthetic (ACTIVSg2000)");

  // Anything the provenance does not support is unavailable, not inferred.
  assert.deepEqual(shell.deriveSourceTruth({ sourceId: "some_utility_feed", sourceRef: "s3://somewhere" }), {
    status: "unavailable",
    sourceKind: null,
    topology: null,
  });
});

test("the display vocabulary is exactly the six IA tokens", () => {
  assert.deepEqual(Object.keys(shell.STATUS_COPY).sort(), [...shell.ASSET_STATUS_TOKENS].sort());
  assert.equal(shell.ASSET_STATUS_TOKENS.length, 6);
  assert.ok(!shell.ASSET_STATUS_TOKENS.includes("source_backed"));
});


test("the built bundle actually ships the shell, the dock, and the derived label", async () => {
  // Guards against a shell that only exists in source. `npm run build` runs first
  // in the CI web gate, so dist/ is present here.
  // The entry is split into chunks (2WKG-478); the scenario page ships in one of
  // them, so the shipped artifact is the entry plus every chunk beside it.
  const built = await readBuiltScripts();
  for (const marker of [
    "model-workspace",
    "Full synthetic Texas topology",
    "map scene-viewport",
    "Not available in this offline build",
    "no asserted topology",
    bundle.execution.provenance.artifactId,
  ]) {
    assert.ok(built.includes(marker), `built bundle is missing ${marker}`);
  }
  // The relabelling must not be reachable from the shipped artifact either. The
  // six-token display map legitimately ships, so the check is on the claim this
  // screen would have to make: coverage it does not have.
  assert.ok(!/Minnesota coverage/i.test(built), "the built bundle must not claim Minnesota coverage");
  // `STATUS_COPY` now carries the IA's hyphenated spelling ("Source-supported"),
  // so its own entry is the one legitimate occurrence; it is removed by name and
  // any remaining occurrence is a screen making the claim.
  const displayMapEntry = /source_supported:\s*"Source-supported"/g;
  assert.match(built, displayMapEntry, "the six-token display map should still ship");
  const outsideDisplayMap = built.replace(displayMapEntry, "");
  assert.ok(
    !/source-supported/i.test(outsideDisplayMap),
    "the built bundle must not claim source support outside the display map",
  );
});
