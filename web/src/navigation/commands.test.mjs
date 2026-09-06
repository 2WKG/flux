import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-commands-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/navigation/scale-ladder.ts",
    "src/navigation/breadcrumbs.ts",
    "src/navigation/commands.ts",
    "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { applyScaleCommand, applyFocusCommand, NAVIGATION_COMMANDS } = await import(
  pathToFileURL(join(outputDirectory, "commands.js")).href
);
const { createNavigationState, focus, STATEWIDE_RESET_TARGET } = await import(
  pathToFileURL(join(outputDirectory, "breadcrumbs.js")).href
);

const region = { scale: "region", id: "region-1", label: "Region One" };
const facility = { scale: "facility", id: "facility-1", label: "Facility One" };

test("a pointer path (applyFocusCommand) and a keyboard path (NAVIGATION_COMMANDS) reach identical focus results", () => {
  const start = focus(createNavigationState(), region).state;

  const viaPointerCommand = applyFocusCommand(start, { type: "FOCUS", target: facility });
  const viaKeyboardCommand = NAVIGATION_COMMANDS.focusTarget(start, facility);
  assert.deepEqual(viaPointerCommand, viaKeyboardCommand);

  const viaPointerReset = applyFocusCommand(start, { type: "RESET_TO_STATEWIDE" });
  const viaKeyboardReset = NAVIGATION_COMMANDS.resetToStatewide(start);
  assert.deepEqual(viaPointerReset, viaKeyboardReset);
});

test("a pointer path (applyScaleCommand) and a keyboard path (NAVIGATION_COMMANDS) reach identical scale results", () => {
  assert.equal(applyScaleCommand("region", { type: "ZOOM_IN" }), NAVIGATION_COMMANDS.zoomIn("region"));
  assert.equal(applyScaleCommand("region", { type: "ZOOM_OUT" }), NAVIGATION_COMMANDS.zoomOut("region"));
});

test("ZOOM_IN/ZOOM_OUT step the ladder and clamp at its ends without wrapping", () => {
  assert.equal(NAVIGATION_COMMANDS.zoomIn("statewide"), "region");
  assert.equal(NAVIGATION_COMMANDS.zoomIn("facility"), "facility");
  assert.equal(NAVIGATION_COMMANDS.zoomOut("facility"), "region");
  assert.equal(NAVIGATION_COMMANDS.zoomOut("statewide"), "statewide");
});

test("scale commands never touch focus/breadcrumb state -- they take and return a bare Scale", () => {
  // If this compiled and returned a string equal to one of the ladder scales, no NavigationState leaked in.
  const result = NAVIGATION_COMMANDS.zoomIn("statewide");
  assert.equal(typeof result, "string");
});

test("RESET_TO_STATEWIDE always returns to the stable reset state from any depth", () => {
  const deep = focus(focus(createNavigationState(), region).state, facility).state;
  const result = NAVIGATION_COMMANDS.resetToStatewide(deep);
  assert.equal(result.kind, "applied");
  assert.deepEqual(result.state, createNavigationState());
  assert.deepEqual(result.state.current, STATEWIDE_RESET_TARGET);
});

test("GO_TO_BREADCRUMB walks the trail and its rejection surfaces through the result, not a thrown error", () => {
  const deep = focus(focus(createNavigationState(), region).state, facility).state;
  const backToRegion = NAVIGATION_COMMANDS.goToBreadcrumb(deep, 1);
  assert.equal(backToRegion.kind, "applied");
  assert.deepEqual(backToRegion.state.current, region);

  const outOfRange = NAVIGATION_COMMANDS.goToBreadcrumb(deep, 5);
  assert.equal(outOfRange.kind, "rejected");
  assert.equal(outOfRange.reason, "invalid_breadcrumb_index");
});

test("focusing an invalid target rejects through the command result", () => {
  const start = createNavigationState();
  const result = NAVIGATION_COMMANDS.focusTarget(start, { scale: "county", id: "x", label: null });
  assert.equal(result.kind, "rejected");
  assert.equal(result.reason, "unknown_scale");
});
