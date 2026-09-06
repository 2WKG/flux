import assert from "node:assert/strict";
import { mkdir, readFile, readdir } from "node:fs/promises";
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

const repoRoot = new URL("../../../", import.meta.url);
const readRepo = (relative) => readFile(new URL(relative, repoRoot), "utf8");

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
  assert.equal(encoded, "mn=v1&mode=aggregate&scene=scene%3Amn%3Abaseline%3Av1&artifact=mn%3Aaggregate%3Amanifest%3Av1&hash=sha256%3Af287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05");
  const parsed = mn.readMinnesotaBookmark(`?${encoded}`);
  assert.equal(parsed.kind, "valid");
  assert.equal(parsed.bookmark.context, mn.MINNESOTA_BASELINE_RUN_CONTEXT);
  assert.equal(mn.readMinnesotaBookmark("").kind, "absent");
  for (const search of [
    "?mn=v1",
    `?${encoded}&mn=v1`,
    `?${encoded}&feature=made-up`,
    encoded.replace("mn=v1", "mn=v2"),
    // A link made against a different manifest digest is not this baseline.
    `?${encoded.replace(/hash=[^&]*/, "hash=sha256%3A" + "0".repeat(64))}`,
  ]) {
    assert.equal(mn.readMinnesotaBookmark(search).kind, "invalid", search);
  }
});

test("shareable URLs retain the route and fragment while replacing stale query state", () => {
  assert.equal(
    mn.minnesotaBookmarkUrl(mn.MINNESOTA_BASELINE_RUN_CONTEXT, { pathname: "/minnesota", hash: "#evidence" }),
    "/minnesota?mn=v1&mode=aggregate&scene=scene%3Amn%3Abaseline%3Av1&artifact=mn%3Aaggregate%3Amanifest%3Av1&hash=sha256%3Af287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05#evidence",
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

test("a compare request names the unmounted server route without deriving an aggregate effect", () => {
  const comparison = mn.unavailableMinnesotaComparison(
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
  );
  assert.equal(comparison.kind, "unavailable");
  assert.equal(comparison.code, "mn_comparison_route_unmounted");
  assert.equal(comparison.baseline, mn.MINNESOTA_BASELINE_RUN_CONTEXT);
  assert.equal(comparison.candidate, mn.MINNESOTA_BASELINE_RUN_CONTEXT);
  assert.equal("delta" in comparison, false);
  assert.equal("value" in comparison, false);
});

test("the shareable scene id is the server's highlight vocabulary, not a browser label", async () => {
  // `mn_comparisons.py` returns `highlight_ids` verbatim from the persisted
  // manifest, and the server's own pinned fixture spells them
  // `scene:<context_id>`. Read the server tier and require both literals to
  // occur there: renaming either constant in the browser then fails, which is
  // exactly what "no client-invented scene id" has to mean.
  const route = await readRepo("copilot/routes/mn_comparisons.py");
  assert.match(route, /router = APIRouter\(prefix="\/mn"/);
  assert.match(route, /@router\.post\("\/comparisons"\)/);
  assert.match(route, /"highlight_ids": /);

  const serverFiles = (await readdir(new URL("copilot/", repoRoot)))
    .filter((name) => name.endsWith(".py"))
    .map((name) => `copilot/${name}`)
    .concat(
      (await readdir(new URL("copilot/routes/", repoRoot)))
        .filter((name) => name.endsWith(".py"))
        .map((name) => `copilot/routes/${name}`),
    );
  const serverText = (await Promise.all(serverFiles.map(readRepo))).join("\n");

  assert.ok(
    serverText.includes(mn.MINNESOTA_BASELINE_CONTEXT_ID),
    `no server file names the context id ${mn.MINNESOTA_BASELINE_CONTEXT_ID}`,
  );
  assert.ok(
    serverText.includes(mn.MINNESOTA_AGGREGATE_SCENE_ID),
    `no server file issues the scene id ${mn.MINNESOTA_AGGREGATE_SCENE_ID}`,
  );
  // The scene id is derived from the context id the route takes, never spelled twice.
  assert.equal(mn.MINNESOTA_AGGREGATE_SCENE_ID, `scene:${mn.MINNESOTA_BASELINE_CONTEXT_ID}`);
  assert.equal(mn.MINNESOTA_BASELINE_RUN_CONTEXT.sceneId, mn.MINNESOTA_AGGREGATE_SCENE_ID);
  assert.equal(mn.MINNESOTA_BASELINE_RUN_CONTEXT.contextId, mn.MINNESOTA_BASELINE_CONTEXT_ID);
});

test("the artifact id and digest are the Gate-0 inventory's, not a constant pinned to itself", async () => {
  const inventory = JSON.parse(await readRepo("data/sources/minnesota-accepted-artifact-inventory.json"));
  const accepted = inventory.accepted_product_artifacts;
  assert.ok(Array.isArray(accepted) && accepted.length > 0);
  const artifact = accepted.find((entry) => entry.artifact_id === mn.MINNESOTA_AGGREGATE_ARTIFACT_ID);
  assert.ok(
    artifact,
    `${mn.MINNESOTA_AGGREGATE_ARTIFACT_ID} is not an accepted Gate-0 product artifact: ` +
      accepted.map((entry) => entry.artifact_id).join(", "),
  );
  assert.equal(artifact.truth_label_policy.default, "source_backed");
  // The shareable link carries the manifest's own digest, so a link cannot
  // outlive the bytes it names without saying so.
  assert.equal(mn.MINNESOTA_AGGREGATE_MANIFEST_SHA256, artifact.content_sha256);
  assert.equal(mn.MINNESOTA_BASELINE_RUN_CONTEXT.artifactSha256, artifact.content_sha256);
  assert.match(mn.serializeMinnesotaBookmark(mn.MINNESOTA_BASELINE_RUN_CONTEXT), /(^|&)hash=/);
});

test("the comparison copy names the real route and stays true only while it is unmounted", async () => {
  const comparison = mn.unavailableMinnesotaComparison(
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
    mn.MINNESOTA_BASELINE_RUN_CONTEXT,
  );
  assert.match(comparison.message, /POST \/mn\/comparisons/);
  assert.match(comparison.message, /copilot\/routes\/mn_comparisons\.py/);
  assert.match(comparison.message, /not mounted/);

  // The claim is falsifiable: once 2WKG-436 registers the router, this copy
  // becomes a false statement to the user, and this assertion is what notices.
  const app = await readRepo("copilot/app.py");
  assert.doesNotMatch(
    app,
    /include_router\(\s*mn_comparisons/,
    "mn_comparisons is mounted, so the browser must stop reporting the comparison route unreachable",
  );
});
