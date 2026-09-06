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
      import { CausalSection } from "./explainer/causal";
      import { JepaSection } from "./explainer/jepa";
      import { GnnSection } from "./explainer/gnn";
      import { EMPTY_SCENE_CONTEXT } from "./chat/ask-contract";
      import { TERMINAL_ERROR_CODES } from "./ask/run-state/types";
      import { App } from "./pages/MainPage";
      import { ExplainerPage } from "./pages/ExplainerPage";
      import { GridInventoryPanel } from "./renderer/GridInventoryPanel";
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
      export const renderMainPage = () => renderToStaticMarkup(createElement(App));
      export const renderExplainerPage = () => renderToStaticMarkup(createElement(ExplainerPage));
      const noop = () => {};
      export const renderInventory = (load) => renderToStaticMarkup(createElement(GridInventoryPanel, {
        load, state: "mn", layers: ["line"], query: "", selected: null,
        onStateChange: noop, onLayersChange: noop, onQueryChange: noop, onSelect: noop, onRetry: noop,
      }));
      export const renderCausalSection = () => renderToStaticMarkup(createElement(CausalSection));
      export const renderJepaSection = () => renderToStaticMarkup(createElement(JepaSection));
      export const renderGnnSection = () => renderToStaticMarkup(createElement(GnnSection));
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

test("main and explainer surfaces retain their declared status boundaries", () => {
  const main = surface.renderMainPage();
  const explainer = surface.renderExplainerPage();

  // The Texas topology screen is synthetic. Its machine token remains one of
  // the six IA values and its nav summary renders the owner's display copy.
  const token = main.match(/<main data-source-status="([a-z_]+)"/)?.[1];
  assert.ok(token, "the main page no longer publishes a derived source status");
  assert.ok(ASSET_STATUS_TOKENS.includes(token), `"${token}" is not one of the six IA status tokens`);
  assert.equal(token, "synthetic");

  // The nav source summary leads with the same label.
  const live = main.match(/<div class="live">([\s\S]*?)<\/div>/);
  assert.ok(live, "the nav no longer renders a source summary");
  assert.equal(
    textOf(live[1]),
    `${STATUS_COPY[token]} ACTIVSg2000 static topology · model API required`,
  );

  // And the prohibited browser-invented status word never reaches the screen.
  assert.doesNotMatch(main, new RegExp(PROHIBITED_STATUS_WORD, "i"));

  assert.match(main, /Texas model topology unavailable/);
  assert.match(main, /Loading the synthetic Texas model\./);

  // The explainer makes no Texas-model result claim. It exposes its page-level
  // unavailable status while its mounted teaching sections own their statuses.
  assert.match(explainer, /<main data-source-status="unavailable">/);
  assert.match(explainer, /data-source-status="synthetic"/);
  assert.match(explainer, /data-source-status="hypothetical"/);
  assert.match(explainer, /data-source-status="unavailable"/);

  for (const rendered of [main, explainer]) {
    for (const rival of RIVAL_SPELLINGS) assert.doesNotMatch(rendered, rival);
  }
});

test("the inventory component distinguishes loading, partial, unavailable, and failed reads", () => {
  // These are the component's real `gridLoad` branches; the Texas topology
  // page does not claim this separate physical-inventory surface is mounted.
  const loading = surface.renderInventory({ kind: "loading" });
  assert.match(loading, /Requesting the source-backed inventory release\./);

  const page = {
    api_version: "v1", state: "mn", artifact_version: "1.0.0", artifact_id: "flux:mn-physical:v1",
    release_sha256: "sha-256", layer: "line", inventory_mode: "physical_observed", electrical_model_mode: "none",
    items: [], page: { limit: 100, cursor: null, next_cursor: "next-1", total: 250 },
    coverage: [{
      assetClass: "generation", status: "partial", scopeId: "eia-860", scope: "EIA-860 2024",
      reason: "Retired-unit coordinates are absent.", observed: 1200, denominator: 1500, unknown: 44, unavailable: 256,
    }],
  };
  const partial = surface.renderInventory({ kind: "loaded", pages: [page], truncated: true, nextCursor: "next-1" });
  assert.match(partial, /generation · partial/);
  assert.match(partial, /Observed 1200 of 1500; unknown 44; unavailable 256\./);
  assert.match(partial, /The page walk stopped at its cap; more records exist after cursor <code>next-1<\/code>/);

  // `FailureState` hardcodes its own `copy.unavailable`/`copy.request_failed`
  // rather than importing STATUS_COPY, so these two are a bidirectional pin
  // across two owners, not a tautology.
  const unavailable = surface.renderInventory({ kind: "refused", status: "unavailable", code: "artifact_missing", message: "The accepted inventory artifact is unavailable." });
  assert.match(unavailable, new RegExp(STATUS_COPY.unavailable));
  assert.match(unavailable, /artifact_missing/);
  assert.match(unavailable, /The accepted inventory artifact is unavailable\./);

  const failed = surface.renderInventory({ kind: "refused", status: "request_failed", code: "invalid_input", message: "The inventory request was rejected." });
  assert.match(failed, new RegExp(STATUS_COPY.request_failed));
  assert.match(failed, /invalid_input/);
  assert.match(failed, /The inventory request was rejected\./);
  assert.match(failed, /Retry the inventory request/);
});

test("each mounted explainer section renders a canonical truth status and no provenance status", () => {
  const sections = [
    [surface.renderCausalSection(), "synthetic"],
    [surface.renderJepaSection(), "hypothetical"],
    [surface.renderGnnSection(), "unavailable"],
  ];
  for (const [markup, status] of sections) {
    assert.ok(markup.includes(STATUS_COPY[status]), `explainer section did not render ${STATUS_COPY[status]}`);
    assert.doesNotMatch(markup, /source[_ -]?backed/i);
  }
  assert.match(sections[0][0], /data-source-status="synthetic"/);
  assert.match(sections[0][0], /data-request-status="unavailable"/);
  assert.match(sections[1][0], /data-source-status="hypothetical"/);
  assert.match(sections[2][0], /data-source-status="unavailable"/);
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
    // `statusLabelOf`, the one written translation from the provenance axis into
    // the UI vocabulary. It is a translation at a named seam, not a status value.
    ["src/renderer/scene-view.ts", 1],
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

/**
 * The prohibited decorative status word, spelled once here so the guarantee can
 * be stated without seeding the term into the documents under test. Three frozen
 * contracts refuse it: `docs/design/3d-asset-contract.md` ("no decorative or
 * ... state"), `docs/design/texas-demo-narrative-ia.md` ("prohibited
 * browser-invented status ... Do not display or synthesize it"), and
 * `docs/design/minnesota-gate-0-approval.md` ("not approved").
 *
 * `scripts/validate_asset_archetypes.py` enforces that for `data/3d/**` catalogs
 * only. Prose was unguarded: a design document could tell an implementer to
 * render the word and every gate stayed green.
 */
const PROHIBITED_STATUS_WORD = ["illus", "trative"].join("");

/** The documents that define the prohibition, and so must name the word. */
const PROHIBITION_CONTRACTS = new Set([
  "3d-asset-contract.md",
  "minnesota-demo-narrative-ia.md",
  "minnesota-gate-0-approval.md",
  "texas-demo-narrative-ia.md",
]);

async function designDocuments() {
  const root = path.join(repoRoot.pathname, "docs", "design");
  const found = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(file);
      else if ([".md", ".css", ".html"].includes(path.extname(entry.name))) found.push(file);
    }
  };
  await walk(root);
  return found.sort();
}

test("no design document outside the prohibition contracts carries the prohibited status word", async () => {
  const documents = await designDocuments();
  assert.ok(
    documents.some((file) => path.basename(file) === "ui-style-guide.md"),
    "the walk did not reach docs/design/ui-style-guide.md, so it proves nothing",
  );
  for (const name of PROHIBITION_CONTRACTS) {
    const contract = documents.find((file) => path.basename(file) === name);
    assert.ok(contract, `docs/design/${name} is missing; the exemption list is stale`);
    const text = await readFile(contract, "utf8");
    assert.ok(
      text.toLowerCase().includes(PROHIBITED_STATUS_WORD),
      `docs/design/${name} no longer states the prohibition it is exempted for`,
    );
  }

  const offenders = [];
  for (const file of documents) {
    if (PROHIBITION_CONTRACTS.has(path.basename(file))) continue;
    const lines = (await readFile(file, "utf8")).split("\n");
    for (const [index, line] of lines.entries()) {
      if (line.toLowerCase().includes(PROHIBITED_STATUS_WORD)) {
        offenders.push(`${path.relative(repoRoot.pathname, file)}:${index + 1}: ${line.trim()}`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "a design document reintroduced the prohibited status word; the frozen contracts refuse it",
  );
});

/**
 * `docs/design/ui-tokens.css` is a design reference, not a second stylesheet.
 * #252 collapsed the app onto one `:root` in `web/src/styles.css`; a design file
 * that declared bare token names, or that the app imported, would re-open exactly
 * the drift that closed. These pin the three properties that keep it a reference:
 * every name is `--flux-`-prefixed, nothing under `web/` imports it, and the font
 * stacks lead with the ones `docs/design/texas-workspace-prototype.html` ships
 * (the same source `web/src/styles.css` cites for `--font-sans`/`--font-mono`).
 */
const uiTokensPath = () => path.join(repoRoot.pathname, "docs", "design", "ui-tokens.css");

test("the design token file cannot shadow the app's own token vocabulary", async () => {
  const tokens = await readFile(uiTokensPath(), "utf8");
  const declared = [...tokens.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((match) => match[1]);
  assert.ok(declared.length > 20, "ui-tokens.css declared almost nothing; the parse is wrong");
  const unprefixed = [...new Set(declared.filter((name) => !name.startsWith("--flux-")))];
  assert.deepEqual(unprefixed, [], "a design token dropped the --flux- prefix and can now shadow web/src/styles.css");

  // And no browser file pulls the reference in as a stylesheet.
  const importers = [];
  for (const file of await browserSources()) {
    if ((await readFile(file, "utf8")).includes("ui-tokens.css")) {
      importers.push(path.relative(webRoot.pathname, file));
    }
  }
  assert.deepEqual(importers, [], "browser code imported the design token reference; the app has one stylesheet");
});

test("the design token font stacks lead with the ones the shipped prototype uses", async () => {
  const prototype = await readFile(
    path.join(repoRoot.pathname, "docs", "design", "texas-workspace-prototype.html"),
    "utf8",
  );
  const shipped = {
    "--flux-font-ui": prototype.match(/font:\s*14px\/1\.4\s*([^;]+);/)?.[1]?.trim(),
    "--flux-font-data": prototype.match(/font-family:\s*(ui-monospace[^;]*);/)?.[1]?.trim(),
  };
  assert.equal(shipped["--flux-font-ui"], "ui-sans-serif, system-ui, sans-serif");
  assert.equal(shipped["--flux-font-data"], "ui-monospace, monospace");

  const tokens = await readFile(uiTokensPath(), "utf8");
  for (const [name, stack] of Object.entries(shipped)) {
    const declared = tokens.match(new RegExp(`${name}\\s*:\\s*([^;]+);`))?.[1]?.trim();
    assert.ok(declared, `ui-tokens.css no longer declares ${name}`);
    const lead = stack.split(",")[0].trim();
    assert.equal(
      declared.split(",")[0].trim(),
      lead,
      `${name} leads with a family the prototype does not ship; a downloadable face makes metrics machine-dependent`,
    );
    // Every generic the prototype names must still be in the stack, in order.
    const wanted = stack.split(",").map((part) => part.trim());
    const have = declared.split(",").map((part) => part.trim());
    let cursor = -1;
    for (const family of wanted) {
      const at = have.indexOf(family, cursor + 1);
      assert.ok(at > cursor, `${name} dropped or reordered ${family} from the shipped stack`);
      cursor = at;
    }
  }
});
