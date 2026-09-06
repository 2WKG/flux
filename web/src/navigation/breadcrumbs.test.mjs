import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-breadcrumbs-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/navigation/scale-ladder.ts",
    "src/navigation/breadcrumbs.ts",
    "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  STATEWIDE_RESET_TARGET,
  createNavigationState,
  focus,
  goToBreadcrumb,
  resetToStatewide,
} = await import(pathToFileURL(join(outputDirectory, "breadcrumbs.js")).href);

const region = { scale: "region", id: "region-1", label: "Region One" };
const facility = { scale: "facility", id: "facility-1", label: "Facility One" };
const otherRegion = { scale: "region", id: "region-2", label: "Region Two" };

test("the initial state is the stable statewide reset target, and stays stable across calls", () => {
  const first = createNavigationState();
  const second = createNavigationState();
  assert.deepEqual(first, second);
  assert.deepEqual(first.breadcrumbs, [STATEWIDE_RESET_TARGET]);
  assert.deepEqual(first.current, STATEWIDE_RESET_TARGET);
});

test("focusing a deeper target extends the trail", () => {
  const afterRegion = focus(createNavigationState(), region);
  assert.equal(afterRegion.kind, "focused");
  assert.deepEqual(afterRegion.state.breadcrumbs, [STATEWIDE_RESET_TARGET, region]);

  const afterFacility = focus(afterRegion.state, facility);
  assert.equal(afterFacility.kind, "focused");
  assert.deepEqual(afterFacility.state.breadcrumbs, [STATEWIDE_RESET_TARGET, region, facility]);
  assert.deepEqual(afterFacility.state.current, facility);
});

test("focusing a target at an already-visited scale truncates the trail deterministically", () => {
  const deep = focus(focus(createNavigationState(), region).state, facility).state;
  const result = focus(deep, otherRegion);
  assert.equal(result.kind, "focused");
  // facility is dropped because otherRegion is at region's depth, not deeper than it.
  assert.deepEqual(result.state.breadcrumbs, [STATEWIDE_RESET_TARGET, otherRegion]);
});

test("focusing directly to a facility from statewide skips region without inventing it", () => {
  const result = focus(createNavigationState(), facility);
  assert.equal(result.kind, "focused");
  assert.deepEqual(result.state.breadcrumbs, [STATEWIDE_RESET_TARGET, facility]);
});

test("focusing an unknown scale is rejected, not silently coerced", () => {
  const result = focus(createNavigationState(), { scale: "county", id: "x", label: null });
  assert.equal(result.kind, "rejected");
  assert.equal(result.reason, "unknown_scale");
});

test("focusing statewide with any id other than the named reset target is rejected", () => {
  const result = focus(createNavigationState(), { scale: "statewide", id: "not-the-reset-target", label: null });
  assert.equal(result.kind, "rejected");
  assert.equal(result.reason, "invalid_statewide_target");
});

test("goToBreadcrumb walks back to an exact index, never partway or past the end", () => {
  const deep = focus(focus(createNavigationState(), region).state, facility).state;
  assert.deepEqual(deep.breadcrumbs, [STATEWIDE_RESET_TARGET, region, facility]);

  const backToRegion = goToBreadcrumb(deep, 1);
  assert.equal(backToRegion.kind, "navigated");
  assert.deepEqual(backToRegion.state.breadcrumbs, [STATEWIDE_RESET_TARGET, region]);
  assert.deepEqual(backToRegion.state.current, region);

  const backToRoot = goToBreadcrumb(deep, 0);
  assert.equal(backToRoot.kind, "navigated");
  assert.deepEqual(backToRoot.state, createNavigationState());
});

test("goToBreadcrumb rejects an out-of-range or non-integer index rather than clamping", () => {
  const deep = focus(createNavigationState(), region).state;
  for (const badIndex of [-1, 2, 99, 1.5]) {
    const result = goToBreadcrumb(deep, badIndex);
    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "invalid_breadcrumb_index");
  }
});

test("resetToStatewide always returns the same stable state regardless of prior depth", () => {
  const deep = focus(focus(createNavigationState(), region).state, facility).state;
  assert.deepEqual(resetToStatewide(), createNavigationState());
  assert.notDeepEqual(deep, resetToStatewide());
});
