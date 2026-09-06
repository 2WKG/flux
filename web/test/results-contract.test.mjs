// Behavioural contract tests for the Ask result cards.
//
// These render the real component with `react-dom/server` instead of pattern-matching its
// source, so a gate that stops working goes red. The .tsx is compiled on the fly with the
// esbuild that already builds the app bundle, and written under node_modules/ so that the
// compiled module still resolves `react` from web/node_modules.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
const resultsRoot = new URL("../src/ask/results/", import.meta.url);
const scratch = path.join(webRoot, "node_modules", ".cache", "results-contract");

async function loadResultCards() {
  await mkdir(scratch, { recursive: true });
  const outfile = path.join(scratch, "result-cards.mjs");
  await build({
    entryPoints: [path.join(webRoot, "src", "ask", "results", "index.ts")],
    bundle: true,
    format: "esm",
    platform: "neutral",
    target: "es2020",
    jsx: "automatic",
    loader: { ".css": "empty" },
    external: ["react", "react/jsx-runtime", "react-dom"],
    absWorkingDir: webRoot,
    outfile,
  });
  return import(`${pathToFileURL(outfile).href}?t=${Date.now()}`);
}

const { ResultCards, REVERSIBLE_ACTION_KINDS, ACTION_KINDS, isSupportedResultAction } = await loadResultCards();

after(() => rm(scratch, { recursive: true, force: true }));

function citation(overrides = {}) {
  return {
    doc: "10cfr100", title: "10 CFR Part 100", page: 4, chunk_id: "p4",
    text: "Returned citation excerpt.", version: "retrieval-v1",
    content_kind: "source", locator: "§ 100.11", source: "10 CFR Part 100", score: 0.82,
    citation_id: "cite_01test", ...overrides,
  };
}

function result(overrides = {}) {
  return {
    id: "r1", answer: "", scope: "Test", status: { availability: "source_supported" },
    citations: [], provenance: [], limitations: [], ...overrides,
  };
}

/** Render the real component tree to static markup. */
function render(results, handlers = {}) {
  return renderToStaticMarkup(createElement(ResultCards, { results, ...handlers }));
}

const handlers = { onAction: () => {}, onUndoAction: () => {} };

test("a done frame with verified:false renders the unverified banner and never the verified one", () => {
  const unverified = render([result({ status: { availability: "source_supported", verified: false } })]);
  assert.match(unverified, /Verification reported unresolved evidence/);
  assert.match(unverified, /ask-result__status is-unverified/);
  assert.doesNotMatch(unverified, /Verified against returned tools and citations/);

  // The probe must be able to tell the two states apart, so pin the opposite frame too.
  const verified = render([result({ status: { availability: "source_supported", verified: true } })]);
  assert.match(verified, /Verified against returned tools and citations/);
  assert.doesNotMatch(verified, /Verification reported unresolved evidence/);

  // And an absent flag must claim neither.
  const unknown = render([result({ status: { availability: "source_supported" } })]);
  assert.match(unknown, /Verification status was not supplied/);
});

test("an action whose geometry is unavailable renders no button at all", () => {
  const unavailableGeometry = {
    kind: "focus", id: "a1", revision: "v1", label: "Focus artifact",
    source: "server", geometry: "unavailable",
  };
  assert.equal(isSupportedResultAction(unavailableGeometry), false);
  const markup = render([result({ status: { availability: "source_supported" }, action: unavailableGeometry })], handlers);
  assert.doesNotMatch(markup, /<button/);
  assert.doesNotMatch(markup, /Focus artifact/);
  assert.match(markup, /Scene action unavailable/);

  // A supported action does render a button: without this the assertion above would pass
  // even if the component never rendered a button for anything.
  const supported = { ...unavailableGeometry, geometry: "synthetic" };
  assert.equal(isSupportedResultAction(supported), true);
  const supportedMarkup = render([result({ status: { availability: "source_supported" }, action: supported })], handlers);
  assert.match(supportedMarkup, /<button type="button">Focus artifact \(synthetic geometry\)<\/button>/);
});

test("citation tokens in the answer are linked to the citation entry at the call site", () => {
  const markup = render([result({
    answer: "The returned source supports the stated boundary [10cfr100 p.4].",
    citations: [citation()],
  })]);
  assert.match(markup, /<a href="#citation-10cfr100-4-p4">\[10cfr100 p\.4\]<\/a>/);
  assert.match(markup, /id="citation-10cfr100-4-p4"/);

  // A token with no matching returned citation stays plain prose: the card never invents a link.
  const unmatched = render([result({ answer: "See [otherdoc p.9].", citations: [citation()] })]);
  assert.doesNotMatch(unmatched, /<a href="#citation-otherdoc/);
  assert.match(unmatched, /See \[otherdoc p\.9\]\./);
});

test("a fixture citation renders differently from a source citation", () => {
  const fixture = render([result({ citations: [citation({ content_kind: "fixture", chunk_id: "fx1" })] })]);
  const source = render([result({ citations: [citation({ content_kind: "source", chunk_id: "fx1" })] })]);
  assert.match(fixture, /Fixture corpus/);
  assert.match(fixture, /is-fixture/);
  assert.doesNotMatch(source, /Fixture corpus/);
  assert.doesNotMatch(source, /is-fixture/);
  assert.notEqual(fixture, source);
});

test("the citation frame carries the retrieval and SSE fields through unchanged", () => {
  const markup = render([result({
    citations: [citation({ locator: "§ 100.21", source: "eCFR", version: "retrieval-v7", score: 0.37 })],
  })]);
  for (const value of ["§ 100.21", "eCFR", "retrieval-v7", "0.37"]) {
    assert.ok(markup.includes(value), `citation field ${value} is not rendered`);
  }
});

test("ResultCitation is derived from the generated RetrievalHit contract", async () => {
  const [types, contract] = await Promise.all([
    readFile(new URL("types.ts", resultsRoot), "utf8"),
    readFile(new URL("../src/contracts/copilot-tools.d.ts", import.meta.url), "utf8"),
  ]);
  const pick = types.match(/export type ResultCitation = Pick<\s*RetrievalHit,\s*([^>]+)>/);
  assert.ok(pick, "ResultCitation must be a Pick<> over the generated RetrievalHit");
  const picked = [...pick[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
  const hit = contract.match(/export interface RetrievalHit \{([^}]+)\}/);
  assert.ok(hit, "RetrievalHit is missing from the generated contract");
  const declared = new Set([...hit[1].matchAll(/^\s*([a-z_]+)\??:/gm)].map((match) => match[1]));
  for (const field of picked) {
    assert.ok(declared.has(field), `ResultCitation picks ${field}, which RetrievalHit no longer declares`);
  }
  // The fixture discriminator and source identity must not be dropped on the way to the UI.
  for (const field of ["content_kind", "source", "score", "locator"]) {
    assert.ok(picked.includes(field), `ResultCitation must carry ${field} (spec 05)`);
  }
  assert.match(types, /citation_id\?: string/);
});

test("a number in the answer with no traceable citation renders with the unverified marker", () => {
  const answer = "The fixture corpus reports a shed of 640 MW.";
  const untraced = render([result({ answer, citations: [citation()] })]);
  assert.match(untraced, /<mark class="ask-result__unverified-number">640 \(unverified\)<\/mark>/);

  // The same number, bound to a returned citation, is rendered as evidence instead.
  const traced = render([result({
    answer, citations: [citation()],
    numbers: [{ key: "shed_mw", value: 640, display: "640", citationChunkId: "p4" }],
  })]);
  assert.match(traced, /<a class="ask-result__number" href="#citation-10cfr100-4-p4">640<\/a>/);
  assert.doesNotMatch(traced, /640 \(unverified\)/);
});

test("a bound number whose citation was not returned is still unverified", () => {
  const markup = render([result({
    answer: "The shed is 640 MW.", citations: [citation()],
    numbers: [{ key: "shed_mw", value: 640, display: "640", citationChunkId: "missing-chunk" }],
  })]);
  assert.match(markup, /640 \(unverified\)/);
});

test("done.unverified_numbers forces the unverified marker even on a bound number", () => {
  const markup = render([result({
    answer: "The shed is 640 MW.",
    status: { availability: "synthetic", verified: false, unverifiedNumbers: ["640"] },
    citations: [citation()],
    numbers: [{ key: "shed_mw", value: 640, display: "640", citationChunkId: "p4" }],
  })]);
  assert.match(markup, /640 \(unverified\)/);
  assert.doesNotMatch(markup, /<a class="ask-result__number"/);
  assert.match(markup, /Unverified numbers: 640/);
});

test("every offered action kind is reversible and the card performs no network write", async () => {
  assert.deepEqual([...REVERSIBLE_ACTION_KINDS].sort(), [...ACTION_KINDS].sort());

  const sources = await Promise.all(["ResultCards.tsx", "types.ts", "index.ts"].map(
    (file) => readFile(new URL(file, resultsRoot), "utf8"),
  ));
  const code = sources.join("\n").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  for (const forbidden of [/\bfetch\s*\(/, /XMLHttpRequest/, /sendBeacon/, /"POST"/, /'POST'/, /\bWebSocket\b/, /EventSource/]) {
    assert.doesNotMatch(code, forbidden, `result cards must not perform a network write (${forbidden})`);
  }

  // Behavioural backstop: rendering an actionable card with the network stubbed to throw.
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error("the result cards must not call fetch"); };
  try {
    const markup = render([result({
      status: { availability: "source_supported" },
      action: { kind: "filter", id: "f1", revision: "v1", label: "Filter scene", source: "server", geometry: "source_backed" },
    })], handlers);
    assert.match(markup, /Filter scene/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the harness exercises the empty, unavailable, failed, and fixture frames", async () => {
  const harness = await readFile(new URL("harness.tsx", resultsRoot), "utf8");
  for (const id of ["unavailable-harness", "empty-harness", "failure-harness", "fixture-harness"]) {
    assert.ok(harness.includes(id), `harness is missing the ${id} frame`);
  }
});

test("a result with no citations says so instead of implying evidence", () => {
  const markup = render([result({ answer: "An answer with nothing behind it." })]);
  assert.match(markup, /No citations were returned with this answer/);
  assert.doesNotMatch(markup, /ask-result__citations/);
});
