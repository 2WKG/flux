/**
 * The panel's claims are behavioural, so they are asserted on rendered markup.
 *
 * The previous version of this file was `readFile` + regex over the `.tsx`. It
 * never imported, rendered, or called the component, so four mutations that
 * implement exactly the harms the PR disclaims -- promoting a mismatched run to
 * current, renaming the unavailable heading, sorting the server's facts, and
 * fabricating a fact when the server returned none -- all stayed green, and even
 * the positive pins were satisfied by a commented-out line. The source-text
 * negatives for transport are kept, because that is the one thing text can see.
 */
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-failure-timeline.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { FailureTimelinePanel } from "./minnesota/FailureTimelinePanel";
      export * as runContext from "./minnesota/run-context";
      export { STATUS_COPY } from "./source-truth";
      export const render = (props) => renderToStaticMarkup(createElement(FailureTimelinePanel, props));
    `,
    resolveDir: fileURLToPath(root), loader: "tsx", sourcefile: "mn-failure-timeline-test.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic", packages: "external",
  outfile: fileURLToPath(compiled),
});
const panel = await import(compiled.href);

const source = await readFile(new URL("./FailureTimelinePanel.tsx", import.meta.url), "utf8");

// The shell's own context and identity, not a second hand-written copy.
const context = panel.runContext.MINNESOTA_BASELINE_RUN_CONTEXT;
const identity = panel.runContext.createMinnesotaRunIdentity(context, 100);
const otherIdentity = panel.runContext.createMinnesotaRunIdentity(context, 200);

/**
 * A deliberately out-of-order server response: sorting by `at`, by `id`, or by
 * `kind` each produces a different order, so any client-side reordering is
 * visible in the rendered ids.
 */
const SERVER_ORDER = [
  { id: "f-3", at: "2026-02-01T09:40:00Z", kind: "critical_service", label: "Clinic transferred to standby" },
  { id: "f-1", at: "2026-02-01T09:05:00Z", kind: "flow", label: "Corridor import reduced" },
  { id: "f-2", at: "2026-02-01T11:15:00Z", kind: "failure", label: "Unit trip reported", detail: "Reported by the operator." },
];
const SERVER_IDS = SERVER_ORDER.map((fact) => fact.id);

/** The `data-timeline-fact-id` values in the order they were rendered. */
function renderedFactIds(markup) {
  return [...markup.matchAll(/data-timeline-fact-id="([^"]*)"/g)].map((match) => match[1]);
}

test("the server's fact order is rendered byte for byte, never re-sorted client-side", () => {
  const markup = panel.render({
    context,
    identity,
    result: { status: "ready", identity, facts: SERVER_ORDER },
  });
  assert.deepEqual(renderedFactIds(markup), SERVER_IDS);
  // Not the order any plausible client-side sort would produce.
  assert.notDeepEqual(renderedFactIds(markup), [...SERVER_IDS].sort());
  assert.notDeepEqual(
    renderedFactIds(markup),
    [...SERVER_ORDER].sort((a, b) => a.at.localeCompare(b.at)).map((fact) => fact.id),
  );
  // And every displayed timestamp is the server's string, unparsed.
  for (const fact of SERVER_ORDER) assert.ok(markup.includes(`<time>${fact.at}</time>`), `${fact.id} lost its server timestamp`);
});

test("a mismatched identity is retained as stale and is never presented as current", () => {
  const markup = panel.render({
    context,
    identity,
    // The server answered for a different run than the one on screen.
    result: { status: "ready", identity: otherIdentity, facts: SERVER_ORDER },
  });
  assert.match(markup, /data-timeline-freshness="stale"/);
  assert.doesNotMatch(markup, /data-timeline-freshness="current"/);
  assert.match(markup, /The returned timeline does not match the active run and is retained only as stale\./);
  assert.ok(markup.includes(otherIdentity.attemptId), "the stale run is not named");
  assert.ok(markup.includes(identity.attemptId), "the active run is not named");
  // The facts are still the server's, in the server's order.
  assert.deepEqual(renderedFactIds(markup), SERVER_IDS);

  // The matching case is the control: with the same identity it is current.
  const current = panel.render({ context, identity, result: { status: "ready", identity, facts: SERVER_ORDER } });
  assert.match(current, /data-timeline-freshness="current"/);
  assert.doesNotMatch(current, /data-timeline-freshness="stale"/);
});

test("an empty server response renders no fact at all, never a fabricated one", () => {
  const markup = panel.render({ context, identity, result: { status: "ready", identity, facts: [] } });
  assert.deepEqual(renderedFactIds(markup), []);
  assert.doesNotMatch(markup, /<li\b/);
  assert.doesNotMatch(markup, /<time>/);
  assert.match(markup, /No timeline facts were returned for this run\./);
  // A synthesized timestamp would be today's; nothing here may carry one.
  assert.doesNotMatch(markup, new RegExp(new Date().toISOString().slice(0, 4)));
});

test("the outcome tokens are the frozen vocabulary and the headings are its owner's copy", () => {
  const unavailable = panel.render({
    context,
    identity,
    result: { status: "unavailable", identity, message: "No Minnesota timeline artifact is published for this run.", nextStep: "Ask the publisher." },
  });
  assert.match(unavailable, /data-request-status="unavailable"/);
  assert.ok(unavailable.includes(`<h2>${panel.STATUS_COPY.unavailable}</h2>`), "the heading is not STATUS_COPY's");
  assert.match(unavailable, /Next step: Ask the publisher\./);

  const failed = panel.render({
    context,
    identity,
    result: { status: "request_failed", identity, message: "The timeline request did not complete.", requestId: "req-7" },
  });
  // `request_failed`, not the invented `failed`.
  assert.match(failed, /data-request-status="request_failed"/);
  assert.ok(failed.includes(`<h2>${panel.STATUS_COPY.request_failed}</h2>`), "the heading is not STATUS_COPY's");
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Request ID: req-7/);

  // The two rendered outcome tokens are a subset of the six the IA freezes, and
  // the invented spellings are gone from every branch's markup.
  const frozen = new Set(["source_supported", "source_screened", "hypothetical", "synthetic", "unavailable", "request_failed"]);
  for (const markup of [unavailable, failed]) {
    for (const [, token] of markup.matchAll(/data-request-status="([^"]*)"/g)) {
      assert.ok(frozen.has(token), `${token} is not one of the six frozen IA tokens`);
    }
    assert.doesNotMatch(markup, /data-timeline-status=/);
    assert.doesNotMatch(markup, /Timeline unavailable|Timeline request failed/);
  }
});

test("a server-supplied stale message survives alongside the mismatch sentence", () => {
  const message = "The publisher marked this timeline superseded at 11:20Z.";
  const markup = panel.render({
    context,
    identity,
    result: { status: "stale", identity: otherIdentity, facts: SERVER_ORDER, message },
  });
  assert.ok(markup.includes(message), "the server's stale message was dropped");
  assert.match(markup, /The returned timeline does not match the active run and is retained only as stale\./);
});

test("the run context on screen is the shell's, not a second declaration of it", () => {
  const markup = panel.render({ context, identity, result: { status: "ready", identity, facts: [] } });
  const escape = (value) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  for (const value of [identity.attemptId, identity.contextRevision, context.sceneId, context.artifactId, context.mode]) {
    assert.ok(markup.includes(escape(value)), `the run context omits ${value}`);
  }
  // The panel declares no rival MinnesotaRunContext / MinnesotaRunIdentity.
  assert.doesNotMatch(source, /\binterface MinnesotaRunContext\b/);
  assert.doesNotMatch(source, /\binterface MinnesotaRunIdentity\b/);
  assert.match(source, /from "\.\/run-context"/);
});

test("has no browser transport, topology, renderer, or simulation dependency", () => {
  for (const forbidden of [
    /\bfetch\s*\(/,
    /XMLHttpRequest/,
    /EventSource/,
    /duckdb/i,
    /from ["'][^"']*(?:scene|minnesota-adapter|renderer)[^"']*["']/,
    // Nothing may synthesize a timestamp or reorder what the server sent.
    /new Date\(/,
    /\.sort\(/,
  ]) assert.doesNotMatch(source, forbidden);
});
