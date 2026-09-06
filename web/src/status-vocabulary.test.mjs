/**
 * The status vocabulary has one owner, and so do its display strings.
 *
 * `src/labels.ts` owns the six IA status tokens and `src/source-truth.ts`
 * `STATUS_COPY` owns the six display strings (the IA's "UI label" column,
 * `docs/design/minnesota-demo-narrative-ia.md`). `src/layers/legend.test.mjs`
 * already pins those strings against the IA table by label. This file pins the
 * other half: that no surface re-spells them, that the rendered text is the
 * owner's text, and that `source_backed` stays on the artifact-provenance axis
 * (`docs/design/minnesota-gate-0-approval.md:51-66`) instead of leaking into the
 * UI status vocabulary.
 *
 * Nothing here reads a line number, and nothing asserts over source text where a
 * rendered string or a compiled bundle can be asserted instead.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { stripComments } from "./../scripts/check-browser-boundary.mjs";

const here = new URL(".", import.meta.url);
const webRoot = new URL("../", import.meta.url);
const repoRoot = new URL("../../", import.meta.url);

const compiled = new URL("../node_modules/.cache/flux-status-vocabulary.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ASSET_STATUS_TOKENS } from "./labels";
      import { STATUS_COPY } from "./source-truth";
      import { Inspector } from "./inspector/Inspector";
      import { RunTrace } from "./ask/run-state/RunTrace";
      import { createRunState } from "./ask/run-state/reducer";
      import { ChatDock } from "./chat/ChatDock";
      import { EMPTY_SCENE_CONTEXT } from "./chat/ask-contract";
      import { TERMINAL_ERROR_CODES } from "./ask/run-state/types";
      export { ASSET_STATUS_TOKENS, STATUS_COPY, TERMINAL_ERROR_CODES };
      export const renderInspector = (status) =>
        renderToStaticMarkup(createElement(Inspector, { asset: { status, artifactLabel: status, name: "Probe", kind: "Facility" } }));
      export const renderRunTrace = (status) =>
        renderToStaticMarkup(createElement(RunTrace, { state: createRunState({ attemptId: "a1", contextRevision: "r1" }, status) }));
      export const renderChatDock = (status) =>
        renderToStaticMarkup(createElement(ChatDock, {
          contextRevision: "r1", context: EMPTY_SCENE_CONTEXT, attemptId: "a1",
          sourceLabel: "Fixture demo", sourceStatus: status, status: "idle",
        }));
    `,
    resolveDir: here.pathname,
    loader: "tsx",
    sourcefile: "status-vocabulary-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  loader: { ".css": "empty" },
  outfile: compiled.pathname,
});
const surface = await import(compiled.href);
const { ASSET_STATUS_TOKENS, STATUS_COPY, TERMINAL_ERROR_CODES } = surface;

/** Rendered text only: markup and attributes are not the claim under test. */
const textOf = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

/** Every spelling of the six labels that is NOT the owner's. */
const RIVAL_SPELLINGS = [/Source supported/, /Source screened/, /Request-failed/, /Source_supported/];

async function browserSources() {
  const found = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!["node_modules", "dist"].includes(entry.name)) await walk(file);
      } else if ([".ts", ".tsx"].includes(path.extname(entry.name))) {
        found.push(file);
      }
    }
  };
  await walk(path.join(webRoot.pathname, "src"));
  return found.sort();
}

/** A display-label map: at least three of the six tokens bound to a status label string. */
const LABEL_VALUE = /^(?:Source[ -]supported|Source[ -]screened|Hypothetical|Synthetic|Unavailable|Request[ -]failed)$/i;

test("the six display strings are declared in one place, and every declaration is the owner's", async () => {
  const owners = new Map();
  for (const file of await browserSources()) {
    const source = stripComments(await readFile(file, "utf8"));
    const bound = new Map();
    for (const match of source.matchAll(/\b(source_supported|source_screened|hypothetical|synthetic|unavailable|request_failed)\s*:\s*"([^"]*)"/g)) {
      if (LABEL_VALUE.test(match[2])) bound.set(match[1], match[2]);
    }
    if (bound.size >= 3) owners.set(path.relative(webRoot.pathname, file), bound);
  }

  // `src/ask/results/ResultCards.tsx` still carries a copy that agrees with the
  // owner byte for byte. It belongs to another unit's file set, so it is pinned
  // here rather than deleted here: it may not drift, and no third file may join.
  assert.deepEqual(
    [...owners.keys()],
    ["src/ask/results/ResultCards.tsx", "src/source-truth.ts"],
    "a surface re-spelled the six display strings instead of importing STATUS_COPY",
  );
  for (const [file, bound] of owners) {
    for (const [token, value] of bound) {
      assert.equal(value, STATUS_COPY[token], `${file} spells ${token} differently from its owner`);
    }
  }
});

test("the inspector renders the owner's copy, and never the unhyphenated spelling", () => {
  for (const status of ASSET_STATUS_TOKENS) {
    const rendered = textOf(surface.renderInspector(status));
    assert.ok(rendered.includes(`Status ${STATUS_COPY[status]}`), `the inspector did not render ${STATUS_COPY[status]}`);
    assert.ok(rendered.includes(`Artifact ${STATUS_COPY[status]}`));
    for (const rival of RIVAL_SPELLINGS) assert.doesNotMatch(rendered, rival);
  }
});

test("every status string the run trace renders is a value of STATUS_COPY", () => {
  const owned = new Set(Object.values(STATUS_COPY));
  for (const status of ASSET_STATUS_TOKENS) {
    const rendered = textOf(surface.renderRunTrace(status));
    const shown = rendered.match(/Source status: ([^.]*?)(?= Cancel run|$)/);
    assert.ok(shown, `the run trace rendered no source status for ${status}`);
    assert.ok(owned.has(shown[1].trim()), `"${shown[1].trim()}" is not a STATUS_COPY value`);
    assert.equal(shown[1].trim(), STATUS_COPY[status]);
    for (const rival of RIVAL_SPELLINGS) assert.doesNotMatch(rendered, rival);
  }
});

test("the chat dock renders the owner's copy", () => {
  for (const status of ASSET_STATUS_TOKENS) {
    const rendered = textOf(surface.renderChatDock(status));
    assert.ok(rendered.includes(`Truth: ${STATUS_COPY[status]}`), `the dock did not render ${STATUS_COPY[status]}`);
    for (const rival of RIVAL_SPELLINGS) assert.doesNotMatch(rendered, rival);
  }
});

test("`source_backed` is the artifact-provenance axis and never a status", async () => {
  assert.ok(!ASSET_STATUS_TOKENS.includes("source_backed"));
  assert.ok(!Object.keys(STATUS_COPY).includes("source_backed"));
  assert.ok(!Object.values(STATUS_COPY).some((value) => value.toLowerCase().includes("backed")));

  // Where the token may legitimately appear in browser code, comments removed.
  const allowed = new Map([
    // The frozen three-value provenance axis itself (`ArtifactTruthLabel`).
    ["src/ask/results/types.ts", 2],
    // The negative fixture that proves an unrecognised status is refused, not tinted.
    ["src/layers/LayerControlsHarness.tsx", 1],
  ]);
  const seen = new Map();
  for (const file of await browserSources()) {
    const occurrences = [...stripComments(await readFile(file, "utf8")).matchAll(/source_backed/g)].length;
    if (occurrences > 0) seen.set(path.relative(webRoot.pathname, file), occurrences);
  }
  assert.deepEqual(Object.fromEntries(seen), Object.fromEntries(allowed), "`source_backed` reached a new site in browser code");
});

test("the shipped component bundle carries the owner's strings and no provenance token", async () => {
  const bundle = await build({
    stdin: {
      contents: `
        export * from "./ask/results/index";
        export { Inspector } from "./inspector/Inspector";
        export { RunTrace } from "./ask/run-state/RunTrace";
        export { ChatDock } from "./chat/ChatDock";
      `,
      resolveDir: here.pathname,
      loader: "tsx",
      sourcefile: "status-vocabulary-bundle.tsx",
    },
    bundle: true, format: "esm", platform: "browser", jsx: "automatic",
    packages: "external", loader: { ".css": "empty" }, write: false,
  });
  assert.equal(bundle.errors.length, 0, JSON.stringify(bundle.errors));
  const code = bundle.outputFiles.filter((file) => !file.path.endsWith(".css")).map((file) => file.text).join("\n");
  assert.ok(code.length > 1000, "the probe bundle did not build");

  // The artifact-provenance axis is a type, so it is erased: the token must not
  // survive as a runtime string on any of these surfaces.
  assert.doesNotMatch(code, /source_backed/);
  // And the display strings that do survive are only the owner's spellings.
  for (const rival of RIVAL_SPELLINGS) assert.doesNotMatch(code, rival);
  for (const value of Object.values(STATUS_COPY)) assert.ok(code.includes(value), `the bundle lost the display string ${value}`);
});

test("the SSE terminal-error codes are the server's list, stated once in the same order", async () => {
  const sse = await readFile(new URL("copilot/sse.py", repoRoot), "utf8");
  const block = sse.match(/(?<![A-Z_])_ERROR_CODES = frozenset\(\s*\{([^}]*)\}/);
  assert.ok(block, "copilot/sse.py no longer declares _ERROR_CODES as a frozenset literal");
  const server = [...block[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
  assert.deepEqual([...TERMINAL_ERROR_CODES], server, "the browser's terminal-error set drifted from copilot/sse.py");

  // Any hand-written restatement in browser code must be that same ordered list.
  for (const file of await browserSources()) {
    const source = stripComments(await readFile(file, "utf8"));
    for (const union of source.matchAll(/=\s*((?:\s*\|?\s*"[a-z_]+"\s*)+);/g)) {
      const members = [...union[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
      if (!members.includes("upstream_error")) continue;
      assert.deepEqual(members, server, `${path.relative(webRoot.pathname, file)} restates the terminal-error set differently`);
    }
  }
});
