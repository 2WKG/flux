import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./FailureTimelinePanel.tsx", import.meta.url), "utf8");

test("accepts only immutable run context and typed server-result facts", () => {
  assert.match(source, /interface MinnesotaRunIdentity \{[\s\S]*readonly runId: string;[\s\S]*readonly contextRevision: string;/);
  assert.match(source, /interface MinnesotaRunContext \{[\s\S]*readonly identity: MinnesotaRunIdentity;/);
  assert.match(source, /type MinnesotaFailureTimelineResult =[\s\S]*readonly status: "ready";[\s\S]*readonly facts: readonly MinnesotaTimelineFact\[\]/);
  assert.match(source, /type MinnesotaTimelineFactKind = "failure" \| "flow" \| "critical_service"/);
  assert.match(source, /function sameIdentity\(/);
  assert.match(source, /const identityMatches = sameIdentity\(context\.identity, result\.identity\);/);
});

test("keeps unavailable, failed, and stale outcomes explicit", () => {
  assert.match(source, /data-timeline-status="stale"/);
  assert.match(source, /data-timeline-status="unavailable"/);
  assert.match(source, /data-timeline-status="failed"/);
  assert.match(source, /Timeline unavailable/);
  assert.match(source, /Timeline request failed/);
  assert.match(source, /The returned timeline does not match the active run and is retained only as stale\./);
  assert.match(source, /<Facts facts=\{result\.facts\} \/>/);
});

test("has no browser transport, topology, renderer, or simulation dependency", () => {
  for (const forbidden of [
    /\bfetch\s*\(/,
    /XMLHttpRequest/,
    /EventSource/,
    /duckdb/i,
    /from ["'][^"']*(?:scene|minnesota-adapter|renderer)[^"']*["']/,
  ]) assert.doesNotMatch(source, forbidden);
});
