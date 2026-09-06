import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-run-context.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: { contents: 'export * from "./minnesota/run-context";', resolveDir: fileURLToPath(root), loader: "ts" },
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const mn = await import(compiled.href);

test("the Minnesota baseline is immutable aggregate metadata with no invented ask selection", () => {
  const baseline = mn.MINNESOTA_BASELINE_RUN_CONTEXT;
  assert.equal(Object.isFrozen(baseline), true);
  assert.equal(Object.isFrozen(baseline.sceneContext), true);
  assert.deepEqual(baseline.sceneContext, {
    scenario_id: null, hour: null, selected_site_id: null, compare_site_id: null, selected_element_id: null, unit_mw: null,
  });
  assert.equal(mn.resetMinnesotaRunContext(), baseline);
});

test("a versioned bookmark round-trips exactly and rejects partial, duplicate, unknown, and future states", () => {
  const encoded = mn.serializeMinnesotaBookmark(mn.MINNESOTA_BASELINE_RUN_CONTEXT);
  assert.equal(encoded, "mn=v1&mode=aggregate&scene=mn%3Acoverage%3Aaggregate%3Av1&artifact=mn%3Aaggregate%3Amanifest%3Av1");
  const parsed = mn.readMinnesotaBookmark(`?${encoded}`);
  assert.equal(parsed.kind, "valid");
  assert.equal(parsed.bookmark.context, mn.MINNESOTA_BASELINE_RUN_CONTEXT);
  assert.equal(mn.readMinnesotaBookmark("").kind, "absent");
  for (const search of ["?mn=v1", `?${encoded}&mn=v1`, `?${encoded}&feature=made-up`, "?mn=v2&mode=aggregate&scene=mn%3Acoverage%3Aaggregate%3Av1&artifact=mn%3Aaggregate%3Amanifest%3Av1"]) {
    assert.equal(mn.readMinnesotaBookmark(search).kind, "invalid", search);
  }
});

test("shareable URLs retain the route and fragment while replacing stale query state", () => {
  assert.equal(
    mn.minnesotaBookmarkUrl(mn.MINNESOTA_BASELINE_RUN_CONTEXT, { pathname: "/minnesota", hash: "#evidence" }),
    "/minnesota?mn=v1&mode=aggregate&scene=mn%3Acoverage%3Aaggregate%3Av1&artifact=mn%3Aaggregate%3Amanifest%3Av1#evidence",
  );
});

test("both RunIdentity fields guard against stale asynchronous results", () => {
  const current = mn.createMinnesotaRunIdentity(mn.MINNESOTA_BASELINE_RUN_CONTEXT, 100);
  const later = mn.createMinnesotaRunIdentity(mn.MINNESOTA_BASELINE_RUN_CONTEXT, 101);
  assert.equal(mn.isCurrentMinnesotaRun(current, current), true);
  assert.equal(mn.isCurrentMinnesotaRun(current, later), false);
  assert.deepEqual(mn.acceptMinnesotaRunResult(current, { identity: current, value: "current" }), { kind: "accepted", value: "current" });
  assert.deepEqual(mn.acceptMinnesotaRunResult(current, { identity: later, value: "stale" }), { kind: "stale" });
  assert.deepEqual(
    mn.acceptMinnesotaRunResult(current, { identity: { ...current, contextRevision: "mn:other" }, value: "wrong-context" }),
    { kind: "stale" },
  );
});

test("a compare request names the absent server contract without deriving an aggregate effect", () => {
  const comparison = mn.unavailableMinnesotaComparison(
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
  );
  assert.deepEqual(comparison, {
    kind: "unavailable",
    code: "mn_server_compare_contract_missing",
    baseline: mn.MINNESOTA_BASELINE_RUN_CONTEXT,
    candidate: mn.MINNESOTA_BASELINE_RUN_CONTEXT,
    message: "No server comparison contract supplies a Minnesota aggregate baseline, candidate, or effect.",
  });
  assert.equal("delta" in comparison, false);
  assert.equal("value" in comparison, false);
});
